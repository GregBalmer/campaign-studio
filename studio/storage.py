"""Azure Blob Storage: send the approved ads to the client's own cloud storage.

The brief lists Azure, AWS or Dropbox for storage. Every ad is always saved on
this computer first (outputs/<campaign>/); Azure is an optional second copy,
switched on by pasting one link.

How access works. The client's IT gives a container SAS link: an address for
one container plus a signed token that allows writing, and nothing else, until
a set date. No account key or password is ever stored here. The link is saved
in .env on this computer only, and is never logged, returned to the browser or
put in an error message.

What it does. Each approved ad is uploaded with one request
(PUT <container>/<campaign>/<product>/<ratio>/<market>.png, x-ms-blob-type:
BlockBlob), keeping the same folders as on disk, followed by report.json.
Uploading the same file again replaces it, so sending twice is safe.

Sources, on learn.microsoft.com:
  - Put Blob:        /rest/api/storageservices/put-blob
  - SAS reference:   /rest/api/storageservices/create-service-sas
  - Error codes:     /rest/api/storageservices/blob-service-error-codes

Tested against a stand-in server (tools/fake_azure.py, tools/test_azure.py).
Standard library only, like the other adapters.
"""
from __future__ import annotations

import datetime as dt
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_VERSION = "2021-08-06"
AZURE_HOST = ".blob.core.windows.net"
ENV_KEY = "AZURE_STORAGE_SAS_URL"
RETRY_WAIT = 2

NOT_A_LINK = ("That doesn't look like an Azure container link. In the Azure portal, open the container, "
              "choose Shared access tokens, and copy the Blob SAS URL.")
NOT_AZURE = "That link isn't an Azure Blob Storage address (it should end in .blob.core.windows.net)."
ONE_FILE = "That link is for a single file. Make one for the whole container instead."
NO_CONTAINER = "That link doesn't name a container. Make the link from the container, not the storage account."
NO_WRITE = "That link can't write files. Make a new one with the Create and Write permissions ticked."
EXPIRED = "That link has expired. Make a new one with an end date after you'll need it."
REFUSED = "Azure didn't accept the link. It may have been revoked or copied incompletely. Make a new one."
NOT_FOUND = "Azure can't find that container. Check it still exists, then make a new link."
BUSY = "Azure is busy. Wait a few seconds and try again."
SERVER = "Azure had a server problem. Try again in a minute."
UNREACHABLE = "Couldn't reach Azure. Check the internet connection and try again."
NOT_CONNECTED = "Azure storage isn't connected. Add a container link under Services."


class StorageError(RuntimeError):
    """A plain sentence the person can act on."""


def test_mode() -> bool:
    """True when pointed at the stand-in server, which only tests do."""
    return bool(os.environ.get("AZURE_TEST_HOST", "").strip())


def saved_link() -> str | None:
    return os.environ.get(ENV_KEY, "").strip() or None


def parse(link: str) -> dict:
    """Check a container SAS link without contacting Azure. Returns the parts
    the app needs; raises StorageError with what to fix."""
    try:
        u = urllib.parse.urlsplit(link.strip())
    except ValueError:
        raise StorageError(NOT_A_LINK) from None
    q = urllib.parse.parse_qs(u.query)
    if u.scheme not in ("https", "http") or not u.netloc or "sig" not in q:
        raise StorageError(NOT_A_LINK)
    host = u.hostname or ""
    test_host = os.environ.get("AZURE_TEST_HOST", "").strip()
    if test_host:
        if u.netloc != test_host:
            raise StorageError(NOT_AZURE)
    elif u.scheme != "https" or not host.endswith(AZURE_HOST):
        raise StorageError(NOT_AZURE)
    if q.get("sr", [""])[0] == "b":
        raise StorageError(ONE_FILE)
    parts = [p for p in u.path.split("/") if p]
    if len(parts) != 1:
        raise StorageError(NO_CONTAINER if not parts else ONE_FILE)
    perms = q.get("sp", [""])[0]
    if not ({"c", "w"} & set(perms)):
        raise StorageError(NO_WRITE)
    expires = None
    if q.get("se"):
        try:
            expires = dt.datetime.fromisoformat(q["se"][0].replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            expires = None
        if expires and expires <= dt.datetime.now(dt.timezone.utc):
            raise StorageError(EXPIRED)
    account = host.split(".")[0] if not test_host else "test"
    return {"base": f"{u.scheme}://{u.netloc}/{parts[0]}", "query": u.query,
            "account": account, "container": parts[0],
            "expires": expires.isoformat() if expires else None}


def describe() -> dict:
    """What the Services panel shows. Never includes the token."""
    link = saved_link()
    if not link:
        return {"connected": False, "test": test_mode()}
    try:
        p = parse(link)
    except StorageError as e:
        return {"connected": False, "test": test_mode(), "problem": str(e)}
    return {"connected": True, "test": test_mode(), "account": p["account"],
            "container": p["container"], "expires": p["expires"]}


def _put(p: dict, name: str, data: bytes, ctype: str) -> None:
    """Upload one file. One quiet retry for 429, 5xx and a dropped connection."""
    path = "/".join(urllib.parse.quote(part) for part in name.split("/"))
    req = urllib.request.Request(f"{p['base']}/{path}?{p['query']}", data=data, method="PUT", headers={
        "x-ms-blob-type": "BlockBlob", "x-ms-version": API_VERSION, "Content-Type": ctype})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()
                return
        except urllib.error.HTTPError as e:
            code = (e.headers.get("x-ms-error-code") or "") if e.headers else ""
            try:
                detail = e.read().decode("utf-8", "replace").lower()
            except Exception:
                detail = ""
            finally:
                e.close()
            if attempt == 1 and (e.code == 429 or e.code >= 500):
                time.sleep(RETRY_WAIT)
                continue
            if e.code == 403:
                if code == "AuthorizationPermissionMismatch":
                    raise StorageError(NO_WRITE) from None
                # Azure words an out-of-date signature as "...time...", e.g. "Signed expiry time ...".
                if code == "AuthenticationFailed" and "time" in detail:
                    raise StorageError(EXPIRED) from None
                raise StorageError(REFUSED) from None
            if e.code == 404:
                raise StorageError(NOT_FOUND) from None
            if e.code == 429 or code == "ServerBusy":
                raise StorageError(BUSY) from None
            if e.code >= 500:
                raise StorageError(SERVER) from None
            raise StorageError(f"Azure didn't accept the upload ({e.code}{', ' + code if code else ''}).") from None
        except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError):
            if attempt == 1:
                time.sleep(RETRY_WAIT)
                continue
            raise StorageError(UNREACHABLE) from None


def check(link: str) -> dict:
    """Check a link before saving it: its shape, then one small real upload,
    because a write-only link can't be checked any other way."""
    p = parse(link)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _put(p, "campaign-studio-check.txt",
         f"Campaign Studio connected to this container on {stamp}. Safe to delete.\n".encode(), "text/plain")
    return p


def send(campaign_id: str, files: list[tuple[str, Path]], link: str | None = None) -> int:
    """Upload (name inside the campaign folder, local path) pairs under
    <campaign_id>/. Returns how many were sent."""
    link = link or saved_link()
    if not link:
        raise StorageError(NOT_CONNECTED)
    p = parse(link)
    for name, path in files:
        ctype = "application/json" if name.endswith(".json") else "image/png"
        _put(p, f"{campaign_id}/{name}", path.read_bytes(), ctype)
    return len(files)
