# -*- coding: utf-8 -*-
"""Render the map symbols onto the real floor plan, as flat PNG contact sheets.

Two sheets:

    pose-variants.png   six candidate pose symbols, one route colour
    colour-schemes.png  the chosen symbol (radar sector) in eleven palettes,
                        each shown with the destination pin and origin ring so
                        the whole cast is judged together

`public/map-symbols.html` is the interactive version of the same thing; this
script exists so the options can be looked at without a dev server.

Screen pixels here are real pixels, so the constants below are the constants
MapCanvas uses.

    python design/render_pose_variants.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FLOOR_PLAN = ROOT / 'public' / 'system_data' / 'map' / 'floor1.jpg'
OUT_VARIANTS = HERE / 'pose-variants.png'
OUT_COLOURS = HERE / 'colour-schemes.png'
OUT_RING = HERE / 'dot-ring.png'
OUT_ROUTE = HERE / 'route-casing.png'
OUT_DOTS = HERE / 'route-dots.png'

MAP_SIZE = 500

ACCENT = (13, 110, 253)
DEST = (229, 72, 77)         # destination pin, fixed
ORIGIN_INK = (15, 23, 42)    # origin ring, fixed
WHITE = (255, 255, 255)
INK = (17, 19, 21)
INK_2 = (85, 89, 95)
INK_3 = (138, 143, 150)
PAPER = (242, 241, 238)
LINE = (228, 226, 221)

# Real shortest path on floor 1: Auditorium -> M21_B.
ROUTE = [
    (140, 146), (207, 146), (241, 146), (250, 146), (313, 146), (313, 215),
    (313, 253), (338, 312), (338, 333), (338, 351), (338, 378.85), (338, 391),
    (338, 408), (338, 433.43), (338, 446), (338, 466),
]

SS = 3                       # supersample: PIL does no anti-aliasing of its own
HEADING_DEG = 90
PROGRESS = 0.38

DOT_R = 7                    # accent disc, screen px
DOT_RING = 0.42              # white ring as a fraction of the disc
ROUTE_W = 4
ROUTE_CASING_W = 7.4
DOT_TRAIL_R = 4          # the trail dot that shipped before the line
DOT_TRAIL_CASING = 6.2
DOT_TRAIL_SPACING = 17


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def point_at_fraction(points, fraction):
    total = sum(math.dist(points[i - 1], points[i]) for i in range(1, len(points)))
    target = total * fraction
    walked = 0.0
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        length = math.dist(a, b)
        if walked + length >= target:
            t = 0 if length == 0 else (target - walked) / length
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        walked += length
    return points[-1]


def sample_along_path(points, spacing):
    """A point every `spacing` units of arc length, not every vertex."""
    if len(points) < 2 or spacing <= 0:
        return []
    out = [points[0]]
    carried = 0.0
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        length = math.dist(a, b)
        if length == 0:
            continue
        travelled = spacing - carried
        while travelled <= length:
            t = travelled / length
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            travelled += spacing
        carried = (carried + length) % spacing
    return out


def polar(cx, cy, r, rad):
    return (cx + math.cos(rad) * r, cy + math.sin(rad) * r)


def fan_points(cx, cy, rad, spread_deg, r, steps=48):
    """A pie sector as a polygon: apex, then the arc sampled evenly."""
    spread = math.radians(spread_deg)
    return [(cx, cy)] + [
        polar(cx, cy, r, rad - spread + 2 * spread * i / steps) for i in range(steps + 1)
    ]


def pin_points(x, y, r, steps=48):
    """MapCanvas's pin: a circle closed by the two lines tangent to it.

    The head sits `r * 2.4` above the tip; the tangents make the taper meet the
    circle smoothly instead of bulging out of it.
    """
    dist = r * 2.4
    cos_phi = r / dist
    sin_phi = math.sqrt(max(0.0, 1 - cos_phi * cos_phi))
    tx, ty = r * sin_phi, -dist + r * cos_phi

    cx, cy = x, y - dist
    a1 = math.atan2(ty + dist, tx)          # right tangent point, seen from the head
    a2 = -math.pi - a1                      # left one, going over the top
    arc = [polar(cx, cy, r, a1 + (a2 - a1) * i / steps) for i in range(steps + 1)]
    return [(x, y), (x + tx, y + ty)] + arc + [(x - tx, y + ty)]


def flat_fill(img, points, colour, opacity):
    """One flat alpha, composited. No gradient anywhere in this file."""
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).polygon(points, fill=colour + (int(255 * opacity),))
    return Image.alpha_composite(img, layer)


# --------------------------------------------------------------------------
# symbols
# --------------------------------------------------------------------------
def draw_dot(draw, x, y, u, colour=ACCENT, ring=True):
    """The disc, with or without its white casing.

    The casing is what carries the symbol over a dark ground - but the pose is
    always ON the route, and the route runs down corridors, where the bare disc
    already scores 3.81 against #ececec. Inside a turquoise room it would drop
    to 1.80, and the walker is never in one.
    """
    r = DOT_R * u
    if ring:
        pad = DOT_R * DOT_RING * u
        draw.ellipse([x - r - pad, y - r - pad, x + r + pad, y + r + pad], fill=WHITE)
    draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)


def draw_origin(draw, x, y, u):
    r, casing = 8 * u, 2.4 * u
    draw.ellipse([x - r - casing, y - r - casing, x + r + casing, y + r + casing], fill=WHITE)
    draw.ellipse([x - r, y - r, x + r, y + r], outline=ORIGIN_INK, width=max(1, int(r * 0.34)))


def draw_dest(draw, x, y, u):
    r = 12 * u
    draw.polygon(pin_points(x, y, r), fill=DEST, outline=WHITE, width=max(1, int(r * 0.16)))
    hole, top = r * 0.3, y - r * 2.4
    draw.ellipse([x - hole, top - hole, x + hole, top + hole], fill=WHITE)


def sector(img, x, y, rad, spread, radius, u, fill_op, edge_op, colour):
    pts = fan_points(x, y, rad, spread, radius * u)
    img = flat_fill(img, pts, colour, fill_op)
    if edge_op:
        ImageDraw.Draw(img, 'RGBA').line(
            pts[1:] + [pts[0], pts[1]], fill=colour + (int(255 * edge_op),),
            width=max(1, int(1.4 * u)), joint='curve')
    return img


def v_sector(img, x, y, rad, u, colour=ACCENT):
    return sector(img, x, y, rad, 32, 30, u, 0.32, 0.62, colour)


def v_beam(img, x, y, rad, u, colour=ACCENT):
    return sector(img, x, y, rad, 16, 46, u, 0.28, 0.70, colour)


def v_sweep(img, x, y, rad, u, colour=ACCENT):
    img = sector(img, x, y, rad, 34, 34, u, 0.20, 0, colour)
    d = ImageDraw.Draw(img, 'RGBA')
    for radius, width, op in ((20, 1.3, 0.5), (34, 1.6, 0.75)):
        arc = [polar(x, y, radius * u, rad + math.radians(-34 + 68 * i / 40)) for i in range(41)]
        d.line(arc, fill=colour + (int(255 * op),), width=max(1, int(width * u)), joint='curve')
    return img


def v_chevron(img, x, y, rad, u, colour=ACCENT):
    tip = polar(x, y, DOT_R * 2.9 * u, rad)
    base = polar(x, y, DOT_R * 1.5 * u, rad)
    left = polar(x, y, DOT_R * 1.62 * u, rad - 0.62)
    right = polar(x, y, DOT_R * 1.62 * u, rad + 0.62)
    ImageDraw.Draw(img, 'RGBA').polygon(
        [tip, left, base, right], fill=colour + (255,),
        outline=WHITE + (255,), width=max(1, int(1.6 * u)))
    return img


def v_torch(img, x, y, rad, u, colour=ACCENT):
    return sector(img, x, y, rad, 62, 22, u, 0.30, 0.55, colour)


def v_needle(img, x, y, rad, u, colour=ACCENT):
    tip = polar(x, y, 34 * u, rad)
    left = polar(x, y, DOT_R * 1.1 * u, rad - math.pi / 2)
    right = polar(x, y, DOT_R * 1.1 * u, rad + math.pi / 2)
    ImageDraw.Draw(img, 'RGBA').polygon(
        [tip, left, right], fill=colour + (255,),
        outline=WHITE + (255,), width=max(1, int(1.5 * u)))
    return img


VARIANTS = [
    ('01', 'Radar sector', 'ใบพัดเรดาร์ ±32°', v_sector),
    ('02', 'Long beam', 'ลำแคบยาว ±16°', v_beam),
    ('03', 'Radar + rings', 'ใบพัด + วงระยะ', v_sweep),
    ('04', 'Chevron on ring', 'ลูกศรเกาะขอบวง', v_chevron),
    ('05', 'Wide torch', 'ลำกว้างสั้น ±62°', v_torch),
    ('06', 'Compass needle', 'เข็มทิศ', v_needle),
]


# --------------------------------------------------------------------------
# colour schemes
#
# Judged against what this floor plan actually is: 60% light grey #ececec, 12%
# turquoise rooms (#a5d8d9 / #6dc8c9), black wall lines. The figure in each
# caption is WCAG contrast against the darker turquoise - the hardest ground on
# the plan. #0d6efd scores 1.80 there, which is why today's route survives on
# its white casing rather than on its colour.
# --------------------------------------------------------------------------
SCHEMES = [
    ('A', 'One accent', 'ฟ้าเดียวกันทั้งคู่ (ปัจจุบัน)',
     (13, 110, 253), (13, 110, 253), 'route 1.80 · pose 1.80'),
    ('B', 'Two-step blue', 'ทางน้ำเงินเข้ม · ฉันฟ้าสด',
     (10, 73, 196), (13, 110, 253), 'route 3.04 · pose 1.80'),
    ('C', 'Graphite path', 'ทางเทาเข้ม · ฉันเป็นสีเดียวบนแผนที่',
     (58, 68, 83), (13, 110, 253), 'route 3.94 · pose 1.80'),
    ('D', 'Navy path', 'ทางกรมท่า · ฉันฟ้าสว่าง',
     (18, 58, 143), (43, 139, 255), 'route 4.15 · pose 1.55'),
    ('E', 'Violet me', 'ทางฟ้า · ฉันม่วง',
     (13, 110, 253), (124, 58, 237), 'route 1.80 · pose 2.28'),

    # Green is crowded on this plan: the rooms are mint (hue 164), the lifts are
    # neon lime (hue 85), and the app already spends #22c55e on the lift marker.
    # Only a dark green clears all three - #22c55e itself scores 1.10 on the
    # turquoise and sits at 0 degrees from the lift marker.
    ('F', 'Forest path', 'ทางเขียวเข้ม · ฉันฟ้า',
     (20, 83, 45), (13, 110, 253), 'route 3.65 · pose 1.80'),
    ('G', 'Two-step green', 'เขียวเข้ม + เขียวกลาง',
     (20, 83, 45), (21, 128, 61), 'route 3.65 · pose 2.01'),
    ('H', 'Green me', 'ทางฟ้า · ฉันเขียว',
     (13, 110, 253), (21, 128, 61), 'route 1.80 · pose 2.01'),

    # Orange is squeezed between two colours the app already spends: the stairs
    # marker #f59e0b (hue 38) and the destination pin #e5484d (hue 358).
    # #ea580c (hue 21) is the widest gap available - 17 degrees from the stairs,
    # 22 from the pin - and it buys hue contrast against any blue or green path,
    # which is a stronger separator than a contrast ratio.
    ('I', 'Orange me', 'ทางฟ้า · ฉันส้ม',
     (13, 110, 253), (234, 88, 12), 'route 1.80 · pose 1.42'),
    ('J', 'Graphite + orange', 'ทางเทาเข้ม · ฉันส้ม',
     (58, 68, 83), (234, 88, 12), 'route 3.94 · pose 1.42'),
    ('K', 'Forest + orange', 'ทางเขียวเข้ม · ฉันส้ม',
     (20, 83, 45), (234, 88, 12), 'route 3.65 · pose 1.42'),
]


# --------------------------------------------------------------------------
# tiles
# --------------------------------------------------------------------------
def render_tile(plan, variant_fn, size_px, zoom, colours=(ACCENT, ACCENT), cast=False,
                ring=True, route_casing=True, route_style='line'):
    """One view of the route with the pose symbol on it.

    `cast=True` frames the whole route and adds the origin ring and destination
    pin, so a colour is judged next to the symbols it has to coexist with.
    """
    tw, th = size_px
    w, h = tw * SS, th * SS
    route_colour, pose_colour = colours

    span = MAP_SIZE / zoom
    pose = point_at_fraction(ROUTE, PROGRESS)

    # "slice": cover the tile, so the longer side sets the scale.
    scale = max(w, h) / span
    if cast:
        cx = (min(p[0] for p in ROUTE) + max(p[0] for p in ROUTE)) / 2
        cy = (min(p[1] for p in ROUTE) + max(p[1] for p in ROUTE)) / 2
    else:
        cx, cy = pose
    left, top = cx - (w / 2) / scale, cy - (h / 2) / scale

    crop = plan.resize((int(MAP_SIZE * scale), int(MAP_SIZE * scale)), Image.LANCZOS)
    img = Image.new('RGBA', (w, h), PAPER + (255,))
    img.paste(crop, (int(-left * scale), int(-top * scale)))

    def to_px(pt):
        return ((pt[0] - left) * scale, (pt[1] - top) * scale)

    # Symbol sizes are screen pixels of the FINAL tile, so at supersampled
    # resolution one screen pixel is exactly SS pixels - independent of how many
    # pixels a map unit happens to occupy.
    u = SS

    d = ImageDraw.Draw(img, 'RGBA')
    if route_style == 'dots':
        # Spacing is in screen pixels too, so the trail keeps its rhythm at any zoom.
        dots = [to_px(pt) for pt in sample_along_path(ROUTE, DOT_TRAIL_SPACING * u / scale)]
        if route_casing:
            for dx, dy in dots:
                r = DOT_TRAIL_CASING * u
                d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=WHITE)
        for dx, dy in dots:
            r = DOT_TRAIL_R * u
            d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=route_colour)
    else:
        line = [to_px(pt) for pt in ROUTE]
        if route_casing:
            d.line(line, fill=WHITE + (255,), width=max(1, int(ROUTE_CASING_W * u)), joint='curve')
        d.line(line, fill=route_colour + (255,), width=max(1, int(ROUTE_W * u)), joint='curve')

    if cast:
        draw_origin(ImageDraw.Draw(img, 'RGBA'), *to_px(ROUTE[0]), u)
        draw_dest(ImageDraw.Draw(img, 'RGBA'), *to_px(ROUTE[-1]), u)

    px, py = to_px(pose)
    img = variant_fn(img, px, py, math.radians(HEADING_DEG), u, pose_colour)
    draw_dot(ImageDraw.Draw(img, 'RGBA'), px, py, u, pose_colour, ring)

    return img.resize((tw, th), Image.LANCZOS)


def font(size, bold=False):
    for name in (('tahomabd.ttf', 'arialbd.ttf') if bold else ('tahoma.ttf', 'arial.ttf')):
        try:
            return ImageFont.truetype(f'C:/Windows/Fonts/{name}', size)
        except OSError:
            continue
    return ImageFont.load_default()


def sheet(cells, cols, tile_px, title, subtitle, out, cap_h=48):
    """cells: (index, name, thai, meta_or_None, draw_callable) -> one PNG."""
    tw, th = tile_px
    pad, gap, head_h = 26, 18, 74
    rows = math.ceil(len(cells) / cols)

    w = pad * 2 + cols * tw + (cols - 1) * gap
    h = head_h + pad + rows * (th + cap_h) + (rows - 1) * gap + pad
    canvas = Image.new('RGB', (w, h), PAPER)
    d = ImageDraw.Draw(canvas)

    d.text((pad, 26), title, font=font(21, True), fill=INK)
    d.text((pad, 52), subtitle, font=font(13), fill=INK_2)

    for i, (idx, name, thai, meta, draw_tile) in enumerate(cells):
        col, row = i % cols, i // cols
        x = pad + col * (tw + gap)
        y = head_h + pad + row * (th + cap_h + gap)

        canvas.paste(draw_tile().convert('RGB'), (x, y))
        d.rectangle([x, y, x + tw - 1, y + th - 1], outline=LINE)

        d.text((x, y + th + 9), f'{idx}  {name}', font=font(14, True), fill=INK)
        d.text((x, y + th + 27), thai, font=font(12), fill=INK_2)
        if meta:
            d.text((x, y + th + 44), meta, font=font(11), fill=INK_3)

    canvas.save(out)
    print(f'wrote {out}  ({w}x{h})')


# --------------------------------------------------------------------------
# ring vs no ring
# --------------------------------------------------------------------------
GROUNDS = [
    ('#ececec', 'ทางเดิน'),
    ('#d7d7d7', 'เทาเข้ม'),
    ('#6dc8c9', 'ห้อง'),
    ('#4bb3b4', 'ห้องเข้ม'),
    ('#000000', 'เส้นผนัง'),
]


def grounds_strip(colour, ring, width, height):
    """The symbol repeated across every ground it can land on."""
    w, h = width * SS, height * SS
    img = Image.new('RGBA', (w, h), PAPER + (255,))
    d = ImageDraw.Draw(img, 'RGBA')

    cell = w / len(GROUNDS)
    for i, (bg, _) in enumerate(GROUNDS):
        d.rectangle([i * cell, 0, (i + 1) * cell, h], fill=bg)

    for i, _ in enumerate(GROUNDS):
        cx, cy = (i + 0.5) * cell, h / 2
        img = v_sector(img, cx, cy, math.radians(0), SS, colour)
        draw_dot(ImageDraw.Draw(img, 'RGBA'), cx, cy, SS, colour, ring)

    return img.resize((width, height), Image.LANCZOS)


def ring_sheet():
    tw, th = 470, 96
    pad, gap, head_h, cap_h = 26, 16, 74, 44
    rows = [
        ('มีขอบขาว', 'ปัจจุบัน · จุดยืนได้ทุกพื้น', (13, 110, 253), True),
        ('ไม่มีขอบขาว', 'ตามที่ขอ · จุดล้วน ๆ', (13, 110, 253), False),
        ('ไม่มีขอบ · น้ำเงินเข้ม', '#0a49c4 · ทนพื้นสว่างกว่า', (10, 73, 196), False),
    ]

    w = pad * 2 + tw
    h = head_h + pad + len(rows) * (th + cap_h) + (len(rows) - 1) * gap + pad + 22
    canvas = Image.new('RGB', (w, h), PAPER)
    d = ImageDraw.Draw(canvas)
    d.text((pad, 26), 'จุดตำแหน่ง — ขอบขาว vs ไม่มีขอบ', font=font(21, True), fill=INK)
    d.text((pad, 52), 'สัญลักษณ์เดียวกันบนทุกพื้นที่มันไปอยู่ได้ · ใบพัดยังมีเส้นขอบตัวเองเสมอ',
           font=font(13), fill=INK_2)

    for i, (name, note, colour, ring) in enumerate(rows):
        y = head_h + pad + i * (th + cap_h + gap)
        canvas.paste(grounds_strip(colour, ring, tw, th).convert('RGB'), (pad, y))
        d.rectangle([pad, y, pad + tw - 1, y + th - 1], outline=LINE)
        d.text((pad, y + th + 9), name, font=font(14, True), fill=INK)
        d.text((pad, y + th + 27), note, font=font(12), fill=INK_2)

    cell = tw / len(GROUNDS)
    for i, (bg, label) in enumerate(GROUNDS):
        d.text((pad + i * cell, h - 26), f'{label}  {bg}', font=font(10), fill=INK_3)

    canvas.save(OUT_RING)
    print(f'wrote {OUT_RING}  ({w}x{h})')


ROUTE_ROWS = [
    ('มีขอบขาว', 'ปัจจุบัน · #0d6efd', (13, 110, 253), True),
    ('ไม่มีขอบขาว', 'สีเดิม · ห้องเทอร์ควอยซ์ 2.31', (13, 110, 253), False),
    ('ไม่มีขอบ · เข้มขึ้นหนึ่งขั้น', '#0a49c4 · ห้อง 3.89', (10, 73, 196), False),
    ('ไม่มีขอบ · เขียวป่า', '#14532d · ห้อง 4.67', (20, 83, 45), False),
]


def route_sheet(plan):
    """Whole route, so the line is judged where it crosses rooms - not just
    where it runs down a corridor."""
    tw, th = 300, 300
    cells = [(chr(ord('1') + i), name, note, None,
              (lambda c=colour, k=casing: render_tile(plan, v_sector, (tw, th), 1.05,
                                                      colours=(c, ACCENT), cast=True,
                                                      ring=False, route_casing=k)))
             for i, (name, note, colour, casing) in enumerate(ROUTE_ROWS)]
    sheet(cells, cols=2, tile_px=(tw, th),
          title='เส้นทาง — ขอบขาว vs ไม่มีขอบ',
          subtitle='ทั้งเส้น ตั้งแต่ต้นทางถึงปลายทาง · จุดตำแหน่งไม่มีขอบขาวทุกภาพ · '
                   'ตัวเลขคือ contrast บนห้องเทอร์ควอยซ์ที่เส้นต้องพาดผ่าน',
          out=OUT_ROUTE, cap_h=46)


DOT_ROWS = [
    ('จุดไข่ปลา + ขอบขาว', 'แบบเดิม · #0d6efd', (13, 110, 253), True),
    ('จุดไข่ปลา ไม่มีขอบ', 'สีเดิม · ห้องเทอร์ควอยซ์ 2.31', (13, 110, 253), False),
    ('จุดไข่ปลา ไม่มีขอบ · เข้มขึ้น', '#0a49c4 · ห้อง 3.89', (10, 73, 196), False),
    ('จุดไข่ปลา ไม่มีขอบ · เขียวป่า', '#14532d · ห้อง 4.67', (20, 83, 45), False),
]


def dots_sheet(plan):
    tw, th = 300, 300
    cells = [(str(i + 1), name, note, None,
              (lambda c=colour, k=casing: render_tile(plan, v_sector, (tw, th), 1.05,
                                                      colours=(c, ACCENT), cast=True,
                                                      ring=False, route_casing=k,
                                                      route_style='dots')))
             for i, (name, note, colour, casing) in enumerate(DOT_ROWS)]
    sheet(cells, cols=2, tile_px=(tw, th),
          title='เส้นทางแบบจุดไข่ปลา — ขอบขาว vs ไม่มีขอบ',
          subtitle='จุด r4 ทุก 17 px · จุดตำแหน่งไม่มีขอบขาวทุกภาพ · '
                   'ตัวเลขคือ contrast บนห้องเทอร์ควอยซ์ที่เส้นทางต้องพาดผ่าน',
          out=OUT_DOTS, cap_h=46)


def main():
    plan = Image.open(FLOOR_PLAN).convert('RGBA')
    ring_sheet()
    route_sheet(plan)
    dots_sheet(plan)

    sheet(
        [(idx, name, thai, None, (lambda fn=fn: render_tile(plan, fn, (300, 210), 2.9, ring=False)))
         for idx, name, thai, fn in VARIANTS],
        cols=3, tile_px=(300, 210),
        title='ตำแหน่งของฉัน — หกแบบให้เลือก',
        subtitle='เส้นทางเป็นเส้นตรงทึบทุกแบบ · จุด r7 ขอบขาว · สีทึบล้วน ไม่มี gradient',
        out=OUT_VARIANTS, cap_h=46)

    sheet(
        [(idx, name, thai, meta,
          (lambda rc=rc, pc=pc: render_tile(plan, v_sector, (300, 300), 1.05,
                                            colours=(rc, pc), cast=True, ring=False)))
         for idx, name, thai, rc, pc, meta in SCHEMES],
        cols=3, tile_px=(300, 300),
        title='สีเส้นทาง + สีตำแหน่ง — สิบเอ็ดชุด',
        subtitle='Radar sector ทุกชุด · มีหมุดปลายทางกับวงต้นทางในภาพด้วย · '
                 'ตัวเลขคือ contrast บนห้องสีเทอร์ควอยซ์เข้ม #4bb3b4',
        out=OUT_COLOURS, cap_h=62)


if __name__ == '__main__':
    main()
