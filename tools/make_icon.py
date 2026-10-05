"""Generate assets/icons/app.ico (original artwork, no third-party branding).

A rounded square with a simple ball-of-yarn motif.
Run: python tools/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "icons"
BLUE = (47, 111, 235, 255)
WHITE = (255, 255, 255, 255)


def draw(size: int = 1024) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0.04 * s, 0.04 * s, 0.96 * s, 0.96 * s], radius=0.2 * s, fill=BLUE)

    cx, cy, r = 0.47 * s, 0.46 * s, 0.30 * s
    # tail of yarn leaving the ball (drawn first, ball covers its start)
    import math
    w_tail = int(0.032 * s)
    pts = []
    for i in range(61):
        t = i / 60
        x = cx + 0.12 * s + t * 0.30 * s
        y = cy + 0.24 * s + t * 0.16 * s + math.sin(t * math.pi * 1.6) * 0.05 * s
        pts.append((x, y))
    d.line(pts, fill=WHITE, width=w_tail, joint="curve")
    end = pts[-1]
    d.ellipse([end[0] - w_tail / 2, end[1] - w_tail / 2, end[0] + w_tail / 2,
               end[1] + w_tail / 2], fill=WHITE)

    ball = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bd = ImageDraw.Draw(ball)
    bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    lines = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines)
    w = int(0.026 * s)
    for k in range(-3, 4):  # wraps in one direction
        off = k * 0.085 * s
        ld.ellipse([cx - 1.6 * r + off, cy - 2.2 * r - off, cx + 1.6 * r + off, cy + 0.9 * r - off],
                   outline=BLUE, width=w)
    for k in range(0, 3):   # a few crossing wraps
        off = k * 0.09 * s
        ld.arc([cx - r - off, cy - 0.35 * r, cx + r + off, cy + 1.9 * r], start=190, end=350,
               fill=BLUE, width=w)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([cx - r + w, cy - r + w, cx + r - w, cy + r - w], fill=255)
    lines.putalpha(ImageChops.multiply(lines.getchannel("A"), mask))
    ball.alpha_composite(lines)
    img.alpha_composite(ball)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw(1024)
    big.resize((256, 256), Image.LANCZOS).save(OUT / "app.png")
    big.save(OUT / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                     (128, 128), (256, 256)])
    print("Wrote", OUT / "app.ico")


if __name__ == "__main__":
    main()
