"""The GUI's small drawings — logo tile, icons, output previews — as images.

Tk's Canvas draws without antialiasing on Windows, which leaves curves and
circles visibly stepped next to CustomTkinter's smooth widgets. So everything
here is drawn with Pillow at SUPERSAMPLE times the size it's shown at, then
reduced, the same trick tools/make_icons.py uses for the app icon.

Each function takes a size in logical pixels and returns an RGBA image
several times larger; CTkImage scales it down to the display's DPI.
"""

from PIL import Image, ImageDraw

# Returned images are this many times their logical size, so they stay sharp
# at 300% display scaling without CTkImage having to scale anything up.
RES = 3

# Drawn larger again, then reduced — the reduction is the antialiasing.
SUPERSAMPLE = 4

# The mark, on the same 32x32 grid as assets/logo.svg. Keep in step with it
# (and with tools/make_icons.py) if the artwork changes.
_GRID = 32
_AXIS_PTS = [(6, 4.5), (6, 26), (27.5, 26)]
_AXIS_WIDTH = 2.4
_CURVE_PTS = [(9.5, 21.2), (14.8, 16.2), (19.2, 18.4), (25, 9.2)]
_CURVE_WIDTH = 2.6

# The tile is white in both themes, so the mark wears its light-theme colours.
TILE = "#ffffff"
TILE_BORDER = "#e5e5ea"
MARK_AXIS = "#c7c7cc"
MARK_CURVE = "#08865a"


def _canvas(w, h):
    """A transparent supersampled canvas and the factor from logical pixels."""
    k = RES * SUPERSAMPLE
    img = Image.new("RGBA", (round(w * k), round(h * k)), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), k


def _finish(img, w, h):
    return img.resize((round(w * RES), round(h * RES)), Image.LANCZOS)


def _stroke(draw, points, width, colour):
    """Polyline with round caps and joins, which ImageDraw has no option for."""
    draw.line(points, fill=colour, width=max(1, round(width)))
    r = width / 2
    for x, y in points:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)


def _dashed_v(draw, x, y0, y1, dash, gap, width, colour):
    y = y0
    while y < y1:
        draw.line([(x, y), (x, min(y + dash, y1))], fill=colour, width=max(1, round(width)))
        y += dash + gap


def dim(img, factor):
    """The image with its colours pulled toward black, alpha untouched.

    Used for the form behind the progress panel, which is dimmed by recolouring
    rather than by an overlay — Tk has no translucent widgets.
    """
    r, g, b, a = img.split()
    r, g, b = (ch.point(lambda v: int(v * factor)) for ch in (r, g, b))
    return Image.merge("RGBA", (r, g, b, a))


def mark_tile(size, border=True):
    """The logo mark centred in a white rounded-square tile."""
    img, d, k = _canvas(size, size)
    s = size * k
    radius = s * 0.24
    if border:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius, fill=TILE_BORDER)
        inset = max(1.0, k * 1.0)
        d.rounded_rectangle((inset, inset, s - 1 - inset, s - 1 - inset), radius - inset, fill=TILE)
    else:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius, fill=TILE)
    # The mark fills ~70% of the tile, optically centred on its bounding box.
    m = s * 0.70 / _GRID
    ox = (s - _GRID * m) / 2 - 0.25 * m
    oy = (s - _GRID * m) / 2 - 0.75 * m

    def pts(points):
        return [(ox + x * m, oy + y * m) for x, y in points]

    _stroke(d, pts(_AXIS_PTS), _AXIS_WIDTH * m, MARK_AXIS)
    _stroke(d, pts(_CURVE_PTS), _CURVE_WIDTH * m, MARK_CURVE)
    return _finish(img, size, size)


def folder_icon(size, colour):
    """An outline folder, drawn inside the repository path field."""
    img, d, k = _canvas(size, size)
    s = size * k
    w = s * 0.085
    top, bottom = s * 0.22, s * 0.82
    left, right = s * 0.08, s * 0.92
    tab_r = s * 0.40
    d.rounded_rectangle((left, top + s * 0.10, right, bottom), s * 0.10, outline=colour, width=round(w))
    _stroke(d, [(left + w / 2, top + s * 0.14), (left + w / 2, top + s * 0.02),
                (tab_r - s * 0.04, top + s * 0.02), (tab_r + s * 0.06, top + s * 0.12)], w, colour)
    return _finish(img, size, size)


def check_circle(size, selected, accent, ring, on_accent="#ffffff"):
    """The tick badge on an output tile: filled when on, an empty ring when off."""
    img, d, k = _canvas(size, size)
    s = size * k
    if selected:
        d.ellipse((0, 0, s - 1, s - 1), fill=accent)
        _stroke(d, [(s * 0.29, s * 0.52), (s * 0.44, s * 0.66), (s * 0.72, s * 0.36)], s * 0.1, on_accent)
    else:
        w = max(1.0, k * 1.5)
        d.ellipse((0, 0, s - 1, s - 1), fill=ring)
        d.ellipse((w, w, s - 1 - w, s - 1 - w), fill=(0, 0, 0, 0))
    return _finish(img, size, size)


def tick_badge(size, accent, on_accent):
    """The "done" tick at the start of the footer."""
    return check_circle(size, True, accent, accent, on_accent)


def dashboard_preview(w, h, dark, blue, orange, purple):
    """A thumbnail of the static dashboard: hero chart over a row of cards."""
    img, d, k = _canvas(w, h)
    W, H = w * k, h * k
    page = "#000000" if dark else "#f5f5f7"
    card = "#1c1c1e" if dark else "#ffffff"
    ink = "#f5f5f7" if dark else "#1d1d1f"
    faint = "#3a3a3c" if dark else "#d2d2d7"
    d.rounded_rectangle((0, 0, W - 1, H - 1), 6 * k, fill=page)
    # Title stroke and a short sub-line, standing in for the hero.
    d.rounded_rectangle((6 * k, 6 * k, 30 * k, 9.5 * k), 1.75 * k, fill=ink)
    d.rounded_rectangle((6 * k, 12 * k, 20 * k, 14 * k), k, fill=faint)
    # The big lines-of-code card.
    cx0, cy0, cx1, cy1 = 6 * k, 18 * k, W - 6 * k, H * 0.66
    d.rounded_rectangle((cx0, cy0, cx1, cy1), 3 * k, fill=card)
    pts = []
    for i, v in enumerate((0.10, 0.18, 0.22, 0.38, 0.45, 0.62, 0.70, 0.86)):
        pts.append((cx0 + 4 * k + (cx1 - cx0 - 8 * k) * i / 7, cy1 - 3 * k - (cy1 - cy0 - 7 * k) * v))
    area = pts + [(pts[-1][0], cy1 - 2 * k), (pts[0][0], cy1 - 2 * k)]
    d.polygon(area, fill=blue + "33")
    _stroke(d, pts, 1.3 * k, blue)
    # Two small chart cards underneath.
    gap = 4 * k
    bw = (W - 12 * k - gap) / 2
    by0, by1 = H * 0.66 + 4 * k, H - 6 * k
    for n, colour in enumerate((orange, purple)):
        x0 = 6 * k + n * (bw + gap)
        d.rounded_rectangle((x0, by0, x0 + bw, by1), 3 * k, fill=card)
        heights = (0.5, 0.8, 0.6, 0.95, 0.4) if n == 0 else (0.3, 0.55, 0.75, 0.9, 1.0)
        slot = (bw - 6 * k) / len(heights)
        for i, v in enumerate(heights):
            bx = x0 + 3 * k + i * slot + slot * 0.2
            top = by1 - 2.5 * k - (by1 - by0 - 5 * k) * v
            d.rounded_rectangle((bx, top, bx + slot * 0.6, by1 - 2.5 * k), slot * 0.3, fill=colour)
    return _finish(img, w, h)


def story_preview(w, h, blue):
    """A thumbnail of the story: a line drawing in, with its playhead."""
    img, d, k = _canvas(w, h)
    W, H = w * k, h * k
    d.rounded_rectangle((0, 0, W - 1, H - 1), 6 * k, fill="#000000")
    d.rounded_rectangle((6 * k, 6 * k, 18 * k, 8 * k), k, fill=blue)
    d.rounded_rectangle((6 * k, 11 * k, 34 * k, 15 * k), 2 * k, fill="#f5f5f7")
    d.rounded_rectangle((6 * k, 18 * k, 26 * k, 20 * k), k, fill="#3a3a3c")
    # Grid, then the line up to the playhead.
    x0, x1, y0, y1 = 6 * k, W - 6 * k, H * 0.42, H - 6 * k
    for f in (0.0, 0.5, 1.0):
        y = y0 + (y1 - y0) * f
        d.line([(x0, y), (x1, y)], fill="#1c1c1e", width=max(1, round(0.6 * k)))
    values = (0.05, 0.14, 0.20, 0.34, 0.42, 0.58, 0.66)
    pts = [(x0 + (x1 - x0) * 0.80 * i / (len(values) - 1), y1 - (y1 - y0) * v) for i, v in enumerate(values)]
    area = pts + [(pts[-1][0], y1), (pts[0][0], y1)]
    d.polygon(area, fill=blue + "38")
    _stroke(d, pts, 1.3 * k, blue)
    hx, hy = pts[-1]
    _dashed_v(d, hx, hy, y1, 2 * k, 1.6 * k, 0.6 * k, "#8e8e93")
    for r, alpha in ((4.2, "30"), (3.0, "60")):
        d.ellipse((hx - r * k, hy - r * k, hx + r * k, hy + r * k), fill=blue + alpha)
    d.ellipse((hx - 1.9 * k, hy - 1.9 * k, hx + 1.9 * k, hy + 1.9 * k), fill=blue)
    return _finish(img, w, h)
