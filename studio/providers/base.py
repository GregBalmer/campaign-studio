from __future__ import annotations

from PIL import Image


class ProviderError(RuntimeError):
    """A failure the person using the app should see, already in plain words."""


class ImageProvider:
    """Makes key visuals. `id` and `model` are what report.json records."""
    id = "base"
    label = "Base"
    model = "base"

    def generate_image(self, prompt: str, size: int, seed: int, hints: dict) -> Image.Image:
        """Return a square RGB image `size` pixels across.

        `hints` carries structured brief data (product name, colours) that a real
        model reads from the prompt but the demo generator uses directly.
        """
        raise NotImplementedError


class TextProvider:
    """Translates the campaign message. `text_model` is what report.json records."""
    id = "base"
    label = "Base"
    text_model = "base"

    def translate(self, text: str, source: str, target: str, brief: dict) -> dict:
        """Return {"text": ..., "back_translation": ..., "note": ...}."""
        raise NotImplementedError
