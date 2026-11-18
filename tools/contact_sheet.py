"""Dev helper: one image showing every frame of a campaign's outputs."""
import sys
from pathlib import Path
from PIL import Image

out = Path(sys.argv[1])
dest = Path(sys.argv[2])
H = 420
rows = []
for prod in sorted(p for p in out.iterdir() if p.is_dir()):
    ims = [Image.open(f) for r in ("1x1", "9x16", "16x9") for f in sorted((prod / r).glob("*.png"))]
    rows.append([i.resize((int(i.width * H / i.height), H)) for i in ims])
W = max(sum(i.width + 12 for i in r) for r in rows)
sheet = Image.new("RGB", (W, len(rows) * (H + 12)), "white")
for ri, r in enumerate(rows):
    x = 0
    for i in r:
        sheet.paste(i, (x, ri * (H + 12)))
        x += i.width + 12
sheet.save(dest, quality=82)
