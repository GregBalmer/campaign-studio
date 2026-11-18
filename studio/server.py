"""Local web server: the app's API plus the built UI, standard library only.

Binds to 127.0.0.1, so it is never reachable from other machines.
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import traceback
import urllib.parse
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, pipeline, providers
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
            if path.startswith("/api/"):
                return self._api(method, path[5:].strip("/").split("/"), query)
            if path.startswith("/files/"):
                return self._files(path[7:])
            return self._static(path)
        except (StudioError, ProviderError) as e:
            self._error(str(e), 400)
        except Exception:
            traceback.print_exc()
            self._error("Something went wrong on our side. The details are in the terminal window.", 500)

    # ------------------------------------------------------------ API
    def _api(self, method: str, parts: list[str], q: dict) -> None:
        b = self._body() if method in ("POST", "PATCH") and not (len(parts) > 2 and parts[2] == "upload") else {}
        by = (b.get("by") or "").strip() or None

        if parts == ["status"]:
            from .notify import slack_webhook
            return self._json({"providers": providers.available(), "default_provider": providers.default_name(),
                               "slack": bool(slack_webhook())})

        if parts == ["settings", "key"] and method == "POST":
            key = (b.get("key") or "").strip()
            if not re.fullmatch(r"sk-[A-Za-z0-9_\-]{20,}", key):
                raise StudioError("That doesn't look like an OpenAI key. It starts with sk-.")
            from .providers.openai_provider import check_key
            check_key(key)
            config.save_env_value("OPENAI_API_KEY", key)
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
            return with_campaign(cid, lambda c: (c.set_provider(b.get("provider", "")), view(c))[1])

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
                return with_campaign(cid, lambda c: (c.approve_master(pid, by or "someone"), view(c))[1])
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
                return with_campaign(cid, lambda c: (c.approve_copy(lang, by or "someone"), view(c))[1])
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
            return with_campaign(cid, lambda c: (c.decide(b["key"], b.get("decision"), by or "someone",
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
    def _files(self, rel: str) -> None:
        root, _, rest = rel.partition("/")
        base = {"workspace": config.WORKSPACE, "outputs": config.OUTPUTS}.get(root)
        p = _safe_file(base, rest) if base else None
        if not p:
            return self._error("Not found.", 404)
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
