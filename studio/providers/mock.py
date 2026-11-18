"""Demo provider: draws a plausible product scene locally, with no network or key.

It exists so anyone can walk the whole flow for free. Its images are obviously
illustrations, never presented as photography, and the report records them as
"mock".
"""
from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import config
from .base import Provider

# Hand-checked translations of the sample message, so the demo reads naturally.
# Anything else is returned untranslated and clearly marked.
KNOWN = {
    ("Made for the longest days.", "ja"): (
        "いちばん長い日のために。", "For the longest days.",
    ),
    ("Made for the longest days.", "de"): (
        "Gemacht für die längsten Tage.", "Made for the longest days.",
    ),
}


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class MockProvider(Provider):
    id = "mock"
    label = "Demo images"

    def generate_image(self, prompt: str, size: int, seed: int, hints: dict) -> Image.Image:
        rng = random.Random(seed)
        colors = hints.get("colors", {})
        primary = _hex(colors.get("primary", "#14213D"))
        accent = _hex(colors.get("accent", "#FF6B4A"))
        neutral = _hex(colors.get("neutral", "#F4E9DA"))

        s = size
        img = Image.new("RGB", (s, s))
        d = ImageDraw.Draw(img)

        # Sky: warm golden-hour gradient, hue nudged by seed.
        top = _mix((255, 196, 150), accent, rng.uniform(0.0, 0.35))
        mid = (255, 226, 190)
        horizon = int(s * rng.uniform(0.56, 0.64))
        for y in range(horizon):
            d.line([(0, y), (s, y)], fill=_mix(top, mid, y / horizon))
        # Sea band, then sand.
        sea_h = int(s * 0.07)
        for y in range(horizon, horizon + sea_h):
            t = (y - horizon) / sea_h
            d.line([(0, y), (s, y)], fill=_mix((86, 128, 156), (150, 176, 186), t))
        for y in range(horizon + sea_h, s):
            t = (y - horizon - sea_h) / max(1, s - horizon - sea_h)
            d.line([(0, y), (s, y)], fill=_mix(_mix(neutral, (232, 205, 170), 0.4), (214, 182, 146), t))

        # Low sun with a soft glow.
        sun_x = int(s * rng.uniform(0.15, 0.85))
        sun_y = horizon - int(s * rng.uniform(0.08, 0.2))
        glow = Image.new("L", (s, s), 0)
        gd = ImageDraw.Draw(glow)
        r = int(s * 0.22)
        gd.ellipse([sun_x - r, sun_y - r, sun_x + r, sun_y + r], fill=170)
        glow = glow.filter(ImageFilter.GaussianBlur(s * 0.08))
        img = Image.composite(Image.new("RGB", (s, s), (255, 236, 200)), img, glow)
        d = ImageDraw.Draw(img)
        sr = int(s * 0.045)
        d.ellipse([sun_x - sr, sun_y - sr, sun_x + sr, sun_y + sr], fill=(255, 244, 222))

        # Product: off-centre on purpose, so the focal point matters when cropping.
        cx = int(s * rng.choice([0.36, 0.42, 0.58, 0.64]))
        base_y = int(s * rng.uniform(0.80, 0.86))
        desc = (hints.get("description", "") + " " + hints.get("name", "")).lower()
        kind = "tube" if "tube" in desc or "gel" in desc else "bottle"
        body = accent if "coral" in desc.split("tube")[0] else _mix(neutral, (255, 255, 255), 0.3)
        cap = primary

        # Shadow.
        sh = Image.new("L", (s, s), 0)
        sd = ImageDraw.Draw(sh)
        sw = int(s * 0.13)
        sd.ellipse([cx - sw, base_y - int(s * 0.02), cx + sw + int(s * 0.06), base_y + int(s * 0.025)], fill=120)
        sh = sh.filter(ImageFilter.GaussianBlur(s * 0.012))
        img = Image.composite(Image.new("RGB", (s, s), (120, 90, 60)), img, sh)
        d = ImageDraw.Draw(img)

        if kind == "bottle":
            w, h = int(s * 0.12), int(s * 0.36)
            x0, y0 = cx - w // 2, base_y - h
            d.rounded_rectangle([x0, y0, x0 + w, base_y], radius=int(w * 0.28), fill=body)
            # Shoulder, collar, nozzle.
            cw = int(w * 0.62)
            d.rounded_rectangle([cx - cw // 2, y0 - int(s * 0.07), cx + cw // 2, y0 + int(s * 0.01)],
                                radius=int(cw * 0.2), fill=cap)
            d.rectangle([cx - int(w * 0.12), y0 - int(s * 0.1), cx + int(w * 0.18), y0 - int(s * 0.07)], fill=cap)
            label_box = [x0 + int(w * 0.12), y0 + int(h * 0.38), x0 + w - int(w * 0.12), y0 + int(h * 0.68)]
        else:
            w, h = int(s * 0.14), int(s * 0.34)
            x0, y0 = cx - w // 2, base_y - h
            # Tube stands on its cap; crimped end at the top.
            d.polygon([(x0 - int(w * 0.06), y0), (x0 + w + int(w * 0.06), y0),
                       (x0 + w, base_y - int(s * 0.06)), (x0, base_y - int(s * 0.06))], fill=body)
            d.rectangle([x0 - int(w * 0.08), y0 - int(s * 0.018), x0 + w + int(w * 0.08), y0 + int(s * 0.008)],
                        fill=_mix(body, (0, 0, 0), 0.08))
            d.rounded_rectangle([cx - int(w * 0.42), base_y - int(s * 0.065), cx + int(w * 0.42), base_y],
                                radius=int(s * 0.012), fill=cap)
            # Small coral sun mark.
            m = int(w * 0.16)
            d.ellipse([cx - m, y0 + int(h * 0.22) - m, cx + m, y0 + int(h * 0.22) + m], fill=accent)
            label_box = [x0 + int(w * 0.12), y0 + int(h * 0.42), x0 + w - int(w * 0.12), y0 + int(h * 0.62)]

        # Highlight down one side for a bit of form.
        hl = Image.new("L", (s, s), 0)
        hd = ImageDraw.Draw(hl)
        hd.rectangle([x0 + int(w * 0.14), y0 + int(h * 0.06), x0 + int(w * 0.24), base_y - int(h * 0.1)], fill=90)
        hl = hl.filter(ImageFilter.GaussianBlur(s * 0.006))
        img = Image.composite(Image.new("RGB", (s, s), (255, 255, 255)), img, hl)
        d = ImageDraw.Draw(img)

        # Label: brand name, small.
        try:
            font = ImageFont.truetype(str(config.FONTS / "Inter.ttf"), max(10, int(s * 0.014)))
            font.set_variation_by_name("SemiBold")
        except OSError:
            font = ImageFont.load_default()
        brand = hints.get("brand", "")
        lb = label_box
        tw = d.textlength(brand.lower(), font=font)
        d.text(((lb[0] + lb[2] - tw) / 2, (lb[1] + lb[3]) / 2 - s * 0.009), brand.lower(),
               fill=cap if body != cap else (255, 255, 255), font=font)

        img = img.filter(ImageFilter.GaussianBlur(0.6))
        # Remember where the product is, so the default focal point is right.
        top = y0 - int(s * (0.1 if kind == "bottle" else 0.018))  # include the nozzle or crimp
        img.info["focal"] = (cx / s, (top + base_y) / 2 / s)
        img.info["zone"] = (w * 0.62 / s, (base_y - top) / 2 / s + 0.01)
        return img

    def translate(self, text: str, source: str, target: str, brief: dict) -> dict:
        if source == target:
            return {"text": text, "back_translation": text, "note": ""}
        hit = KNOWN.get((text.strip(), target))
        if hit:
            return {"text": hit[0], "back_translation": hit[1],
                    "note": "Demo translation from a fixed list. Connect OpenAI for live translation."}
        return {"text": text, "back_translation": text,
                "note": "Demo mode can't translate new wording. Type the translation, or connect OpenAI."}
