"""Brand and legal checks on each finished frame.

Every check answers a question a reviewer would ask, in their words, and says
where on the frame the problem is (a box in 0-1 coordinates) so the app can
mark it on the image instead of in a log.
"""
from __future__ import annotations

import re

from PIL import Image

from .imaging import hex_rgb

PASS, WARN, FAIL = "pass", "warn", "fail"


def _lum(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _worst_background(plate: Image.Image, box) -> float:
    """Luminance of the brightest 10% of the background under a box: white text
    is only as readable as its worst patch."""
    region = plate.crop(tuple(int(v) for v in box)).convert("RGB").resize((48, 48))
    lums = sorted(_lum(p) for p in region.getdata())
    return lums[int(len(lums) * 0.9)]


def contrast_with_white(plate: Image.Image, box) -> float:
    return 1.05 / (_worst_background(plate, box) + 0.05)


def _norm(box, W, H):
    if not box:
        return None
    return [round(box[0] / W, 4), round(box[1] / H, 4), round(box[2] / W, 4), round(box[3] / H, 4)]


def banned_hits(text: str, lang: str, brief: dict) -> list[str]:
    words = (brief.get("banned_words") or {}).get(lang, [])
    hits = []
    for w in words:
        if lang in ("ja", "zh", "ko") or not w.isalpha():
            if w.lower() in text.lower():
                hits.append(w)
        elif re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE):
            hits.append(w)
    return hits


def run(layout: dict, text: str, lang: str, brief: dict) -> list[dict]:
    img: Image.Image = layout["image"]
    W, H = img.size
    short = min(W, H)
    out = []

    def add(cid, label, status, message, box=None):
        out.append({"id": cid, "label": label, "status": status, "message": message,
                    "box": _norm(box, W, H)})

    # 1. Readable message.
    ratio = contrast_with_white(layout["plate"], layout["text_box"])
    if ratio >= 4.5:
        add("readable", "Message is easy to read", PASS, f"Contrast {ratio:.1f}:1 (needs 4.5).")
    elif ratio >= 3:
        add("readable", "Message is easy to read", WARN,
            f"Contrast is {ratio:.1f}:1, a little low. Move the focal point so the text sits on a calmer area.",
            layout["text_box"])
    else:
        add("readable", "Message is easy to read", FAIL,
            f"Contrast is only {ratio:.1f}:1. The message will be hard to read.", layout["text_box"])

    # 2. Message clear of the product.
    tb = layout["text_box"]
    on = layout["text_on_product"]
    if on > 0.15:
        add("clear", "Message stays off the product", FAIL,
            "The message covers the product. Check the product box in step 2.",
            layout["card_box"])
    elif on > 0:
        add("clear", "Message stays off the product", WARN,
            "The message touches the edge of the product.", layout["card_box"])
    else:
        add("clear", "Message stays off the product", PASS, "Text and product don't overlap.")

    # 2b. Product not cut off by the crop.
    vis = layout["product_visible"]
    if vis >= 0.9:
        add("whole", "Product is fully in frame", PASS, "The whole product fits this format.")
    elif vis >= 0.7:
        add("whole", "Product is fully in frame", WARN,
            "The edge of the product is cropped in this format.", layout["product_box"])
    else:
        add("whole", "Product is fully in frame", FAIL,
            f"Only about {vis:.0%} of the product fits this format.", layout["product_box"])

    # 3. Logo present and visible.
    lb = layout["logo_box"]
    if not lb:
        add("logo", "Logo is on the frame", FAIL, "No logo was supplied for this brand.")
    else:
        lr = contrast_with_white(layout["plate"], lb)
        if lr >= 3:
            add("logo", "Logo is on the frame", PASS, f"Logo placed and visible ({lr:.1f}:1).")
        else:
            add("logo", "Logo is on the frame", WARN, f"Logo is placed but faint ({lr:.1f}:1).", lb)

    # 4. Brand colours: how much of the frame sits close to the brand palette.
    colors = brief["brand"]["colors"]
    palette = [hex_rgb(v) for v in colors.values()]
    small = img.convert("RGB").resize((120, int(120 * H / W)))
    px = list(small.getdata())
    near = sum(1 for p in px if min(sum(abs(p[i] - c[i]) for i in range(3)) for c in palette) < 70)
    share = near / len(px)
    if share >= 0.08:
        add("colours", "Brand colours are used", PASS, f"{share:.0%} of the frame sits in the brand palette.")
    else:
        add("colours", "Brand colours are used", WARN,
            f"Only {share:.0%} of the frame is in the brand palette. The image may feel off-brand.")

    # 5. Words allowed by legal.
    hits = banned_hits(text, lang, brief)
    if hits:
        add("words", "No restricted words", FAIL,
            f"Legal restricts: {', '.join(hits)}. Change the wording.", tb)
    else:
        add("words", "No restricted words", PASS, "No restricted words found.")

    # 6. Message fits.
    if layout["too_long"]:
        add("fits", "Message fits the format", FAIL,
            "The message is too long for this format, even at the smallest size. Shorten it.", tb)
    elif layout["shrunk"]:
        add("fits", "Message fits the format", WARN,
            "The message was set smaller than usual to fit.", tb)
    else:
        add("fits", "Message fits the format", PASS, f"Fits on {layout['lines']} line(s) at full size.")

    # 7. Image sharp enough.
    s = layout["source_scale"]
    if s >= 0.75:
        add("sharp", "Image is sharp", PASS, "Enough resolution for this size.")
    elif s >= 0.5:
        add("sharp", "Image is sharp", WARN,
            f"The picture was enlarged {1 / s:.1f}× for this format and may look soft.")
    else:
        add("sharp", "Image is sharp", FAIL,
            f"The picture was enlarged {1 / s:.1f}× for this format. Use a larger photo.")

    return out


def summary(checks: list[dict]) -> str:
    if any(c["status"] == FAIL for c in checks):
        return FAIL
    if any(c["status"] == WARN for c in checks):
        return WARN
    return PASS
