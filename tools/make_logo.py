"""Draws the fictional Solvane logo used by the sample campaign.

Run once; the PNG is committed. Kept so the asset is reproducible.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
NAVY, CORAL = (20, 33, 61, 255), (255, 107, 74, 255)
S = 4  # supersample

f = ImageFont.truetype(str(ROOT / "studio/fonts/Inter.ttf"), 200 * S)
f.set_variation_by_name("SemiBold")
probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
word = "solvane"
l, t, r, b = probe.textbbox((0, 0), word, font=f)
mark = 150 * S
gap = 36 * S
W = mark + gap + (r - l) + 20 * S
H = max(b - t, mark) + 40 * S
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
cy = H // 2 + 10 * S
# Sun on a horizon: a disc cut by a line, three short rays.
d.pieslice([0, cy - mark // 2, mark, cy + mark // 2], 180, 360, fill=CORAL)
d.rectangle([0, cy + 6 * S, mark, cy + 18 * S], fill=CORAL)
d.text((mark + gap - l, (H - (b - t)) // 2 - t + 6 * S), word, font=f, fill=NAVY)
img = img.resize((W // S, H // S), Image.LANCZOS)
bbox = img.getbbox()
img = img.crop(bbox)
out = ROOT / "samples/long-light/assets/logo.png"
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out)
print(out, img.size)
