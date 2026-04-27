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
PADDING = 128      # canvas padding before bar group

# Bar geometry: 4 ascending signal bars. Faithful to the existing
# favicon — sharp rectangles (no corner rounding), narrow bars with
# wide gaps, saturated colours. Every phone OS shows 4 bars going red
# (no signal) → green (full signal); 5 bars + blue middle reads as
# "chart", 4 raw reads as "signal".
BAR_HEIGHTS = [0.30, 0.55, 0.80, 1.00]
BAR_COLORS = [
    (220, 38, 38),    # red-600     — weak signal
    (249, 115, 22),   # orange-500
    (250, 204, 21),   # yellow-400
    (22, 163, 74),    # green-600   — strong signal
]
BAR_RADIUS = 0        # raw rectangles, matching favicon
BAR_GAP_RATIO = 0.55  # bar:gap = 1:0.55 (slim, technical)

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
    bar_w = usable / (n_bars + (n_bars - 1) * BAR_GAP_RATIO)
    gap = bar_w * BAR_GAP_RATIO
    bottom = SIZE - PADDING

    for i, (h_frac, color) in enumerate(zip(BAR_HEIGHTS, BAR_COLORS)):
        x0 = PADDING + i * (bar_w + gap)
        x1 = x0 + bar_w
        bar_h = usable * h_frac
        y1 = bottom
        y0 = y1 - bar_h
        if BAR_RADIUS > 0:
            draw.rounded_rectangle((x0, y0, x1, y1), radius=BAR_RADIUS, fill=color)
        else:
            draw.rectangle((x0, y0, x1, y1), fill=color)
    return img


def main() -> None:
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    img = make_icon(transparent_bg=False)
    img.save(OUT_PATH, format="PNG", optimize=True)
    print(f"wrote {OUT_PATH} ({SIZE}x{SIZE}, {os.path.getsize(OUT_PATH)} bytes)")


if __name__ == "__main__":
    main()
