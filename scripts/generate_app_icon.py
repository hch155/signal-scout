"""Generate the 1024x1024 Signal-Scout app icon.

Used for:
- Facebook app review (mandatory App icon 1024x1024 field)
- Open Graph fallback (og:image)
- Future: high-res favicon variants

Design: 5 ascending bars in a signal-strength visualization, brand
colors red → orange → yellow → blue → green, on a white rounded-rect
"app tile" background. No external assets, no fonts, no network.

Run:  python scripts/generate_app_icon.py
Out:  src/static/images/app-icon-1024.png
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_PATH = os.path.join(ROOT, "src", "static", "images", "app-icon-1024.png")

SIZE = 1024
TILE_RADIUS = 192  # ~iOS app tile rounding at 1024
PADDING = 96       # canvas padding before bar group

# Bar geometry: 5 bars, ascending. Heights are fractions of usable canvas.
# Gaps are 30% of bar width to keep the silhouette readable.
BAR_HEIGHTS = [0.34, 0.50, 0.66, 0.82, 1.00]
BAR_COLORS = [
    (239, 68, 68),    # red-500
    (249, 115, 22),   # orange-500
    (234, 179, 8),    # yellow-500
    (59, 130, 246),   # blue-500
    (34, 197, 94),    # green-500
]
BAR_RADIUS = 40       # corner rounding on each bar

BG_TILE = (255, 255, 255, 255)
BG_TRANSPARENT = (0, 0, 0, 0)


def make_icon(transparent_bg: bool = False) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), BG_TRANSPARENT)
    draw = ImageDraw.Draw(img)

    if not transparent_bg:
        # Rounded-rect "app tile" background.
        draw.rounded_rectangle(
            (0, 0, SIZE, SIZE),
            radius=TILE_RADIUS,
            fill=BG_TILE,
        )

    usable = SIZE - 2 * PADDING
    n_bars = len(BAR_HEIGHTS)
    # Gaps take 30% of each bar's width — bar:gap = 1:0.3 ratio.
    bar_w = usable / (n_bars + (n_bars - 1) * 0.3)
    gap = bar_w * 0.3
    bottom = SIZE - PADDING

    for i, (h_frac, color) in enumerate(zip(BAR_HEIGHTS, BAR_COLORS)):
        x0 = PADDING + i * (bar_w + gap)
        x1 = x0 + bar_w
        bar_h = usable * h_frac
        y1 = bottom
        y0 = y1 - bar_h
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=BAR_RADIUS,
            fill=color,
        )
    return img


def main() -> None:
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    img = make_icon(transparent_bg=False)
    img.save(OUT_PATH, format="PNG", optimize=True)
    print(f"wrote {OUT_PATH} ({SIZE}x{SIZE}, {os.path.getsize(OUT_PATH)} bytes)")


if __name__ == "__main__":
    main()
