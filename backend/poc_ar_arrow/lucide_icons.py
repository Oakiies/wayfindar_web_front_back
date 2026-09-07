"""Render Lucide icons into a PIL image.

The frontend (`frontend-v3`) already draws its turn cues with lucide-react, so
using the same icon set here means the AR overlay and the app show literally the
same glyphs instead of two hand-drawn approximations.

Path data is copied from lucide-react v0.563.0 (ISC licensed) rather than read
out of `frontend-v3/node_modules`, so the backend does not depend on the
frontend being installed.

Lucide icons are stroke-based on a 24x24 grid with stroke-width 2 and round
caps/joins - which is why they can be reproduced faithfully by sampling the
paths and stroking the resulting polylines.
"""
import math

from svg.path import Arc, CubicBezier, Close, Line, Move, QuadraticBezier, parse_path

VIEWBOX = 24.0
DESIGN_STROKE = 2.0

# name -> list of primitives. ('path', d) | ('circle', cx, cy, r)
ICONS = {
    # x
    'close': [
        ('path', 'M18 6 6 18'),
        ('path', 'm6 6 12 12'),
    ],
    # camera-off
    'camera-off': [
        ('path', 'M14.564 14.558a3 3 0 1 1-4.122-4.121'),
        ('path', 'm2 2 20 20'),
        ('path', 'M20 20H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 .819-.175'),
        ('path', 'M9.695 4.024A2 2 0 0 1 10.004 4h3.993a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v7.344'),
    ],
    # map
    'map': [
        ('path', 'M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z'),
        ('path', 'M15 5.764v15'),
        ('path', 'M9 3.236v15'),
    ],
    # arrow-up
    'straight': [
        ('path', 'm5 12 7-7 7 7'),
        ('path', 'M12 19V5'),
    ],
    # corner-up-right
    'right': [
        ('path', 'm15 14 5-5-5-5'),
        ('path', 'M4 20v-7a4 4 0 0 1 4-4h12'),
    ],
    # corner-up-left
    'left': [
        ('path', 'M20 20v-7a4 4 0 0 0-4-4H4'),
        ('path', 'M9 14 4 9l5-5'),
    ],
    # circle-check
    'arrived': [
        ('circle', 12.0, 12.0, 10.0),
        ('path', 'm9 12 2 2 4-4'),
    ],
    # rotate-ccw, for a u-turn
    'uturn': [
        ('path', 'M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8'),
        ('path', 'M3 3v5h5'),
    ],
}

_CURVE_SAMPLES = 14


def _subpaths(d):
    """Sample one `d` string into polylines, one per subpath.

    Segments are walked individually rather than sampling the whole path
    uniformly: that keeps sharp corners exactly where the designer put them,
    and only spends samples on the curved segments.
    """
    polylines = []
    current = []

    for seg in parse_path(d):
        if isinstance(seg, Move):
            if len(current) > 1:
                polylines.append(current)
            current = [(seg.end.real, seg.end.imag)]
            continue
        if isinstance(seg, Close):
            if current:
                current.append(current[0])
            continue

        if isinstance(seg, Line):
            points = [seg.end]
        elif isinstance(seg, (Arc, CubicBezier, QuadraticBezier)):
            points = [seg.point((i + 1) / _CURVE_SAMPLES)
                      for i in range(_CURVE_SAMPLES)]
        else:
            points = [seg.end]

        if not current:
            current = [(seg.start.real, seg.start.imag)]
        current.extend((p.real, p.imag) for p in points)

    if len(current) > 1:
        polylines.append(current)
    return polylines


def stroke_polyline(draw, points, color, width):
    """Polyline with round joints and caps.

    PIL has no round line caps; without discs at the ends a thin glyph shows
    square nibs, which is exactly what Lucide's `stroke-linecap="round"` avoids.
    """
    if len(points) < 2:
        return
    draw.line(points, fill=color, width=width, joint='curve')
    r = width / 2.0
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def draw_icon(draw, name, cx, cy, size, color, width=None):
    """Draw `name` centred on (cx, cy), scaled to fit a `size` x `size` box.

    `width` defaults to Lucide's own 2/24 stroke ratio, so the icon keeps the
    weight it was designed with.
    """
    primitives = ICONS[name]
    scale = size / VIEWBOX
    if width is None:
        width = max(2, int(round(DESIGN_STROKE * scale)))

    def to_canvas(x, y):
        return (cx + (x - VIEWBOX / 2.0) * scale, cy + (y - VIEWBOX / 2.0) * scale)

    for prim in primitives:
        if prim[0] == 'circle':
            _, ox, oy, r = prim
            ex, ey = to_canvas(ox, oy)
            rr = r * scale
            draw.ellipse((ex - rr, ey - rr, ex + rr, ey + rr),
                         outline=color, width=width)
            continue

        for polyline in _subpaths(prim[1]):
            stroke_polyline(draw, [to_canvas(x, y) for x, y in polyline],
                            color, width)


def icon_bounds(name):
    """Tight bounds of the icon in viewBox units, as (x0, y0, x1, y1)."""
    xs, ys = [], []
    for prim in ICONS[name]:
        if prim[0] == 'circle':
            _, ox, oy, r = prim
            xs += [ox - r, ox + r]
            ys += [oy - r, oy + r]
            continue
        for polyline in _subpaths(prim[1]):
            xs += [p[0] for p in polyline]
            ys += [p[1] for p in polyline]
    return min(xs), min(ys), max(xs), max(ys)


if __name__ == '__main__':
    for key in ICONS:
        x0, y0, x1, y1 = icon_bounds(key)
        print(f'{key:9s} bounds ({x0:5.1f}, {y0:5.1f}) - ({x1:5.1f}, {y1:5.1f})')
