"""Sign-in: who is using the app, so every approval is stamped with a real person.

This is a stand-in for the client's single sign-on (Adobe, Okta, Microsoft Entra).
People live in workspace/team.json with salted, hashed passwords. Signing in sets a
random session token in an HttpOnly cookie; the server, not the browser, decides
whose name goes on an approval.

The first time the app runs, the team is seeded from samples/team.json: fictional
demo people for trying the sample. Add real people with:

    python3 tools/team.py add "Full Name" name@company.com
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time

from . import config

TEAM = config.WORKSPACE / "team.json"
SESSIONS = config.WORKSPACE / "sessions.json"
SEED = config.SAMPLES / "team.json"
COOKIE = "studio_session"
SESSION_DAYS = 14
_ROUNDS = 200_000
_lock = threading.RLock()


class AuthError(Exception):
    """Wrong email or password, or not signed in."""


# ---------------------------------------------------------------- passwords
def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ROUNDS).hex()
    return f"pbkdf2_sha256${_ROUNDS}${salt}${digest}"


def _check(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(test, digest)


# ---------------------------------------------------------------- team
def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def team() -> dict:
    """email -> {name, password, demo?}. Seeds the demo people on first run."""
    with _lock:
        if not TEAM.exists():
            people = {}
            for p in _read(SEED, {"people": []})["people"]:
                people[p["email"].lower()] = {"name": p["name"], "role": p.get("role", ""),
                                              "password": hash_password(p["password"]), "demo": True}
            _write(TEAM, {"people": people})
        return _read(TEAM, {"people": {}})["people"]


def demo_accounts() -> list[dict]:
    """The sample's demo people, with their passwords, for the sign-in page hint.
    Only listed while those accounts still exist in the team."""
    people = team()
    return [{"name": p["name"], "role": p.get("role", ""), "email": p["email"], "password": p["password"]}
            for p in _read(SEED, {"people": []})["people"] if p["email"].lower() in people]


def add_person(name: str, email: str, password: str, role: str = "") -> None:
    email = email.strip().lower()
    if "@" not in email:
        raise AuthError("That doesn't look like an email address.")
    if len(password) < 8:
        raise AuthError("Use a password of at least 8 characters.")
    with _lock:
        data = {"people": team()}
        data["people"][email] = {"name": name.strip(), "role": role.strip(), "password": hash_password(password)}
        _write(TEAM, data)


def remove_person(email: str) -> bool:
    with _lock:
        data = {"people": team()}
        gone = data["people"].pop(email.strip().lower(), None) is not None
        _write(TEAM, data)
        sessions = {t: s for t, s in _read(SESSIONS, {}).items() if s["email"] != email.strip().lower()}
        _write(SESSIONS, sessions)
        return gone


# ---------------------------------------------------------------- sessions
def sign_in(email: str, password: str) -> tuple[str, dict]:
    email = (email or "").strip().lower()
    person = team().get(email)
    # Check a password either way, so a wrong email takes as long as a wrong password.
    if not _check(password or "", person["password"] if person else hash_password("x", "00" * 16)) or not person:
        time.sleep(0.4)
        raise AuthError("That email and password don't match. Check them and try again.")
    token = secrets.token_urlsafe(32)
    with _lock:
        sessions = _read(SESSIONS, {})
        now = time.time()
        sessions = {t: s for t, s in sessions.items() if s["expires"] > now}
        sessions[token] = {"email": email, "expires": now + SESSION_DAYS * 86400}
        _write(SESSIONS, sessions)
    return token, public(email, person)


def sign_out(token: str | None) -> None:
    if not token:
        return
    with _lock:
        sessions = _read(SESSIONS, {})
        if sessions.pop(token, None):
            _write(SESSIONS, sessions)


def who(token: str | None) -> dict | None:
    """The signed-in person for a session token, or None."""
    if not token:
        return None
    s = _read(SESSIONS, {}).get(token)
    if not s or s["expires"] < time.time():
        return None
    person = team().get(s["email"])
    return public(s["email"], person) if person else None


def public(email: str, person: dict) -> dict:
    return {"email": email, "name": person["name"], "role": person.get("role", "")}
