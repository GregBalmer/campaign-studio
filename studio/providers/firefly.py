"""Adobe Firefly image provider.

Read this first: this adapter is written to Adobe's published API as read on
18 November 2026. It has NOT been run against a live Firefly account, because
none was available. Every request and every error message is proven against a
stand-in server (tools/fake_firefly.py, tools/test_firefly.py), which shows the
adapter does what the documentation describes. It can't show that the
documentation matches the live service.

What it does: sign in, start an image job, wait for it, download the picture.

Sources, all on developer.adobe.com/firefly-services/docs/firefly-api:
  - Sign-in:    /getting-started/
  - Quickstart: /guides/
  - Tutorial:   /guides/how-tos/firefly-generate-image-api-tutorial
  - Reference:  /api/  (and the OpenAPI file it links to, firefly-api.json)

Confirmed in the reference:
  - 2048x2048 is a supported size for Image 3 and Image 4. 1536x1536 is not.
  - A finished job puts its images under result.outputs.
  - Job statuses: pending, running, succeeded, failed, cancelled,
    cancel_pending, timeout.
  - Errors carry {"error_code", "message"}; a 403 names its reason in the
    x-access-error header.
  - x-model-version takes image3 (the default), image4_standard, image4_ultra,
    and two custom-model values this adapter doesn't support.
  - The download link lasts one hour. It's used within seconds.

Still unconfirmed:
  - The allowed range for a seed. Every documented example is between 1 and
    100,000, so seeds are kept in that range.
  - How this endpoint reports a content-policy refusal. Newer endpoints use
    status 451; this one doesn't list it. Both are handled, plus a match on
    the message text, which is a guess.
  - The exact wording Adobe's sign-in server uses for a refused scope.

Not supported: Image 5. It lives at a different address with a different
request (/v4/images/generate-async, aspectRatio instead of size).

Firefly has no text translation, so this is an image provider only.

Standard library only, like openai_provider.py. The secret and the access
token are never logged, returned or put in an error message.
"""
from __future__ import annotations

import io
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

from .. import config
from .base import ImageProvider, ProviderError

RETRY_WAIT = 3      # seconds before the one automatic retry
POLL_EVERY = 2      # seconds between checks on a running job
POLL_LIMIT = 180    # seconds to wait for a job in total
NATIVE = 2048       # the square size asked of Firefly; resized to what the app needs
MODEL_VERSIONS = ("image3", "image4_standard", "image4_ultra")
POLICY_CODES = ("legal_error", "prompt_unsafe", "prompt_entity_denied", "image_unsafe")

NO_CREDENTIALS = "No Firefly credentials are set. Add them under Services, or choose another image generator."
BAD_CREDENTIALS = "Adobe didn't accept the Firefly credentials. Check the client ID and secret under Services."
BAD_SCOPE = ("These credentials aren't set up for Firefly. Ask your Adobe admin to add the "
             "Firefly Services API to the project.")
NO_ACCESS = "This Adobe organisation doesn't have access to Firefly Services. Ask your Adobe admin."
NO_QUOTA = "This Adobe organisation has used up its Firefly allowance. Ask your Adobe admin."
POLICY = "Firefly declined this image request under its content policy. Try different wording in the mood."
BUSY = "Firefly is busy (rate limit). Wait a few seconds and try again."
SERVER = "Firefly had a server problem. Try again in a minute."
JOB_FAILED = "Firefly couldn't make this image. Try again, or change the wording in the mood."
TOO_LONG = "Firefly took too long to answer. Try again."
UNREACHABLE = "Couldn't reach Adobe. Check the internet connection and try again."
NO_IMAGE = "Firefly answered without an image. Try again."
BAD_ADDRESS = "Firefly sent back an address this app doesn't trust, so it stopped. Try again."


class _Refused(Exception):
    """The server answered with an error status."""

    def __init__(self, status: int, payload: dict, headers: dict):
        self.status, self.payload, self.headers = status, payload, headers


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# Calls that carry the secret or the token never follow a redirect, so neither
# can be sent on to an address Adobe didn't name in the documentation.
_direct = urllib.request.build_opener(_NoRedirect)


def _send(req: urllib.request.Request, timeout: int, follow: bool = False) -> bytes:
    """One request, with the same retry rule as OpenAI: one quiet retry for
    429, 5xx and a dropped connection. Nothing else is retried."""
    opener = urllib.request.urlopen if follow else _direct.open
    for attempt in (1, 2):
        try:
            with opener(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if attempt == 1 and (e.code == 429 or e.code >= 500):
                time.sleep(RETRY_WAIT)
                continue
            try:
                payload = json.loads(e.read().decode("utf-8"))
            except Exception:
                payload = {}
            headers = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
            raise _Refused(e.code, payload if isinstance(payload, dict) else {}, headers) from None
        except (socket.timeout, TimeoutError):
            # Don't double a long wait.
            raise ProviderError(TOO_LONG) from None
        except (urllib.error.URLError, ConnectionError) as e:
            if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
                raise ProviderError(TOO_LONG) from None
            if attempt == 1:
                time.sleep(RETRY_WAIT)
                continue
            raise ProviderError(UNREACHABLE) from None
    raise ProviderError(UNREACHABLE)


# ---------------------------------------------------------------- sign-in

_tokens: dict = {}             # (sign-in address, client id, scopes) -> (token, good until)
_token_lock = threading.Lock()  # two products can generate at once


def _fetch_token(client_id: str, client_secret: str) -> tuple:
    """Ask Adobe's sign-in server for an access token.
    POST {ims}/ims/token/v3, form-encoded, client_credentials grant."""
    form = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": config.firefly_scopes(),
    }).encode("utf-8")
    req = urllib.request.Request(config.firefly_ims_url() + "/ims/token/v3", data=form, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        data = json.loads(_send(req, timeout=30).decode("utf-8"))
    except _Refused as e:
        raise ProviderError(_friendly_signin(e)) from None
    except ValueError:
        raise ProviderError("Adobe's sign-in answered in an unexpected shape. Try again.") from None
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise ProviderError("Adobe's sign-in answered without an access token. Try again.")
    try:
        lasts = float(data.get("expires_in", 0))
    except (TypeError, ValueError):
        lasts = 0.0
    return token, time.time() + lasts - 60


def _friendly_signin(e: _Refused) -> str:
    # Unconfirmed: the sign-in server's error wording isn't in the Firefly docs.
    # OAuth servers conventionally answer {"error": "invalid_scope" | "invalid_client"}.
    text = f"{e.payload.get('error', '')} {e.payload.get('error_description', '')}".lower()
    if "scope" in text:
        return BAD_SCOPE
    if e.status in (400, 401):
        return BAD_CREDENTIALS
    if e.status == 429:
        return "Adobe's sign-in is busy. Wait a few seconds and try again."
    if e.status >= 500:
        return "Adobe's sign-in had a server problem. Try again in a minute."
    return f"Adobe's sign-in returned an error ({e.status})."


def _token() -> tuple:
    """Return (client id, token), reusing a token until a minute before it expires."""
    client_id, secret = config.firefly_client_id(), config.firefly_client_secret()
    if not client_id or not secret:
        raise ProviderError(NO_CREDENTIALS)
    key = (config.firefly_ims_url(), client_id, config.firefly_scopes())
    with _token_lock:
        hit = _tokens.get(key)
        if hit and hit[1] > time.time():
            return client_id, hit[0]
        _tokens[key] = _fetch_token(client_id, secret)
        return client_id, _tokens[key][0]


def forget_tokens() -> None:
    with _token_lock:
        _tokens.clear()


def check_credentials(client_id: str, client_secret: str) -> None:
    """Confirm a client ID and secret before saving them, by asking for a token.

    This proves Adobe accepts the pair and the scopes. It does not prove the
    organisation is entitled to generate images: that only shows on the first
    image request.
    """
    _fetch_token(client_id, client_secret)


# ---------------------------------------------------------------- the API

def _detail(payload: dict) -> str:
    parts = [str(payload.get("message") or "")]
    for v in payload.get("validation_errors") or []:
        if isinstance(v, dict) and v.get("msg"):
            where = ".".join(str(x) for x in v.get("loc", []) if x != "body")
            parts.append(f"{where}: {v['msg']}" if where else str(v["msg"]))
    text = " ".join(p for p in parts if p).strip()
    return text or str(payload.get("error_code") or "")


def _is_policy(status: int, payload: dict) -> bool:
    if status == 451 or payload.get("error_code") in POLICY_CODES:
        return True
    # Unconfirmed: a guess at the wording, for a refusal sent as a plain 400 or 422.
    return bool(re.search(r"content policy|guideline|unsafe|denied|blocked", str(payload.get("message") or "").lower()))


def _friendly(e: _Refused) -> str:
    status, payload = e.status, e.payload
    if status == 401:
        return "Adobe didn't accept the Firefly credentials. Check them under Services."
    if status == 403:
        why = e.headers.get("x-access-error", "")
        if why == "quota_exhausted":
            return NO_QUOTA
        if why == "invalid_ims_scope":
            return BAD_SCOPE
        return NO_ACCESS
    if status in (400, 422, 451) and _is_policy(status, payload):
        return POLICY
    if status == 408:
        return TOO_LONG
    if status == 429:
        return BUSY
    if status >= 500:
        return SERVER
    detail = _detail(payload)[:200] or "no details"
    if status in (400, 422):
        return f"Firefly didn't accept the request ({status}): {detail}"
    return f"Firefly returned an error ({status}): {detail}"


def _call(method: str, url: str, client_id: str, token: str, body: dict | None = None,
          extra: dict | None = None) -> dict:
    headers = {"x-api-key": client_id, "Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    headers.update(extra or {})
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        raw = _send(req, timeout=60)
    except _Refused as e:
        if e.status == 401:
            forget_tokens()  # the token may have been revoked; sign in afresh next time
        raise ProviderError(_friendly(e)) from None
    try:
        out = json.loads(raw.decode("utf-8"))
    except ValueError:
        out = None
    if not isinstance(out, dict):
        raise ProviderError("Firefly answered in an unexpected shape. Try again.")
    return out


def _same_place(url: urllib.parse.SplitResult, base: str) -> bool:
    b = urllib.parse.urlsplit(base)
    return (url.scheme, url.hostname, url.port) == (b.scheme, b.hostname, b.port)


def _trusted_status_url(url: str) -> bool:
    """The status address is sent the access token, so it must be Adobe's.
    Adobe's examples use a different host from the API's own, so any https host
    under adobe.io is accepted rather than one exact name."""
    try:
        u = urllib.parse.urlsplit(url)
        if config._env("FIREFLY_API_URL"):   # tests: only the stand-in server itself
            return _same_place(u, config.firefly_api_url())
        return u.scheme == "https" and bool(u.hostname) and u.hostname.endswith(".adobe.io")
    except ValueError:
        return False


def _trusted_image_url(url: str) -> bool:
    """The download link is pre-signed and gets no credentials, so https is enough."""
    try:
        u = urllib.parse.urlsplit(url)
        if u.scheme == "https" and u.hostname:
            return True
        return bool(config._env("FIREFLY_API_URL")) and _same_place(u, config.firefly_api_url())
    except ValueError:
        return False


def _outputs(status: dict) -> list:
    # The reference puts images under result.outputs. Adobe's older tutorial
    # shows them at the top level, so both are read.
    result = status.get("result")
    found = result.get("outputs") if isinstance(result, dict) else None
    if not found:
        found = status.get("outputs")
    return found if isinstance(found, list) else []


class FireflyProvider(ImageProvider):
    """Image generation with Firefly's generate-async endpoint."""

    @property
    def id(self) -> str:  # type: ignore[override]
        # Pointed anywhere but Adobe, a frame must never be recorded as Firefly's.
        return "firefly-test" if config.firefly_test_mode() else "firefly"

    @property
    def label(self) -> str:  # type: ignore[override]
        return "Firefly test server" if config.firefly_test_mode() else "Adobe Firefly"

    @property
    def model(self) -> str:  # type: ignore[override]
        if config.firefly_test_mode():
            return "test-server"
        return config.firefly_model_version() or "firefly (Adobe's default)"

    def generate_image(self, prompt: str, size: int, seed: int, hints: dict) -> Image.Image:
        version = config.firefly_model_version()
        if version and version not in MODEL_VERSIONS:
            raise ProviderError(f"FIREFLY_MODEL_VERSION is set to '{version}'. "
                                f"This app supports {', '.join(MODEL_VERSIONS[:-1])} and {MODEL_VERSIONS[-1]}.")
        client_id, token = _token()
        api = config.firefly_api_url()

        # Start the job. Asynchronous, as Adobe's Quickstart does it.
        job = _call("POST", api + "/v3/images/generate-async", client_id, token, body={
            "prompt": prompt[:1024],            # the documented limit
            "numVariations": 1,
            "size": {"width": NATIVE, "height": NATIVE},
            "contentClass": "photo",
            "seeds": [1 + seed % 100000],
        }, extra={"x-model-version": version} if version else None)
        status_url = job.get("statusUrl")
        if not isinstance(status_url, str) or not _trusted_status_url(status_url):
            raise ProviderError(BAD_ADDRESS)

        # Wait for it.
        deadline = time.time() + POLL_LIMIT
        while True:
            status = _call("GET", status_url, client_id, token)
            state = status.get("status")
            if state == "succeeded":
                break
            if state == "failed":
                raise ProviderError(POLICY if _is_policy(0, status) else JOB_FAILED)
            if state == "cancelled":
                raise ProviderError("Firefly cancelled this image before it finished. Try again.")
            if state == "timeout":
                raise ProviderError(TOO_LONG)
            # pending, running, cancel_pending, or anything new: keep waiting.
            if time.time() + POLL_EVERY > deadline:
                raise ProviderError(TOO_LONG)
            time.sleep(POLL_EVERY)

        try:
            link = _outputs(status)[0]["image"]["url"]
        except (IndexError, KeyError, TypeError):
            raise ProviderError(NO_IMAGE) from None
        if not isinstance(link, str) or not _trusted_image_url(link):
            raise ProviderError(BAD_ADDRESS)

        # Download. The link is pre-signed, so no Adobe headers go with it.
        try:
            raw = _send(urllib.request.Request(link, method="GET"), timeout=60, follow=True)
        except _Refused as e:
            raise ProviderError(SERVER if e.status >= 500 else NO_IMAGE) from None
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception:
            raise ProviderError(NO_IMAGE) from None
        img = img.convert("RGB")
        if img.width != img.height:  # centre-crop to square
            side = min(img.size)
            left, top = (img.width - side) // 2, (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side))
        if img.size != (size, size):
            img = img.resize((size, size), Image.LANCZOS)
        return img
