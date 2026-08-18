"""Render the Repo Growth mark to the icon files the app and installers use.

    python tools/make_icons.py

Writes assets/logo.ico (the Windows window/taskbar/exe icon, multi-size) and
assets/logo.png (256px, used for the window icon everywhere else). Both are
committed — this script only needs running when the mark changes.

assets/logo.svg stays the source of truth for the artwork. Nothing here can
read SVG without pulling a renderer into the project, so the mark is redrawn
from the same coordinates, exactly as gui.py redraws it on a Canvas. Keep the
three in step if the mark ever changes.

Needs Pillow (in requirements-dev.txt); it is not a runtime dependency.
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

AXIS_COLOUR  = "#2a3242"
MARK_COLOUR  = "#00e5a0"

# The 32x32 grid of assets/logo.svg.
GRID = 32
AXIS_PTS    = [(6, 4.5), (6, 26), (27.5, 26)]
AXIS_WIDTH  = 2.4
CURVE_PTS   = [(9.5, 21.2), (14.8, 16.2), (19.2, 18.4), (25, 9.2)]
CURVE_WIDTH = 3
NODE_RADII  = [2, 2, 2, 3.4]

# Every size Windows picks from: Explorer and the taskbar want the small end,
# the alt-tab switcher and large icon views the big end.
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

# Drawn this many times larger, then reduced. Pillow has no antialiasing of
# its own, so the downsample is what gives the curve clean edges.
SUPERSAMPLE = 8


def _round_stroke(draw, points, width, colour, scale):
    """Polyline with round caps and joins, which ImageDraw has no option for.

    Discs of the stroke's own radius at every vertex round both the ends and
    the corners, matching the SVG's stroke-linecap/linejoin="round".
    """
    pts = [(x * scale, y * scale) for x, y in points]
    w = width * scale
    draw.line(pts, fill=colour, width=int(round(w)))
    r = w / 2
    for x, y in pts:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)


def render(size):
    """The mark as an RGBA image `size` pixels square, on transparency."""
    scale = size * SUPERSAMPLE / GRID
    big = Image.new("RGBA", (size * SUPERSAMPLE,) * 2, (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)

    _round_stroke(draw, AXIS_PTS, AXIS_WIDTH, AXIS_COLOUR, scale)
    _round_stroke(draw, CURVE_PTS, CURVE_WIDTH, MARK_COLOUR, scale)
    for (x, y), r in zip(CURVE_PTS, NODE_RADII):
        draw.ellipse(
            ((x - r) * scale, (y - r) * scale, (x + r) * scale, (y + r) * scale),
            fill=MARK_COLOUR,
        )

    return big.resize((size, size), Image.LANCZOS)


def main():
    images = [render(s) for s in ICO_SIZES]
    ico_path = os.path.join(ASSETS, "logo.ico")
    images[-1].save(
        ico_path, format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=images[:-1],
    )

    png_path = os.path.join(ASSETS, "logo.png")
    images[-1].save(png_path, format="PNG")

    for path in (ico_path, png_path):
        print(f"wrote {os.path.relpath(path, ROOT)}  ({os.path.getsize(path):,} bytes)")


if __name__ == "__main__":
    main()
