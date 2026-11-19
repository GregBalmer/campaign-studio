"""Fresh-install test: does a new copy set itself up and work, on this OS?

    python tools/smoke_test.py [--screenshot out.png]

Runs start.py exactly as a reviewer would (no API key), waits for it to come
up, signs in as a demo person, walks the whole four-step flow through the API in demo mode, checks the
download and the interface, runs the command-line version, and optionally saves
a screenshot of the review screen with a local Chrome or Edge. GitHub Actions
runs this on Windows, macOS and Linux.

It also proves the Adobe Firefly adapter offline: the adapter's own tests, then
one whole campaign made through a stand-in Firefly server (tools/fake_firefly.py).
"""
from __future__ import annotations

import http.cookiejar
import io
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = os.environ.get("SMOKE_PORT", "8799")
WINDOWS = os.name == "nt"


def log(msg: str) -> None:
    print(f"[smoke] {msg}", flush=True)


# Keeps the sign-in cookie between calls, like a browser.
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(base: str, method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=120) as r:
        data = r.read()
        return json.loads(data) if r.headers.get("Content-Type", "").startswith("application/json") else data


def find_browser() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if os.path.exists(p):
            return p
    return None


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if WINDOWS:  # start.py runs the server as a child; end the whole tree
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def azure_checks(venv_py: Path, clean: dict) -> None:
    """The Azure storage connection, with no Azure account and no network."""
    r = subprocess.run([str(venv_py), "tools/test_azure.py"], cwd=ROOT, env=clean,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"Azure storage tests failed:\n{r.stderr[-1500:]}"
    log("Azure storage tests OK: " + (r.stderr.strip().splitlines() or ["?"])[-3])


def firefly_checks(venv_py: Path, clean: dict) -> None:
    """The Firefly adapter, with no Adobe account and no network."""
    r = subprocess.run([str(venv_py), "tools/test_firefly.py"], cwd=ROOT, env=clean,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"Firefly adapter tests failed:\n{r.stderr[-1500:]}"
    log("Firefly adapter tests OK: " + (r.stderr.strip().splitlines() or ["?"])[-3])

    # One whole campaign through the stand-in server, on a throwaway copy of the
    # sample so the real sample's outputs still come from the demo generator.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    fake = subprocess.Popen([str(venv_py), "tools/fake_firefly.py", "--port", str(port)], cwd=ROOT, env=clean,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cid = "firefly-wiring-test"
    tmp = Path(tempfile.mkdtemp())
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise SystemExit("the stand-in Firefly server didn't start")
        shutil.copytree(ROOT / "samples" / "long-light", tmp / "c")
        brief = json.loads((tmp / "c" / "brief.json").read_text(encoding="utf-8"))
        brief["campaign"] = "Firefly wiring test"
        (tmp / "c" / "brief.json").write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
        base = f"http://127.0.0.1:{port}"
        env = dict(clean, FIREFLY_IMS_URL=base, FIREFLY_API_URL=base,
                   FIREFLY_CLIENT_ID="test-client-id", FIREFLY_CLIENT_SECRET="test-client-secret")
        r = subprocess.run([str(venv_py), "cli.py", str(tmp / "c" / "brief.json"), "--images", "firefly",
                            "--translation", "mock"], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, f"cli.py with the stand-in Firefly server failed: {r.stdout[-600:]} {r.stderr[-600:]}"
        report = json.loads((ROOT / "outputs" / cid / "report.json").read_text(encoding="utf-8"))
        made = [p for p in report["products"] if p["master_origin"] == "generated"]
        assert made, "no key visual was generated through the stand-in server"
        for p in made:
            # A frame from the stand-in must never be recorded as Adobe Firefly's.
            assert (p["provider"], p["model"]) == ("firefly-test", "test-server"), f"recorded as {p['provider']}/{p['model']}"
        assert '"firefly"' not in json.dumps(report), "the report claims Adobe Firefly made something"
        assert report["summary"]["frames"] == 12
        log(f"Firefly wiring OK: {len(made)} key visual(s) made through the stand-in server, recorded as firefly-test")
    finally:
        fake.kill()
        fake.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(ROOT / "workspace" / cid, ignore_errors=True)
        shutil.rmtree(ROOT / "outputs" / cid, ignore_errors=True)


def main() -> int:
    # CI consoles on Windows aren't UTF-8; never let printing a log line fail the test.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    shot = sys.argv[sys.argv.index("--screenshot") + 1] if "--screenshot" in sys.argv else None
    env = dict(os.environ, STUDIO_PORT=PORT, PYTHONUNBUFFERED="1")
    for name in [k for k in env if k == "OPENAI_API_KEY" or k.startswith("FIREFLY_")]:
        env.pop(name)
    if (ROOT / ".env").exists():
        log("note: a .env file exists here; this test expects a fresh copy without one")

    log(f"Python {sys.version.split()[0]} on {sys.platform}")
    t0 = time.time()
    proc = subprocess.Popen([sys.executable, "start.py", "--no-browser"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: [lines.put(ln) for ln in proc.stdout], daemon=True).start()  # type: ignore[union-attr]

    url = None
    try:
        while time.time() - t0 < 600:
            try:
                ln = lines.get(timeout=1)
            except queue.Empty:
                if proc.poll() is not None:
                    raise SystemExit(f"start.py exited early with code {proc.returncode}")
                continue
            print("  | " + ln.rstrip(), flush=True)
            m = re.search(r"Open:\s+(http://\S+)", ln)
            if m:
                url = m.group(1)
                break
        if not url:
            raise SystemExit("start.py never reported a URL")
        log(f"app up at {url} after {time.time() - t0:.0f}s")
        base = url + "/api/campaigns/long-light"

        status = call(url, "GET", "/api/status")
        assert status["default_providers"] == {"image": "mock", "text": "mock"}, "with no key the app must start in demo mode"
        firefly = status["providers"]["image"][-1]
        assert firefly["id"] == "firefly" and not firefly["ready"], "Firefly must wait for credentials"
        assert [p["id"] for p in status["providers"]["text"]] == ["mock", "openai"]
        page = call(url, "GET", "/")
        assert b"<title>Campaign Studio</title>" in page, "interface not served"
        assert b"manifest.webmanifest" in page

        try:
            call(url, "GET", "/api/campaigns")
            raise SystemExit("the app answered without signing in")
        except urllib.error.HTTPError as e:
            assert e.code == 401, f"expected 401 before sign-in, got {e.code}"
        try:
            call(url, "POST", "/api/auth/login", {"email": "sam@solvane.example", "password": "wrong"})
            raise SystemExit("a wrong password was accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        me = call(url, "POST", "/api/auth/login", {"email": "sam@solvane.example", "password": "longlight"})
        assert me["user"]["name"] == "Sam Rivera"
        log("sign-in OK: locked until signed in, wrong password refused, demo account works")
        by = {"by": "Someone Else"}  # ignored: approvals are stamped with the signed-in person
        for kind in ("image", "text"):
            call(base, "POST", "/provider", {"kind": kind, "provider": "mock"})
        try:
            call(base, "POST", "/provider", {"kind": "image", "provider": "firefly"})
            raise SystemExit("Firefly was selectable without credentials")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        try:
            call(url, "POST", "/api/settings/firefly", {"client_id": "has space", "client_secret": "x"})
            raise SystemExit("Firefly credentials with a space were accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        for pid in ("daylight-mist", "after-sun-gel"):
            call(base, "POST", f"/products/{pid}/master", by)
            call(base, "POST", f"/products/{pid}/approve", by)
        call(base, "POST", "/translate", by)
        for lang in ("en", "ja"):
            call(base, "POST", f"/copy/{lang}/approve", by)
        v = call(base, "POST", "/fanout", by)
        frames = v["frames"]
        assert len(frames) == 12, f"expected 12 ads, got {len(frames)}"
        assert not any(f["status"] == "fail" for f in frames.values()), "a sample ad failed its checks"
        for key, f in frames.items():
            call(base, "POST", "/decide", {**by, "key": key, "decision": "approved"})
        v = call(base, "GET", "")
        assert all(f["decision"]["by"] == "Sam Rivera" for f in v["frames"].values()), "approval not stamped with the signed-in person"
        z = zipfile.ZipFile(io.BytesIO(call(base, "GET", "/download?only=approved")))
        pngs = [n for n in z.namelist() if n.endswith(".png")]
        assert len(pngs) == 12 and "long-light/report.json" in z.namelist(), "download incomplete"
        log("four-step flow OK: 12 ads built, checked, approved and downloaded")

        if shot:
            browser = find_browser()
            if browser:
                profile = ROOT / ".smoke-profile"
                for _attempt in range(3):  # headless Chrome is occasionally flaky on CI
                    try:
                        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                        f"--user-data-dir={profile}", "--window-size=1440,900",
                                        "--virtual-time-budget=8000", f"--screenshot={Path(shot).resolve()}",
                                        url + "/#review"], capture_output=True, timeout=120)
                    except subprocess.TimeoutExpired:
                        pass
                    if Path(shot).exists():
                        break
                shutil.rmtree(profile, ignore_errors=True)
                log(f"screenshot {'saved to ' + shot if Path(shot).exists() else 'FAILED'}")
            else:
                log("no Chrome or Edge found; skipping screenshot")
    finally:
        stop(proc)

    venv_py = ROOT / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    clean = dict(env, PYTHONIOENCODING="utf-8")
    firefly_checks(venv_py, clean)
    azure_checks(venv_py, clean)
    r = subprocess.run([str(venv_py), "cli.py", "--provider", "mock"], cwd=ROOT,
                       env=clean,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("\n".join("  | " + ln for ln in r.stdout.splitlines()[-4:]), flush=True)
    assert r.returncode == 0, f"cli.py failed: {r.stderr[-500:]}"
    assert (ROOT / "outputs/long-light/daylight-mist/9x16/JP-ja.png").exists()
    sample = json.loads((ROOT / "outputs/long-light/report.json").read_text(encoding="utf-8"))
    assert all(p["provider"] in (None, "mock") for p in sample["products"]), "the sample must come from the demo generator"
    log(f"command line OK. All checks passed in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
