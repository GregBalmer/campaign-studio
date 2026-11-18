#!/usr/bin/env python3
"""Start Campaign Studio.

    python3 start.py

The first run sets up a private Python environment in .venv and installs the one
dependency (Pillow). Every run then starts the app and opens your browser.
Press Ctrl+C in this window to stop it.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MIN = (3, 9)
WINDOWS = os.name == "nt"
# What to type to run this again, in this OS's words.
AGAIN = "py start.py" if WINDOWS else "python3 start.py"


def say(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:  # older Windows consoles
        print(msg.encode("ascii", "replace").decode(), flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_environment() -> None:
    """Re-run this script inside .venv, creating it on first use."""
    if Path(sys.prefix).resolve() == VENV.resolve():
        return
    py = venv_python()
    if not py.exists():
        say("First run: setting up (about 30 seconds, only once)...")
        try:
            venv.EnvBuilder(with_pip=True, clear=True).create(VENV)
        except Exception as e:  # venv/ensurepip missing on some Linux installs
            say(f"\nCouldn't create the Python environment: {e}")
            if not WINDOWS:
                say("On Ubuntu/Debian, run:  sudo apt install python3-venv   then try again.")
            sys.exit(1)
    try:
        import importlib.util  # noqa: F401
        check = subprocess.run([str(py), "-c", "import PIL"], capture_output=True)
        if check.returncode != 0:
            say("Installing Pillow (image library)...")
            r = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                                "-r", str(ROOT / "requirements.txt")])
            if r.returncode != 0:
                say(f"\nCouldn't install Pillow. Check the internet connection, then run {AGAIN} again.")
                sys.exit(1)
    except FileNotFoundError:
        say(f"\nThe Python environment looks broken. Delete the .venv folder, then run {AGAIN} again.")
        sys.exit(1)
    args = [str(py), str(Path(__file__).resolve())] + sys.argv[1:]
    if WINDOWS:
        # os.execv on Windows starts a second process and returns the prompt
        # early, which confuses Ctrl+C. Run it as a child and wait instead.
        try:
            sys.exit(subprocess.call(args))
        except KeyboardInterrupt:
            sys.exit(0)
    os.execv(str(py), args)


def free_port(preferred: int = 8765) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 40)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if WINDOWS:
                # On Windows SO_REUSEADDR would let us bind a port that's in use.
                s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
            else:
                # Same option the server uses, so a just-closed port counts as free.
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    if sys.version_info < MIN:
        say(f"Campaign Studio needs Python {MIN[0]}.{MIN[1]} or newer; this is {sys.version.split()[0]}.")
        say(f"Install a current Python from https://www.python.org/downloads/, then run {AGAIN} again.")
        sys.exit(1)
    ensure_environment()

    sys.path.insert(0, str(ROOT))
    from studio import config, pipeline, providers
    from studio.server import make_server

    config.load_env()
    pipeline.ensure_samples()
    port = free_port(int(os.environ.get("STUDIO_PORT", "8765")))
    url = f"http://127.0.0.1:{port}"
    server = make_server(port)

    mode = "OpenAI" if providers.default_name() == "openai" else "Demo images (no API key needed)"
    say("")
    say("  Campaign Studio is running.")
    say(f"  Open:  {url}")
    say(f"  Image generator: {mode}")
    say("  Stop:  press Ctrl+C in this window")
    say("")
    if "--no-browser" not in sys.argv:
        import threading
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        say(f"\nStopped. Your work is saved; run {AGAIN} to pick up where you left off.")


if __name__ == "__main__":
    main()
