"""Draw simple placeholder storyboard frames for the example project and tests.

  python tools/make_placeholder_boards.py OUTDIR [--count 8]

Writes board_01.png ... as 1280x536 (2.39:1) sketches: a horizon, a couple of figures and a
big panel number, so it's obvious in Kitsu or Blender which board is which.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PALETTE = [(42, 46, 56), (56, 48, 44), (40, 54, 50), (52, 44, 58)]


def board(n: int, size=(1280, 536)) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, PALETTE[n % len(PALETTE)])
    draw = ImageDraw.Draw(img)
    horizon = int(h * (0.55 + 0.1 * ((n % 3) - 1)))
    draw.rectangle([0, horizon, w, h], fill=tuple(c + 18 for c in PALETTE[n % len(PALETTE)]))
    for i in range(1 + n % 3):
        cx = int(w * (0.3 + 0.22 * i))
        tall = int(h * (0.35 + 0.08 * ((n + i) % 3)))
        head = tall // 6
        draw.ellipse([cx - head, horizon - tall, cx + head, horizon - tall + 2 * head], outline=(230, 230, 230), width=4)
        draw.rounded_rectangle([cx - head, horizon - tall + 2 * head + 6, cx + head, horizon], radius=head // 2, outline=(230, 230, 230), width=4)
    draw.rectangle([0, 0, w - 1, h - 1], outline=(160, 160, 170), width=6)
    try:
        font = ImageFont.load_default(size=96)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    draw.text((40, 30), f"{n:02d}", fill=(240, 200, 90), font=font)
    return img


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for n in range(1, args.count + 1):
        board(n).save(out / f"board_{n:02d}.png", optimize=True)
    print(f"wrote {args.count} boards to {out}")


if __name__ == "__main__":
    main()
