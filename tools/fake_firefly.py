"""A stand-in for Adobe's sign-in and Firefly servers, for testing with no account.

It answers the four calls the adapter makes (token, start a job, job status,
image download) in the shapes Adobe documents, records every request it gets,
and can be told to fail in a chosen way. It is not Adobe and makes no real
images: its picture says "TEST SERVER" across the middle.

In tests:

    fake = FakeFirefly().start()
    ...point FIREFLY_IMS_URL and FIREFLY_API_URL at fake.url...
    fake.stop()

By hand, to try the app's Firefly flow offline:

    python3 tools/fake_firefly.py

It prints the lines to put in the environment before `python3 start.py`, and
the client ID and secret to paste under Models.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
TOKEN = "fake-access-token"
ENDPOINTS = ("token", "generate", "status", "image")


def _test_image(width: int, height: int) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (width, height), (226, 228, 235))
    d = ImageDraw.Draw(img)
    step = max(32, width // 16)
    for x in range(-height, width, step * 2):  # diagonal stripes: obviously not a photograph
        d.polygon([(x, height), (x + step, height), (x + step + height, 0), (x + height, 0)], fill=(206, 210, 222))
    # A plain block near the centre, where the app expects the product to stand.
    bw, bh = width // 6, height // 4
    cx, cy = width // 2, int(height * 0.58)
    d.rounded_rectangle([cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2], radius=bw // 6, fill=(88, 96, 122))
    text = "TEST SERVER"
    scale = max(2, width // 220)
    small = Image.new("L", (len(text) * 6 + 2, 11), 0)
    ImageDraw.Draw(small).text((1, 0), text, fill=255)
    big = small.resize((small.width * scale, small.height * scale))
    img.paste((60, 66, 88), ((width - big.width) // 2, int(height * 0.2)), big)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class FakeFirefly:
    """Start with .start(); read .requests afterwards; change the attributes
    below to shape what it answers."""

    def __init__(self, port: int = 0):
        self.port = port
        self.requests: list[dict] = []
        # endpoint -> answers to give first, each (status, json body[, headers]).
        self.script: dict[str, list] = {k: [] for k in ENDPOINTS}
        self.expires_in = 86399
        self.polls_before_done = 1        # how many times status says "running" first
        self.final_status = "succeeded"   # or failed, cancelled, timeout
        self.result_shape = "result"      # "result" (documented) or "flat"
        self.image_size = (2048, 2048)
        self.empty_outputs = False
        self.status_url: str | None = None   # override, to test a foreign address
        self.image_url: str | None = None
        self._polls: dict[str, int] = {}
        self._jobs = 0
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> "FakeFirefly":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                fake._handle(self, "GET")

            def do_POST(self):
                fake._handle(self, "POST")

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def seen(self, endpoint: str) -> list[dict]:
        return [r for r in self.requests if r["endpoint"] == endpoint]

    def fail(self, endpoint: str, status: int, body: dict | None = None, times: int = 1, headers: dict | None = None) -> None:
        self.script[endpoint].extend([(status, body or {}, headers or {})] * times)

    # ------------------------------------------------------------ answers
    def _handle(self, h: BaseHTTPRequestHandler, method: str) -> None:
        url = urllib.parse.urlparse(h.path)
        n = int(h.headers.get("Content-Length") or 0)
        raw = h.rfile.read(n) if n else b""
        path = url.path
        endpoint = ("token" if path == "/ims/token/v3" else
                    "generate" if path == "/v3/images/generate-async" else
                    "status" if path.startswith("/v3/status/") else
                    "image" if path.startswith("/download/") else
                    "control" if path == "/_fake/fail" else "unknown")
        if endpoint == "control":
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            if q.get("on") not in ENDPOINTS:
                return self._json(h, 400, {"error": "on= must be one of " + ", ".join(ENDPOINTS)})
            self.fail(q["on"], int(q.get("status", "500")), {"error_code": q.get("code", "runtime_error")},
                      times=int(q.get("times", "1")))
            return self._json(h, 200, {"ok": True})
        record = {"endpoint": endpoint, "method": method, "path": path,
                  "headers": {k.lower(): v for k, v in h.headers.items()}, "raw": raw}
        ctype = h.headers.get("Content-Type", "")
        if ctype.startswith("application/x-www-form-urlencoded"):
            record["form"] = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
        elif raw:
            try:
                record["json"] = json.loads(raw.decode())
            except ValueError:
                pass
        with self._lock:
            self.requests.append(record)
            scripted = self.script[endpoint].pop(0) if self.script.get(endpoint) else None
        if scripted:
            return self._json(h, scripted[0], scripted[1], scripted[2] if len(scripted) > 2 else {})
        getattr(self, "_" + endpoint, self._unknown)(h, record)

    def _json(self, h, status: int, body: dict, headers: dict | None = None) -> None:
        data = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(data)

    def _unknown(self, h, record) -> None:
        self._json(h, 404, {"error_code": "not_found", "message": "The fake server has no such address."})

    def _token(self, h, record) -> None:
        form = record.get("form", {})
        if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
            return self._json(h, 400, {"error": "invalid_client", "error_description": "invalid client_id parameter"})
        if "firefly_api" not in form.get("scope", ""):
            return self._json(h, 400, {"error": "invalid_scope", "error_description": "scope is not allowed"})
        self._json(h, 200, {"access_token": TOKEN, "token_type": "bearer", "expires_in": self.expires_in})

    def _authorised(self, h, record) -> bool:
        ok = (record["headers"].get("authorization") == f"Bearer {TOKEN}"
              and record["headers"].get("x-api-key") == CLIENT_ID)
        if not ok:
            self._json(h, 401, {"error_code": "401013", "message": "Oauth token is not valid"})
        return ok

    def _generate(self, h, record) -> None:
        if not self._authorised(h, record):
            return
        with self._lock:
            self._jobs += 1
            job = f"job-{self._jobs}"
            self._polls[job] = 0
        self._json(h, 202, {"jobId": job,
                            "statusUrl": self.status_url or f"{self.url}/v3/status/{job}",
                            "cancelUrl": f"{self.url}/v3/cancel/{job}"})

    def _status(self, h, record) -> None:
        if not self._authorised(h, record):
            return
        job = record["path"].rsplit("/", 1)[-1]
        with self._lock:
            self._polls[job] = self._polls.get(job, 0) + 1
            running = self._polls[job] <= self.polls_before_done
        if running:
            return self._json(h, 200, {"status": "running", "jobId": job})
        if self.final_status != "succeeded":
            return self._json(h, 200, {"status": self.final_status, "jobId": job,
                                       "error_code": "runtime_error", "message": "The job did not finish."})
        seed = 0
        outputs = [] if self.empty_outputs else [
            {"seed": seed, "image": {"url": self.image_url or f"{self.url}/download/{job}.png"}}]
        body = {"status": "succeeded", "jobId": job}
        if self.result_shape == "result":
            body["result"] = {"outputs": outputs}
        else:
            body["outputs"] = outputs
        self._json(h, 200, body)

    def _image(self, h, record) -> None:
        data = _test_image(*self.image_size)
        h.send_response(200)
        h.send_header("Content-Type", "image/png")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)


def main() -> int:
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8899
    fake = FakeFirefly(port).start()
    print("Fake Firefly server running. It is not Adobe; its images say TEST SERVER.")
    print()
    print("Start the app pointed at it (in another window):")
    if sys.platform == "win32":
        print(f'  set FIREFLY_IMS_URL={fake.url}')
        print(f'  set FIREFLY_API_URL={fake.url}')
        print("  py start.py")
    else:
        print(f"  FIREFLY_IMS_URL={fake.url} FIREFLY_API_URL={fake.url} python3 start.py")
    print()
    print("Then under Models, connect Adobe Firefly with:")
    print(f"  Client ID:      {CLIENT_ID}")
    print(f"  Client secret:  {CLIENT_SECRET}")
    print()
    print("To make the next request fail, open for example:")
    print(f"  {fake.url}/_fake/fail?on=generate&status=500&times=2")
    print()
    print("Stop: press Ctrl+C")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        fake.stop()
    return 0


if __name__ == "__main__":
    # Run inside the app's own Python environment (.venv), setting it up if needed.
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import start
    start.ensure_environment(__file__)
    sys.exit(main())
