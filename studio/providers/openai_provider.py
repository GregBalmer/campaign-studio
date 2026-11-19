"""OpenAI provider: GPT Image for hero images, a small GPT model for translation.

Uses the standard library's urllib so the project needs no SDK. Every failure
is turned into one sentence a non-technical person can act on.
"""
from __future__ import annotations

import base64
import io
import json
import socket
import time
import urllib.error
import urllib.request

from PIL import Image

from .. import config
from .base import ImageProvider, ProviderError, TextProvider

API = "https://api.openai.com/v1"
RETRY_WAIT = 3  # seconds before the one automatic retry


def _post(path: str, body: dict, timeout: int) -> dict:
    key = config.openai_key()
    if not key:
        raise ProviderError("No OpenAI key is set. Add one under Models, or switch to Demo images.")
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    # A busy or briefly broken service usually answers on a second try, so retry once
    # quietly before telling anyone. Bad keys, billing and policy refusals aren't retried.
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                pass
            low = detail.lower()
            passing = e.code >= 500 or (e.code == 429 and "quota" not in low and "billing" not in low)
            if attempt == 1 and passing:
                time.sleep(RETRY_WAIT)
                continue
            raise ProviderError(_friendly(e.code, detail)) from None
        except (urllib.error.URLError, ConnectionError):
            if attempt == 1:
                time.sleep(RETRY_WAIT)
                continue
            raise ProviderError("Couldn't reach OpenAI. Check the internet connection and try again.") from None
        except (socket.timeout, TimeoutError):
            # Don't double a long wait; a timed-out image request has already taken minutes.
            raise ProviderError("OpenAI took too long to answer. Try again.") from None
    raise ProviderError("Couldn't reach OpenAI. Try again.")


def _friendly(status: int, detail: str) -> str:
    low = detail.lower()
    if status == 401:
        return "OpenAI didn't accept the key. Check it under Models."
    if status == 429 and ("quota" in low or "billing" in low):
        return "The OpenAI account is out of credit. Add billing on platform.openai.com, then try again."
    if status == 429:
        return "OpenAI is busy (rate limit). Wait a few seconds and try again."
    if status == 400 and ("safety" in low or "moderation" in low or "policy" in low):
        return "OpenAI declined this image request under its content policy. Try different wording in the mood."
    if status == 404 or ("model" in low and "not" in low):
        return f"OpenAI doesn't offer the model this app asked for ({detail[:120]})."
    if status >= 500:
        return "OpenAI had a server problem. Try again in a minute."
    return f"OpenAI returned an error ({status}): {detail[:200] or 'no details'}"


class OpenAIProvider(ImageProvider, TextProvider):
    id = "openai"
    label = "OpenAI"

    @property
    def model(self) -> str:  # type: ignore[override]
        return config.image_model()

    @property
    def text_model(self) -> str:  # type: ignore[override]
        return config.text_model()

    def generate_image(self, prompt: str, size: int, seed: int, hints: dict) -> Image.Image:
        # Seed isn't an API parameter; regenerating simply asks again.
        data = _post("/images/generations", {
            "model": config.image_model(),
            "prompt": prompt,
            "size": f"{size}x{size}",
            "quality": "medium",
            "output_format": "png",
            "n": 1,
        }, timeout=180)
        try:
            b64 = data["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("OpenAI answered without an image. Try again.") from None
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")

    def translate(self, text: str, source: str, target: str, brief: dict,
                  instruction: str = "", current: str = "") -> dict:
        from ..brief import LANGUAGE_NAMES
        if source == target:
            return {"text": text, "back_translation": text, "note": "", "drift": ""}
        market = next((m for m in brief.get("markets", []) if m["language"] == target), {})
        instructions = (
            "You localise advertising headlines for social ads. "
            f"Brand: {brief['brand']['name']}. Brand voice: {brief['brand'].get('voice', '')} "
            f"Audience: {brief.get('audience', '')} Market: {market.get('name', target)}. "
            "Adapt the line so it sounds native and natural to that market, not literal. "
            "Keep it about as short as the source; it must fit on an ad. "
            "Do not add claims the source doesn't make. "
            'Reply with JSON only: {"text": "<localised line>", '
            '"back_translation": "<plain English meaning of your line>", '
            '"note": "<one short sentence, in English, on any adaptation choice, or empty>", '
            '"drift": "<if your back_translation means something different from the source, one short line '
            'saying what changed, e.g. Drops \'Made for\'; \'longest days\' becomes \'long summer days\'. '
            'Empty if the meaning is the same.>"}. '
            "The back_translation, note and drift are read by an English-speaking reviewer, so write them in English."
        )
        ask = f"Translate from {LANGUAGE_NAMES.get(source, source)} to {LANGUAGE_NAMES.get(target, target)}:\n{text}"
        if instruction:
            # The reviewer reads only the source language, so their request is in it.
            ask += (f"\n\nThe current translation is: {current}\n"
                    f"The reviewer, who doesn't read {LANGUAGE_NAMES.get(target, target)}, asked for this change: "
                    f"{instruction}\nWrite a new line that does what they asked, still natural and fluent.")
        data = _post("/responses", {
            "model": config.text_model(),
            "instructions": instructions,
            "input": ask,
        }, timeout=60)
        out = _output_text(data)
        try:
            start, end = out.index("{"), out.rindex("}") + 1
            parsed = json.loads(out[start:end])
            return {"text": str(parsed["text"]).strip(),
                    "back_translation": str(parsed.get("back_translation", "")).strip(),
                    "note": str(parsed.get("note", "")).strip(),
                    "drift": str(parsed.get("drift", "")).strip()}
        except (ValueError, KeyError):
            raise ProviderError("The translation came back in an unexpected shape. Try again.") from None

    def suggest_audience(self, brief: dict) -> str:
        products = "; ".join(f"{p.get('name', '')}: {p.get('description', '')}" for p in brief.get("products", []))
        markets = ", ".join(m.get("name", m.get("region", "")) for m in brief.get("markets", []))
        data = _post("/responses", {
            "model": config.text_model(),
            "instructions": (
                "You help a junior designer fill in a social ad brief. Write the target audience in one sentence "
                "of plain English, under 25 words: who they are (an age range), what they do, and why the product "
                "fits them. No marketing jargon, no quotation marks. Reply with the sentence only."
            ),
            "input": f"Brand: {brief['brand']['name']}. Brand voice: {brief['brand'].get('voice', '')}\n"
                     f"Products: {products}\nMessage: {brief.get('message', '')}\nMarkets: {markets}",
        }, timeout=60)
        return _one_line(_output_text(data))

    def describe_photo(self, png: bytes, name: str, brief: dict) -> str:
        data = _post("/responses", {
            "model": config.text_model(),
            "instructions": (
                "Describe the product in this photo for an image generator that will draw it again. "
                "One or two short sentences, under 30 words: the packaging type, colors, cap or closure, "
                "and anything printed on it. Describe only the product, not the background. "
                "Reply with the description only."
            ),
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": f"The product is called {name or 'the product'}."},
                {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png).decode()},
            ]}],
        }, timeout=60)
        return _one_line(_output_text(data))


def _one_line(text: str) -> str:
    text = " ".join(text.split()).strip().strip('"')
    if not text:
        raise ProviderError("OpenAI answered with nothing. Try again.")
    return text


def _output_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts = []
    for item in data.get("output", []) or []:
        if item.get("type") == "message":
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
    return "".join(parts)


def check_key(key: str) -> None:
    """Confirm a key works before saving it, with a cheap read-only call."""
    req = urllib.request.Request(API + "/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            return
    except urllib.error.HTTPError as e:
        raise ProviderError(_friendly(e.code, "")) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        raise ProviderError("Couldn't reach OpenAI to check the key. Check the internet connection.") from None
