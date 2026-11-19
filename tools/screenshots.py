"""Retake the four README screenshots (docs/screens/) at exactly 1440x900.

    python3 start.py                  # in one window: the app must be running
    python3 tools/screenshots.py      # in another: retakes all four

    python3 tools/screenshots.py message review       # just some of them
    python3 tools/screenshots.py --url http://127.0.0.1:8766 --out /tmp/shots

It signs in as the sample's demo person (Sam Rivera), hands that sign-in to a
headless Chrome, and walks the sample campaign into the state each screenshot
shows: a key visual waiting for approval, both languages approved, then the ads
built with every passing one approved. So it changes the sample. Choose
"Restart demo" (beside the campaign name) afterwards if you want it back at the start.

Before the first run, make both of the sample's key visuals in the app (the
After-Sun Aloe Gel one is created, not supplied).

Needs Google Chrome, Chromium or Edge. Runs on macOS and Linux; the way it talks
to Chrome isn't available on Windows. Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = "long-light"
# The demo person seeded for the sample, the same one tools/smoke_test.py signs in as.
DEMO_EMAIL, DEMO_PASSWORD = "sam@solvane.example", "longlight"
# Each screenshot: (step in the address, file name). Taken in this order, because
# each one moves the sample along: key visual, then message, then review.
SHOTS = {"key-visual": "2-key-visual.jpg", "message": "3-message.jpg", "review": "4-review.jpg", "brief": "1-brief.jpg"}
WIDTH, HEIGHT = 1440, 900


def say(msg: str) -> None:
    print(msg, flush=True)


def find_chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        if shutil.which(name):
            return shutil.which(name)
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        if os.path.exists(p):
            return p
    return None


class App:
    """The running app's API, signed in like a browser would be."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body or {}).encode() if method != "GET" else None
        req = urllib.request.Request(self.url + path, method=method, data=data, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=300) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise SystemExit(f"The app said no to {method} {path}: {detail}")
        return json.loads(raw) if raw else None

    def sign_in(self) -> dict:
        try:
            return self.call("POST", "/api/auth/login", {"email": DEMO_EMAIL, "password": DEMO_PASSWORD})["user"]
        except urllib.error.URLError:
            raise SystemExit(f"Nothing is answering at {self.url}. Start the app first with: python3 start.py")

    def session(self) -> str:
        return next(c.value for c in self.jar if c.name == "studio_session")


class Chrome:
    """Headless Chrome, driven over its DevTools pipe (file descriptors 3 and 4)."""

    def __init__(self, binary: str):
        self.profile = tempfile.mkdtemp(prefix="studio-shots-")
        cmd_r, self.cmd_w = os.pipe()
        self.out_r, out_w = os.pipe()

        def wire_pipes():  # Chrome reads commands on fd 3 and writes replies on fd 4
            os.dup2(cmd_r, 3)
            os.dup2(out_w, 4)

        self.proc = subprocess.Popen(
            [binary, "--headless=new", "--remote-debugging-pipe", "--hide-scrollbars", "--disable-gpu",
             f"--user-data-dir={self.profile}", f"--window-size={WIDTH},{HEIGHT}", "about:blank"],
            preexec_fn=wire_pipes, close_fds=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(cmd_r)
        os.close(out_w)
        self.buf = b""
        self.n = 0
        page = next(t for t in self.send("Target.getTargets")["targetInfos"] if t["type"] == "page")
        self.session = self.send("Target.attachToTarget", {"targetId": page["targetId"], "flatten": True})["sessionId"]

    def send(self, method: str, params: dict | None = None, session: str | None = None) -> dict:
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        try:
            os.write(self.cmd_w, json.dumps(msg).encode() + b"\0")
        except BrokenPipeError:
            raise SystemExit("Chrome closed unexpectedly. Try again; if it keeps happening, update Chrome.")
        while True:
            while b"\0" not in self.buf:
                chunk = os.read(self.out_r, 1 << 20)
                if not chunk:
                    raise SystemExit("Chrome closed unexpectedly. Try again; if it keeps happening, update Chrome.")
                self.buf += chunk
            raw, self.buf = self.buf.split(b"\0", 1)
            reply = json.loads(raw)
            if reply.get("id") == self.n:
                if "error" in reply:
                    raise SystemExit(f"Chrome couldn't {method}: {reply['error'].get('message')}")
                return reply.get("result", {})

    def page(self, method: str, params: dict | None = None) -> dict:
        return self.send(method, params, self.session)

    def evaluate(self, js: str):
        return self.page("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})["result"].get("value")

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait()
        shutil.rmtree(self.profile, ignore_errors=True)


# Waits until fonts are in and every image on screen has loaded (at most 15 seconds).
SETTLED = """new Promise(done => {
  const start = Date.now();
  const check = () => {
    const ready = document.querySelector('.camphead') && document.fonts.status === 'loaded'
      && [...document.images].every(i => i.complete) && !document.querySelector('.stage-loading');
    if (ready || Date.now() - start > 15000) done(ready); else setTimeout(check, 200);
  };
  check();
})"""


def capture(chrome: Chrome, url: str, step: str, path: Path) -> None:
    # A fresh query string forces a full load, so the page reads the campaign as it is now.
    chrome.page("Page.navigate", {"url": f"{url}/?shot={time.time():.0f}#{step}"})
    time.sleep(0.5)
    if not chrome.evaluate(SETTLED):
        say(f"  {step}: the page was still loading after 15 seconds; taking the picture anyway.")
    chrome.evaluate("window.scrollTo(0, 0); document.activeElement && document.activeElement.blur(); true")
    time.sleep(0.4)  # let hover and focus styles settle
    shot = chrome.page("Page.captureScreenshot", {"format": "jpeg", "quality": 90,
                                                  "clip": {"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT, "scale": 1}})
    path.write_bytes(base64.b64decode(shot["data"]))
    say(f"  saved {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Retake the README screenshots at 1440x900.")
    parser.add_argument("steps", nargs="*", metavar="step",
                        help="any of: brief, key-visual, message, review (default: all four)")
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="where the app is running")
    parser.add_argument("--out", default=str(ROOT / "docs" / "screens"), help="folder to save into")
    args = parser.parse_args()
    unknown = [s for s in args.steps if s not in SHOTS]
    if unknown:
        parser.error(f"unknown step {', '.join(unknown)}. Use any of: brief, key-visual, message, review.")
    steps = [s for s in SHOTS if s in args.steps] if args.steps else list(SHOTS)

    if os.name == "nt":
        raise SystemExit("This script runs on macOS and Linux. On Windows, take the screenshots by hand at 1440x900.")
    binary = find_chrome()
    if not binary:
        raise SystemExit("Couldn't find Google Chrome, Chromium or Edge. Install one, then try again.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    app = App(args.url)
    me = app.sign_in()
    by = {"by": me["name"]}
    base = f"/api/campaigns/{CAMPAIGN}"
    view = app.call("GET", base)
    if any(not (view["products"].get(p["id"]) or {}).get("master") for p in view["brief"]["products"]):
        raise SystemExit("The sample needs both key visuals first. Open the app, make them on the Key visual step, then try again.")

    say(f"Taking {len(steps)} screenshot(s) of {args.url} as {me['name']}...")
    chrome = Chrome(binary)
    try:
        chrome.page("Network.enable")
        chrome.page("Network.setCookie", {"name": "studio_session", "value": app.session(), "url": app.url, "httpOnly": True})
        chrome.page("Emulation.setDeviceMetricsOverride", {"width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False})
        chrome.page("Page.enable")
        for step in steps:
            if step == "key-visual":
                # No ad decisions yet, and the After-Sun key visual waiting for approval.
                for key, frame in app.call("GET", base)["frames"].items():
                    if frame.get("decision"):
                        app.call("POST", f"{base}/decide", {**by, "key": key, "decision": None})
                if (app.call("GET", base)["products"].get("after-sun-gel") or {}).get("approved"):
                    app.call("POST", f"{base}/products/after-sun-gel/reopen", by)
                capture(chrome, app.url, step, out / SHOTS[step])
                app.call("POST", f"{base}/products/after-sun-gel/approve", by)
            elif step == "message":
                # Every language approved, ready to build.
                view = app.call("GET", base)
                for p in view["brief"]["products"]:
                    if not (view["products"].get(p["id"]) or {}).get("approved"):
                        app.call("POST", f"{base}/products/{p['id']}/approve", by)
                view = app.call("GET", base)
                if any(not view["copy"].get(lang) for lang in view["languages"]):
                    app.call("POST", f"{base}/translate", by)
                    view = app.call("GET", base)
                for lang in view["languages"]:
                    if not (view["copy"].get(lang) or {}).get("approved"):
                        app.call("POST", f"{base}/copy/{lang}/approve", by)
                capture(chrome, app.url, step, out / SHOTS[step])
            elif step == "review":
                # The ads built, and every one that passes its checks approved.
                view = app.call("POST", f"{base}/fanout", by)
                for key, frame in view["frames"].items():
                    if frame["status"] == "pass" and not frame.get("decision"):
                        app.call("POST", f"{base}/decide", {**by, "key": key, "decision": "approved"})
                capture(chrome, app.url, step, out / SHOTS[step])
            elif step == "brief":
                capture(chrome, app.url, step, out / SHOTS[step])
    finally:
        chrome.close()
    say("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
