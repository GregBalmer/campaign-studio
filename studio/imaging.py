"""Cropping and layout: from an approved master to a finished ad frame.

The message and logo are drawn on top of the image at the end, never baked into
the generated picture. So editing the copy costs no generation and re-renders in
a fraction of a second.

Layout model: the focal point marks the product, and a "product zone" around it
is the area the message card must stay out of. Every format tries a few card
positions (bottom, top, left or right) and keeps the one that overlaps the
product least.
"""
from __future__ import annotations


import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config

# Half-width and half-height of the product zone, as a share of the master.
ZONE = (0.08, 0.2)
# Bump when the layout rules change, so existing ads are rebuilt (and re-reviewed).
LAYOUT_VERSION = 3  # 3: one card position per product and size, shared by every language

NO_LINE_START = set("。、．，,.!?！？)」』）ー〜ゃゅょっャュョッ")
BREAK_AFTER = set("のにをはがへともでや、。！？」』")

# Per format: headline size as a share of the short side, and which text
# positions to try, in order of preference.
# "safe" keeps text out of the strips where Stories/Reels draw their own UI
# (profile name at the top, reply bar and buttons at the bottom).
LAYOUT = {
    "1x1": {"size": 0.074, "sides": ["bottom", "right", "left", "top"],
            "col_wide": 0.72, "col_side": 0.50, "safe": (0, 0)},
    "9x16": {"size": 0.084, "sides": ["bottom", "top"],
             "col_wide": 0.80, "col_side": None, "safe": (0.12, 0.17)},
    "16x9": {"size": 0.072, "sides": ["right", "left", "bottom"],
             "col_wide": 0.55, "col_side": 0.42, "safe": (0, 0)},
}


def hex_rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@lru_cache(maxsize=64)
@lru_cache(maxsize=512)
def font(lang: str, size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    name = "NotoSansJP.ttf" if lang in ("ja", "zh", "ko") else "Inter.ttf"
    f = ImageFont.truetype(str(config.FONTS / name), size)
    try:
        f.set_variation_by_name(weight)
    except (OSError, ValueError):
        pass
    return f


def estimate_focal(img: Image.Image) -> tuple[float, float]:
    """First guess at where the product is in a supplied photo: the area that
    stands out most from its surroundings, nudged toward the centre. The person
    confirms or moves it in step 2."""
    s = 96
    small = img.convert("RGB").resize((s, s)).filter(ImageFilter.GaussianBlur(1))
    blur = img.convert("RGB").resize((s, s)).filter(ImageFilter.GaussianBlur(12))
    px, bl = small.load(), blur.load()
    scores = []
    for y in range(s):
        for x in range(s):
            centre = 1 - 0.6 * math.hypot(x / s - 0.5, y / s - 0.5) / 0.707
            scores.append((math.dist(px[x, y], bl[x, y]) * centre, x, y))
    scores.sort(reverse=True)
    top = scores[: int(len(scores) * 0.04)]
    total = sum(t[0] for t in top) or 1
    fx = sum(t[0] * t[1] for t in top) / total / s
    fy = sum(t[0] * t[2] for t in top) / total / s
    return round(fx, 4), round(fy, 4)


def crop_to_ratio(img: Image.Image, ratio: float, focal: tuple[float, float]):
    """Largest crop of `ratio` (w/h) that keeps the focal point as central as possible."""
    W, H = img.size
    if W / H > ratio:
        ch, cw = H, int(round(H * ratio))
    else:
        cw, ch = W, int(round(W / ratio))
    fx, fy = focal[0] * W, focal[1] * H
    x0 = int(min(max(fx - cw / 2, 0), W - cw))
    y0 = int(min(max(fy - ch / 2, 0), H - ch))
    box = (x0, y0, x0 + cw, y0 + ch)
    return img.crop(box), box


# ---------------------------------------------------------------- line breaking

def _measure(f) -> callable:
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    return lambda s: draw.textlength(s, font=f)


def _tokens(text: str, cjk: bool) -> tuple[list[str], str]:
    if not cjk:
        return text.split(), " "
    # Break opportunities after particles and punctuation, never before
    # characters that can't start a line.
    toks, cur = [], ""
    for i, ch in enumerate(text):
        cur += ch
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch in BREAK_AFTER and nxt and nxt not in NO_LINE_START:
            toks.append(cur)
            cur = ""
    if cur:
        toks.append(cur)
    return toks, ""


def _char_wrap(text: str, width, max_w: float) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if width(cur + ch) <= max_w or not cur or ch in NO_LINE_START:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def wrap(text: str, f, max_w: float, cjk: bool) -> tuple[list[str], bool]:
    """Fewest lines that fit, then the most even line lengths (no lone last
    word). Japanese breaks at particles, not mid-word."""
    width = _measure(f)
    toks, sep = _tokens(text.strip(), cjk)
    n = len(toks)
    best = {}

    def solve(i):
        if i == n:
            return (0, 0.0, [])
        if i in best:
            return best[i]
        result = None
        for j in range(i + 1, n + 1):
            line = sep.join(toks[i:j])
            w = width(line)
            if w > max_w and j > i + 1:
                break
            if w > max_w:  # a single token wider than the line
                continue
            rest = solve(j)
            if rest is None:
                continue
            cand = (rest[0] + 1, rest[1] + (max_w - w) ** 2, [line] + rest[2])
            if result is None or cand[:2] < result[:2]:
                result = cand
        best[i] = result
        return result

    res = solve(0)
    if res is None:
        return (_char_wrap(text, width, max_w) if cjk else text.split()), False
    return res[2], True


def light_logo(logo: Image.Image) -> Image.Image:
    """White version of a logo for dark backgrounds (keeps its alpha)."""
    logo = logo.convert("RGBA")
    white = Image.new("RGBA", logo.size, (255, 255, 255, 255))
    white.putalpha(logo.getchannel("A"))
    return white


def _overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def _smooth(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- render

def _plan_rank(p: dict, order: int, short: int, base_size: int) -> tuple:
    return (round(p["overlap"] / (short * short), 3), not p["clean"], len(p["lines"]) > 3,
            p["size"] < base_size * 0.85, order)


def shared_side(master: Image.Image, fmt: str, focal: tuple[float, float], texts: list[tuple[str, str]],
                brand: dict, logo_path: Path | None, zone_size: tuple[float, float] = ZONE) -> str:
    """One card position for a product in one size, used by every language, so the
    markets' ads match and only the words change. Each position is judged by its
    worst language: covering the product rules it out first, then awkward breaks,
    more than three lines, and how many languages it would shrink."""
    per_lang = [render(master, fmt, focal, t, lang, brand, logo_path, zone_size, plan_only=True) for t, lang in texts]
    if not per_lang:
        return LAYOUT[fmt]["sides"][0]
    best = None
    for i, s in enumerate(LAYOUT[fmt]["sides"]):
        ps = [(r["plans"][i], r["short"], r["base_size"]) for r in per_lang]
        rank = (max(round(p["overlap"] / (sh * sh), 3) for p, sh, _ in ps),
                any(not p["clean"] for p, _, _ in ps),
                any(len(p["lines"]) > 3 for p, _, _ in ps),
                sum(p["size"] < b * 0.85 for p, _, b in ps),
                i)
        if best is None or rank < best[0]:
            best = (rank, s)
    return best[1]


def render(master: Image.Image, fmt: str, focal: tuple[float, float], text: str, lang: str,
           brand: dict, logo_path: Path | None, zone_size: tuple[float, float] = ZONE,
           side: str | None = None, plan_only: bool = False) -> dict:
    """Compose one finished frame. Returns the image plus the layout boxes the
    checks need (all in output pixels).

    `side` puts the card in a position chosen for every language at once (see
    `shared_side`). `plan_only` stops before drawing and returns each position's plan."""
    spec = config.FORMATS[fmt]
    rules = LAYOUT[fmt]
    W, H = spec["size"]
    crop, box = crop_to_ratio(master, W / H, focal)
    source_scale = crop.size[0] / W  # <1 means the frame was upscaled
    frame = crop.resize((W, H), Image.LANCZOS).convert("RGB")

    mw, mh = master.size
    sx, sy = W / (box[2] - box[0]), H / (box[3] - box[1])

    def to_frame(x, y):
        return (x * mw - box[0]) * sx, (y * mh - box[1]) * sy

    fpx, fpy = to_frame(*focal)
    z0 = to_frame(focal[0] - zone_size[0], focal[1] - zone_size[1])
    z1 = to_frame(focal[0] + zone_size[0], focal[1] + zone_size[1])
    zone_full = (z0[0], z0[1], z1[0], z1[1])
    zone = (max(0, z0[0]), max(0, z0[1]), min(W, z1[0]), min(H, z1[1]))
    zone_area = max(1, (zone_full[2] - zone_full[0]) * (zone_full[3] - zone_full[1]))
    visible = _overlap(zone_full, (0, 0, W, H)) / zone_area

    short = min(W, H)
    margin = int(short * 0.075)
    cjk = lang in ("ja", "zh", "ko")
    base_size = int(short * rules["size"])
    min_size = int(short * 0.05)

    logo_src = None
    if logo_path and logo_path.exists():
        raw = Image.open(logo_path).convert("RGBA")
        lh = int(short * 0.036)
        logo_src = light_logo(raw.resize((max(1, int(raw.width * lh / raw.height)), lh), Image.LANCZOS))

    bar_h = max(4, int(short * 0.008))
    bar_w = int(short * 0.07)
    pad = int(short * 0.05)
    top_safe = max(margin, int(H * rules["safe"][0]))
    bottom_safe = max(margin, int(H * rules["safe"][1]))

    # Room beside the product on each side, keeping a small breathing gap.
    breathe = int(short * 0.02)
    zl, zt, zr, zb = zone

    def room(side: str) -> tuple[int, int]:
        """Widest and tallest a card can be on this side without touching the product."""
        w, h = W - 2 * margin, H - top_safe - bottom_safe
        if side == "left":
            w = int(zl - breathe - margin)
        elif side == "right":
            w = int(W - margin - zr - breathe)
        elif side == "top":
            h = int(zt - breathe - top_safe)
        elif side == "bottom":
            h = int(H - bottom_safe - zb - breathe)
        return w, h

    def plan(side: str) -> dict:
        col = rules["col_side"] if side in ("left", "right") else rules["col_wide"]
        room_w, room_h = room(side)
        col_w = int(W * col) - 2 * pad
        if room_w - 2 * pad >= short * 0.25:  # enough room beside it: stay inside it
            col_w = min(col_w, room_w - 2 * pad)
        if room_h < short * 0.2:  # no real room above or below: don't try to fit
            room_h = H
        size = base_size
        while True:
            lines, clean = wrap(text, font(lang, size), col_w, cjk)
            line_h = int(size * (1.34 if cjk else 1.1))
            gap = int(size * 0.45)
            logo_gap = int(size * 0.7)
            content_h = bar_h + gap + line_h * len(lines) - int(line_h - size) + \
                (logo_gap + logo_src.height if logo_src else 0)
            # Two lines read best; go a little smaller to get there before
            # accepting three. Shrink further only if the card won't fit the room.
            target = 2 if size > base_size * 0.86 else 3
            if (len(lines) <= target and clean and content_h + 2 * pad <= room_h) or size <= min_size:
                break
            size = max(min_size, int(size * 0.92))
        text_w = max(_measure(font(lang, size))(ln) for ln in lines)
        content_w = int(max(text_w, bar_w, logo_src.width if logo_src else 0))
        card_w, card_h = content_w + 2 * pad, content_h + 2 * pad
        if side == "top":
            cx, cy = margin, top_safe
        elif side == "right":
            cx, cy = W - margin - card_w, H - bottom_safe - card_h
        else:  # bottom, left: anchored bottom-left
            cx, cy = margin, H - bottom_safe - card_h
        card = (cx, cy, cx + card_w, cy + card_h)
        return {"side": side, "size": size, "lines": lines, "line_h": line_h, "clean": clean,
                "gap": gap, "logo_gap": logo_gap, "card": card, "x": cx + pad, "y": cy + pad,
                "overlap": _overlap(card, zone)}

    plans = [plan(s) for s in rules["sides"]]
    if plan_only:
        return {"plans": plans, "short": short, "base_size": base_size}
    forced = [p for p in plans if p["side"] == side]
    # Least overlap with the product wins; then clean line breaks, full size,
    # and the format's preferred position.
    chosen = forced[0] if forced else min(enumerate(plans), key=lambda ip: _plan_rank(ip[1], ip[0], short, base_size))[1]
    side, x, y = chosen["side"], chosen["x"], chosen["y"]
    lines, size, line_h = chosen["lines"], chosen["size"], chosen["line_h"]
    card = chosen["card"]

    # A brand-colour card behind the words only; the photo stays untouched.
    primary = hex_rgb(brand["colors"]["primary"])
    accent = hex_rgb(brand["colors"]["accent"])
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(card, radius=int(short * 0.014), fill=240)
    frame = Image.composite(Image.new("RGB", (W, H), primary), frame, mask)
    plate = frame.copy()  # what sits behind the text, for the legibility check

    d = ImageDraw.Draw(frame)
    d.rectangle([x, y, x + bar_w, y + bar_h], fill=accent)
    f = font(lang, size)
    # Pillow draws from the line's ascent; nudge so the cap height sits on the grid.
    ty = y + bar_h + chosen["gap"] - int(size * 0.08)
    right = x
    for i, line in enumerate(lines):
        d.text((x, ty + i * line_h), line, font=f, fill=(255, 255, 255))
        right = max(right, x + int(d.textlength(line, font=f)))
    text_box = (x, ty, right, ty + line_h * (len(lines) - 1) + size)

    logo_box = None
    if logo_src:
        ly = card[3] - pad - logo_src.height
        frame.paste(logo_src, (x, ly), logo_src)
        logo_box = (x, ly, x + logo_src.width, ly + logo_src.height)

    return {
        "image": frame,
        "plate": plate,
        "text_box": text_box,
        "card_box": card,
        "logo_box": logo_box,
        "product_box": zone,
        "product_visible": visible,
        "text_on_product": _overlap(card, zone) / max(1, (card[2] - card[0]) * (card[3] - card[1])),
        "focal_px": (fpx, fpy),
        "font_size": size,
        "min_font_size": min_size,
        "shrunk": size < base_size * 0.85,
        "too_long": len(lines) > 3,
        "lines": len(lines),
        "source_scale": source_scale,
        "side": side,
        "crop_box": box,
    }
