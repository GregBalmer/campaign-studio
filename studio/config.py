"""Paths and settings.

Settings come from environment variables, which `.env` in the project root can
supply. The app's key field writes to that same `.env`, so a creative team never
has to open it.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"          # read-only campaign templates (committed)
WORKSPACE = ROOT / "workspace"      # working copies people edit (git-ignored)
OUTPUTS = ROOT / "outputs"          # final creatives (git-ignored)
FONTS = Path(__file__).resolve().parent / "fonts"
WEB_DIST = ROOT / "web" / "dist"
ENV_FILE = ROOT / ".env"

# Final sizes per format. Ratios are what the brief asks for; sizes are what the
# social platforms expect.
FORMATS = {
    "1x1": {"label": "Feed post", "ratio": "1:1", "size": (1080, 1080)},
    "9x16": {"label": "Story / Reel", "ratio": "9:16", "size": (1080, 1920)},
    "16x9": {"label": "Banner / Video", "ratio": "16:9", "size": (1920, 1080)},
}

DEFAULT_IMAGE_MODEL = "gpt-image-2.6-flare"
DEFAULT_TEXT_MODEL = "gpt-6-luna"


def load_env() -> None:
    """Read KEY=VALUE lines from .env into os.environ without overriding real env."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def save_env_value(key: str, value: str) -> None:
    """Set one KEY=VALUE in .env, keeping every other line as it was."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    out, found = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key and not line.lstrip().startswith("#"):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    os.environ[key] = value


def openai_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    return key or None


def image_model() -> str:
    return os.environ.get("STUDIO_IMAGE_MODEL", "").strip() or DEFAULT_IMAGE_MODEL


def text_model() -> str:
    return os.environ.get("STUDIO_TEXT_MODEL", "").strip() or DEFAULT_TEXT_MODEL


# ---------------------------------------------------------------- Adobe Firefly
FIREFLY_IMS = "https://ims-na1.adobelogin.com"
FIREFLY_API = "https://firefly-api.adobe.io"
FIREFLY_SCOPES = "openid,AdobeID,session,additional_info,read_organizations,firefly_api,ff_apis"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def firefly_client_id() -> str | None:
    return _env("FIREFLY_CLIENT_ID") or None


def firefly_client_secret() -> str | None:
    return _env("FIREFLY_CLIENT_SECRET") or None


def firefly_ready() -> bool:
    return bool(firefly_client_id() and firefly_client_secret())


def firefly_model_version() -> str | None:
    """Sent as x-model-version when set; left out otherwise so Adobe picks."""
    return _env("FIREFLY_MODEL_VERSION") or None


def firefly_scopes() -> str:
    return _env("FIREFLY_SCOPES") or FIREFLY_SCOPES


def firefly_ims_url() -> str:
    return (_env("FIREFLY_IMS_URL") or FIREFLY_IMS).rstrip("/")


def firefly_api_url() -> str:
    return (_env("FIREFLY_API_URL") or FIREFLY_API).rstrip("/")


def firefly_test_mode() -> bool:
    """True when either address is overridden, which only tests do. Anything
    made in this mode is labelled as coming from a test server, never Adobe."""
    return bool(_env("FIREFLY_IMS_URL") or _env("FIREFLY_API_URL"))
