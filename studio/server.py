"""Local web server: the app's API plus the built UI, standard library only.

Binds to 127.0.0.1, so it is never reachable from other machines.
"""
from __future__ import annotations

import base64
import http.cookies
import io
import json
import mimetypes
import os
import re
import threading
import traceback
import urllib.parse
import zipfile
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from . import auth, config, pipeline, providers
from .pipeline import Campaign, StudioError, with_campaign
from .providers import ProviderError

MAX_UPLOAD = 40 * 1024 * 1024


def _safe_file(base: Path, rel: str) -> Path | None:
    p = (base / rel).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "CampaignStudio/1.0"
    user: dict | None = None  # the signed-in person, set per request

    def log_message(self, fmt, *args):  # keep the terminal quiet and friendly
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ helpers
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            return {}

    def _raw(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise StudioError("That file is over 40 MB. Use a smaller image.")
        return self.rfile.read(n)

    # ------------------------------------------------------------ dispatch
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        url = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(url.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            if path.startswith("/api/auth/"):
                return self._auth(method, path[10:].strip("/"))
            if path.startswith(("/api/", "/files/")) and path != "/api/status":
                self.user = auth.who(self._token())
                if not self.user:
                    return self._json({"error": "Sign in to continue.", "signin": True}, 401)
            if path.startswith("/api/"):
                return self._api(method, path[5:].strip("/").split("/"), query)
            if path.startswith("/files/"):
                return self._files(path[7:], query)
            return self._static(path)
        except auth.AuthError as e:
            self._error(str(e), 401)
        except (StudioError, ProviderError) as e:
            self._error(str(e), 400)
        except Exception:
            traceback.print_exc()
            self._error("Something went wrong on our side. The details are in the terminal window.", 500)

    # ------------------------------------------------------------ sign-in
    def _token(self) -> str | None:
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except http.cookies.CookieError:
            return None
        return jar[auth.COOKIE].value if auth.COOKIE in jar else None

    def _cookie(self, value: str, max_age: int) -> dict:
        # HttpOnly: page scripts can't read it. SameSite=Strict: other sites can't use it.
        return {"Set-Cookie": f"{auth.COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"}

    def _auth(self, method: str, action: str) -> None:
        if action == "me" and method == "GET":
            return self._json({"user": auth.who(self._token()), "demo": auth.demo_accounts()})
        if action == "login" and method == "POST":
            b = self._body()
            token, user = auth.sign_in(b.get("email", ""), b.get("password", ""))
            body = json.dumps({"user": user}).encode()
            return self._send(200, body, "application/json; charset=utf-8",
                              self._cookie(token, auth.SESSION_DAYS * 86400))
        if action == "logout" and method == "POST":
            auth.sign_out(self._token())
            return self._send(200, b'{"user": null}', "application/json; charset=utf-8", self._cookie("", 0))
        return self._error("Not found.", 404)

    # ------------------------------------------------------------ API
    def _api(self, method: str, parts: list[str], q: dict) -> None:
        b = self._body() if method in ("POST", "PATCH") and not (len(parts) > 2 and parts[2] == "upload") else {}
        # Approvals are stamped with whoever is signed in, never a name the browser sends.
        by = self.user["name"] if self.user else None

        if parts == ["status"]:
            from .notify import slack_webhook
            return self._json({"providers": providers.available(),
                               "default_providers": {k: providers.default_name(k) for k in providers.KINDS},
                               "slack": bool(slack_webhook())})

        if parts == ["settings", "key"] and method == "POST":
            key = (b.get("key") or "").strip()
            if not re.fullmatch(r"sk-[A-Za-z0-9_\-]{20,}", key):
                raise StudioError("That doesn't look like an OpenAI key. It starts with sk-.")
            from .providers.openai_provider import check_key
            check_key(key)
            config.save_env_value("OPENAI_API_KEY", key)
            return self._json({"providers": providers.available()})

        if parts == ["settings", "firefly"] and method == "POST":
            client_id = str(b.get("client_id") or "").strip()
            secret = str(b.get("client_secret") or "").strip()
            if not client_id or not secret:
                raise StudioError("Enter both the client ID and the client secret.")
            if re.search(r"\s", client_id) or re.search(r"\s", secret):
                raise StudioError("The client ID and secret can't contain spaces. Copy them again from the Adobe Developer Console.")
            from .providers.firefly import check_credentials
            check_credentials(client_id, secret)
            config.save_env_value("FIREFLY_CLIENT_ID", client_id)
            config.save_env_value("FIREFLY_CLIENT_SECRET", secret)
            return self._json({"providers": providers.available()})

        if parts == ["campaigns"]:
            if method == "POST":
                cid = pipeline.create_campaign(b.get("name") or "New campaign")
                return self._json(Campaign(cid).view())
            return self._json(pipeline.list_campaigns())

        if len(parts) < 2 or parts[0] != "campaigns":
            return self._error("Not found.", 404)
        cid, rest = parts[1], parts[2:]

        def view(c: Campaign | None = None):
            return self._json((c or Campaign(cid)).view())

        if not rest:
            pipeline.ensure_samples()
            return view()
        head = rest[0]

        if head == "reset" and method == "POST":
            pipeline.reset_sample(cid)
            return view()

        if head == "brief" and method == "PATCH":
            return with_campaign(cid, lambda c: (c.update_brief(b), view(c))[1])

        if head == "provider" and method == "POST":
            return with_campaign(cid, lambda c: (c.set_provider(str(b.get("kind", "")), str(b.get("provider", ""))),
                                                 view(c))[1])

        if head == "upload" and method == "POST":
            data = self._raw()
            target = q.get("target", "")
            return with_campaign(cid, lambda c: (c.save_upload(target, data, q.get("name", "")), view(c))[1])

        if head == "products" and len(rest) >= 3:
            pid, action = rest[1], rest[2]
            if action == "master" and method == "POST":
                pipeline.generate_master(cid, pid, by)
                return view()
            if action == "photo" and method == "DELETE":
                return with_campaign(cid, lambda c: (c.remove_photo(pid), view(c))[1])
            if action == "source" and method == "POST":
                return with_campaign(cid, lambda c: (c.use_photo_or_generate(pid, bool(b.get("generate"))), view(c))[1])
            if action == "focal" and method == "POST":
                return with_campaign(cid, lambda c: (c.set_focal(pid, float(b["x"]), float(b["y"]),
                                                                   b.get("w"), b.get("h")), view(c))[1])
            if action == "approve" and method == "POST":
                return with_campaign(cid, lambda c: (c.approve_master(pid, by), view(c))[1])
            if action == "reopen" and method == "POST":
                return with_campaign(cid, lambda c: (c.reopen_master(pid, by), view(c))[1])

        if head == "translate" and method == "POST":
            pipeline.translate_all(cid, by, force=bool(b.get("force")))
            return view()

        if head == "copy" and len(rest) >= 2:
            lang = rest[1]
            if len(rest) == 2 and method == "POST":
                return with_campaign(cid, lambda c: (c.edit_copy(lang, b.get("text", ""), by), view(c))[1])
            if len(rest) == 3 and rest[2] == "approve" and method == "POST":
                return with_campaign(cid, lambda c: (c.approve_copy(lang, by), view(c))[1])
            if len(rest) == 3 and rest[2] == "reopen" and method == "POST":
                return with_campaign(cid, lambda c: (c.reopen_copy(lang, by), view(c))[1])

        if head == "preview" and method == "GET":
            c = Campaign(cid)
            text = q.get("text")
            png, checks = c.preview_png(q["product"], q["format"], q["lang"], text, int(q.get("w", 720)))
            return self._json({"image": "data:image/jpeg;base64," + base64.b64encode(png).decode(),
                               "checks": checks})

        if head == "market-request" and method == "POST":
            region = str(b.get("region", ""))[:8]
            via = b.get("via", "")
            if via == "slack":
                from .notify import NotifyError, post_to_slack
                try:
                    post_to_slack(str(b.get("text", ""))[:3500])
                except NotifyError as e:
                    raise StudioError(str(e)) from None
            return with_campaign(cid, lambda c: (c.record_market_request(region, via, by), view(c))[1])

        if head == "fanout" and method == "POST":
            return with_campaign(cid, lambda c: (c.fan_out(by), view(c))[1])

        if head == "decide" and method == "POST":
            return with_campaign(cid, lambda c: (c.decide(b["key"], b.get("decision"), by,
                                                          b.get("note", "")), view(c))[1])

        if head == "download" and method == "GET":
            return self._download(cid, q.get("only") == "approved")

        return self._error("Not found.", 404)

    def _download(self, cid: str, approved_only: bool) -> None:
        c = Campaign(cid)
        out = c.out_dir()
        if not (out / "report.json").exists():
            raise StudioError("There's nothing to download yet.")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in c.state["frames"].values():
                d = f.get("decision") or {}
                if approved_only and d.get("value") != "approved":
                    continue
                p = out / f["path"]
                if p.exists():
                    z.write(p, f"{cid}/{f['path']}")
            z.write(out / "report.json", f"{cid}/report.json")
        name = f"{cid}{'-approved' if approved_only else ''}.zip"
        self._send(200, buf.getvalue(), "application/zip",
                   {"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------ files
    def _files(self, rel: str, query: dict | None = None) -> None:
        root, _, rest = rel.partition("/")
        base = {"workspace": config.WORKSPACE, "outputs": config.OUTPUTS}.get(root)
        p = _safe_file(base, rest) if base else None
        if not p:
            return self._error("Not found.", 404)
        width = (query or {}).get("w", "")
        if width.isdigit() and p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            # A screen-sized JPEG of a large image, so the interface doesn't wait on a 2-3 MB PNG.
            return self._send(200, _preview(p, min(2400, max(64, int(width)))), "image/jpeg")
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        self._send(200, p.read_bytes(), ctype)

    def _static(self, path: str) -> None:
        if not config.WEB_DIST.exists():
            return self._send(200, b"<h1>The app's interface hasn't been built.</h1>"
                                   b"<p>Run <code>cd web && npm install && npm run build</code>.</p>",
                              "text/html; charset=utf-8")
        p = _safe_file(config.WEB_DIST, path.lstrip("/") or "index.html") or config.WEB_DIST / "index.html"
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, p.read_bytes(), ctype)


_previews: "OrderedDict[tuple, bytes]" = OrderedDict()
_previews_lock = threading.Lock()


def _preview(p: Path, width: int) -> bytes:
    key = (str(p), p.stat().st_mtime_ns, width)
    with _previews_lock:
        if key in _previews:
            _previews.move_to_end(key)
            return _previews[key]
    img = Image.open(p)
    img.load()
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=86, optimize=True)
    data = buf.getvalue()
    with _previews_lock:
        _previews[key] = data
        while len(_previews) > 96:
            _previews.popitem(last=False)
    return data


def make_server(port: int) -> ThreadingHTTPServer:
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("font/woff2", ".woff2")
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    if os.name == "nt":
        # Windows: SO_REUSEADDR lets a second server share the port; use exclusive binding.
        ThreadingHTTPServer.allow_reuse_address = False
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    return srv
