"""Image and translation providers.

The pipeline only ever calls `get(name)` and the two methods on the returned
object, so a new provider (Adobe Firefly, an in-house model) drops in here
without the UI or pipeline changing.

There is no silent fallback: if the chosen provider fails, the error reaches the
person using the app, in plain words.
"""
from __future__ import annotations

from .. import config
from .base import Provider, ProviderError


def available() -> list[dict]:
    has_key = bool(config.openai_key())
    return [
        {"id": "mock", "label": "Demo images", "ready": True,
         "detail": "Drawn locally. Free, instant, no key needed. For trying the flow."},
        {"id": "openai", "label": "OpenAI", "ready": has_key,
         "detail": f"Images with {config.image_model()}, translation with {config.text_model()}."
                   if has_key else "Needs an OpenAI API key."},
    ]


def default_name() -> str:
    return "openai" if config.openai_key() else "mock"


def get(name: str) -> Provider:
    if name == "mock":
        from .mock import MockProvider
        return MockProvider()
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    raise ProviderError(f"Unknown image generator '{name}'.")
