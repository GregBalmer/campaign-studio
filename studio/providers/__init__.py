"""Image and translation providers.

There are two slots, chosen separately: one service makes the images and one
translates the message. They're separate because not every service does both
(Adobe Firefly makes images and has no text translation).

The pipeline only ever calls `get_image(name)` or `get_text(name)` and the one
method on the returned object, so a new provider drops in here without the
pipeline changing. The interface draws its lists from `available()`.

There is no silent fallback: if the chosen provider fails, the error reaches the
person using the app, in plain words.
"""
from __future__ import annotations

from .. import config
from .base import ImageProvider, ProviderError, TextProvider

KINDS = ("image", "text")


def available() -> dict:
    has_key = bool(config.openai_key())
    needs_key = "Needs an OpenAI API key."
    openai = {} if has_key else {"connect": "openai"}
    if config.firefly_test_mode():
        # Never let a frame from a stand-in server be recorded as Adobe Firefly.
        firefly = {"id": "firefly-test", "label": "Firefly test server", "ready": config.firefly_ready(),
                   "detail": "Pointing at a test server, not Adobe."}
        if not firefly["ready"]:
            firefly["connect"] = "firefly"
    elif config.firefly_ready():
        firefly = {"id": "firefly", "label": "Adobe Firefly", "ready": True,
                   "detail": "Adobe's image models under your organisation's licence. "
                             "Written to Adobe's published API, not yet run against a live account."}
    else:
        firefly = {"id": "firefly", "label": "Adobe Firefly", "ready": False, "connect": "firefly",
                   "detail": "Needs your organisation's Firefly Services credentials."}
    return {
        "image": [
            {"id": "mock", "label": "Demo images", "ready": True,
             "detail": "Drawn locally. Free and instant, for trying the flow."},
            {"id": "openai", "label": "OpenAI", "ready": has_key,
             "detail": f"Images with {config.image_model()}." if has_key else needs_key, **openai},
            firefly,
        ],
        "text": [
            {"id": "mock", "label": "Demo translation", "ready": True,
             "detail": "A fixed list for the sample message."},
            {"id": "openai", "label": "OpenAI", "ready": has_key,
             "detail": f"Translation with {config.text_model()}." if has_key else needs_key, **openai},
        ],
    }


def default_name(kind: str = "image") -> str:
    """OpenAI when a key is set, otherwise the demo. Firefly is never a default:
    it hasn't been run against the live service, so a person chooses it."""
    return "openai" if config.openai_key() else "mock"


def resolve(kind: str, name: str) -> str:
    """The id to store for a name someone asked for. 'firefly' and 'firefly-test'
    are the same adapter; which one it is depends on where it's pointed."""
    if kind == "image" and name in ("firefly", "firefly-test"):
        return "firefly-test" if config.firefly_test_mode() else "firefly"
    return name


def get_image(name: str) -> ImageProvider:
    if name == "mock":
        from .mock import MockProvider
        return MockProvider()
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    if name in ("firefly", "firefly-test"):
        from .firefly import FireflyProvider
        return FireflyProvider()
    raise ProviderError(f"Unknown image generator '{name}'.")


def get_text(name: str) -> TextProvider:
    if name == "mock":
        from .mock import MockProvider
        return MockProvider()
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    raise ProviderError(f"Unknown translation service '{name}'.")
