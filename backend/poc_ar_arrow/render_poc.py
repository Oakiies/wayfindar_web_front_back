"""PoC harness: run a real walk video through localization and render the
shipping AR overlay next to the v2 candidate, frame for frame.

Both panes are driven by ONE localization pass and ONE smoother, so the only
difference between them is the overlay geometry — the same reason
ar_render_video.py exists upstream. Alongside the video it writes a CSV of
per-frame metrics and prints a summary, because "does it swing?" is a question
about frame-to-frame motion that is easier to measure than to eyeball.

Run from backend/:
    .venv/Scripts/python.exe poc_ar_arrow/render_poc.py
    .venv/Scripts/python.exe poc_ar_arrow/render_poc.py --start 2650 --end 3200
"""
import argparse
import csv
import math
import os
import sys
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.localization_config as lc                                  # noqa: E402
from app.core import navigation as nav                                # noqa: E402
from app.core.smoothing import create_smoother                        # noqa: E402
from app.services.floor_service import initialize_system, set_active_floor  # noqa: E402
from app.services.state import state                                  # noqa: E402
from app.services.video_processor import _sticky_route, _sticky_turn  # noqa: E402
from app.services import ar_service                                   # noqa: E402
from app.core.ar_geometry import M_PER_PX                             # noqa: E402
from app.utils.heading import (blend_heading_deg, normalize_heading_deg,
                               calculate_camera_heading)                 # noqa: E402

from poc_ar_arrow.ar_arrow_v2 import (                                # noqa: E402
    PoseStabilizer, build_ar_world_v2, render_v2,
)
from poc_ar_arrow.lucide_icons import draw_icon                       # noqa: E402

# The walk this PoC is judged on. Same clip/segment/destination the upstream AR
# work used, so results are comparable with what was validated before.
VIDEO = Path(__file__).resolve().parents[2].parent / 'navigate_indoor' / 'uploads' / 'floor5_2.mp4'
FLOOR = 'floor5'
MAP_IMAGE = Path(__file__).resolve().parents[2] / 'frontend-v3' / 'public' / 'system_data' / f'map/{FLOOR}.jpg'
DEST = 'Fire Exit 1'
ARRIVAL_LABEL = 'FIRE EXIT 1'
ARRIVAL_RADIUS_PX = 18.0
ARRIVAL_EXIT_RADIUS_PX = 50.0  # leave the arrived state after walking away
TARGET_PIN_RADIUS_PX = 90.0    # show the physical target pin only near the goal
TURN_FAR_PX = 70.0             # same turn window as navigate_indoor
FPS = 59.94
START_FRAME = 2650
END_FRAME = 7200
STEP = 3                       # ~20 AR updates/s, matching the upstream harness
OUT_DIR = Path(__file__).resolve().parent / 'out'
OUT_FPS = 20
PANE_W = 900                   # each pane is scaled to this width
MAP_POPUP_SIZE = 238           # square map card in each comparison pane
MAP_POPUP_MARGIN = 18
MAP_POPUP_TOP = 112             # below the debug strip and AR control row
MAP_POPUP_SS = 3
MAP_ROUTE_COLOR = (13, 110, 253, 255)  # one accent, matching frontend-v3
MAP_ORIGIN_COLOR = (17, 19, 21, 255)
MAP_DESTINATION_COLOR = (229, 72, 77, 255)
# Keep the radar in the same accent hue, but let the floor plan show through
# more gently in the exported navigation view.
MAP_POSE_FAN_FILL = (13, 110, 253, 64)
MAP_POSE_FAN_OUTLINE = (13, 110, 253, 132)


class _Session:
    """Minimal stand-in for NavigationSession — _sticky_* only touch these."""
    active_turn = None
    route_cache = None


class _PayloadHold:
    """Keep the last valid world overlay through a brief localization dropout.

    The production browser does this in ``_ar_world_or_hold``. Without the
    same behavior in this frame-by-frame comparison, one bad PnP sample clears
    the overlay and makes AR visibly blink even when the next sample is good.
    The payload contains floor-anchored world points, so a short hold freezes
    the last registered overlay instead of inventing a new screen position.
    """

    def __init__(self, max_gap_s):
        self.max_gap_s = float(max_gap_s)
        self.payload = None
        self.timestamp = None

    def resolve(self, fresh, timestamp):
        if fresh is not None:
            self.payload = fresh
            self.timestamp = float(timestamp)
            return fresh, False, 0.0
        if self.payload is not None and self.timestamp is not None:
            age = float(timestamp) - self.timestamp
            if age <= self.max_gap_s:
                held = dict(self.payload)
                held['heldAge'] = age
                return held, True, age
            self.payload = None
            self.timestamp = None
        return None, False, None


class _PinPoseFilter:
    """Extra-low-pass pose used only for the destination pin.

    The route overlay must follow a turn quickly, but the destination marker
    should behave like a fixed object in the corridor.  Giving it its own
    slower rotation filter prevents small PnP yaw changes from making the pin
    shimmer while preserving real camera movement.
    """

    def __init__(self, metres_per_unit):
        self.filter = PoseStabilizer(alpha=0.06, max_jump_m=0.25,
                                     max_turn_deg=5.0,
                                     turn_follow_deg=7.0,
                                     turn_alpha=0.10,
                                     metres_per_unit=metres_per_unit)
        self.last_R = None
        self.last_t = None
        self.jump_frames = 0

    def update(self, payload):
        if not payload:
            return None
        raw_R = np.asarray(payload['R'], float)
        raw_t = np.asarray(payload['t'], float).reshape(3)

        # A short PnP reacquisition can move the whole destination several
        # metres in one sample.  The normal AR stabilizer intentionally accepts
        # a sustained jump after four frames; a destination pin needs a longer
        # grace period so it does not visibly teleport during that hand-off.
        if self.last_R is not None and self.last_t is not None:
            old_C = -self.last_R.T @ self.last_t
            new_C = -raw_R.T @ raw_t
            step = float(np.linalg.norm(new_C - old_C))
            turn = float(np.linalg.norm(cv2.Rodrigues(raw_R @ self.last_R.T)[0]))
            if step > self.filter.max_jump * 1.8 or turn > math.radians(16.0):
                self.jump_frames += 1
                if self.jump_frames < 9:
                    out = dict(payload)
                    out['R'] = self.last_R
                    out['t'] = self.last_t
                    return out
            else:
                self.jump_frames = 0

        R, t = self.filter.update(raw_R, raw_t)
        out = dict(payload)
        out['R'] = R
        out['t'] = t
        self.last_R = np.asarray(R, float).copy()
        self.last_t = np.asarray(t, float).reshape(3).copy()
        return out

    def clear(self):
        """Forget the frozen destination pose when the user leaves the goal."""
        self.filter.R = None
        self.filter.C = None
        self.filter.held = 0
        self.last_R = None
        self.last_t = None
        self.jump_frames = 0


class _PinScreenFilter:
    """Limit screen-space jumps after a pose reacquisition."""

    def __init__(self, alpha=0.12, max_step_px=18.0, deadband_px=1.4):
        self.alpha = float(alpha)
        self.max_step = float(max_step_px)
        self.deadband = float(deadband_px)
        self.base = None
        self.top = None
        self.quad = None

    def _update(self, old, new):
        new = np.asarray(new, float)
        if old is None:
            return new.copy()
        delta = new - old
        distance = float(np.linalg.norm(delta))
        # Ignore sub-pixel/near-sub-pixel PnP noise.  Without a deadband the
        # antialiased pin edge visibly shimmers even when the camera is moving
        # steadily toward the destination.
        if distance <= self.deadband:
            return old.copy()
        if distance > self.max_step:
            new = old + delta * (self.max_step / distance)
        return (1.0 - self.alpha) * old + self.alpha * new

    def update(self, base, top, quad):
        self.base = self._update(self.base, base)
        self.top = self._update(self.top, top)
        self.quad = self._update(self.quad, quad)
        return self.base.copy(), self.top.copy(), self.quad.copy()

    def reset(self, base, top, quad):
        self.base = np.asarray(base, float).copy()
        self.top = np.asarray(top, float).copy()
        self.quad = np.asarray(quad, float).copy()
        return self.base.copy(), self.top.copy(), self.quad.copy()

    def clear(self):
        self.base = None
        self.top = None
        self.quad = None


def render_shipping(frame, payload):
    """Draw the shipping payload the way the browser draws it."""
    out = frame.copy()
    if not payload or not payload.get('chevrons'):
        return out
    fx, fy, cx, cy = payload['K']
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], float)
    R = np.asarray(payload['R'], float)
    t = np.asarray(payload['t'], float).reshape(3)
    rvec, _ = cv2.Rodrigues(R)
    alphas = payload.get('alphas') or []
    for i, poly_world in enumerate(payload['chevrons']):
        uv = cv2.projectPoints(np.asarray(poly_world, float), rvec, t, K,
                               np.zeros(4))[0].reshape(-1, 2)
        if not np.all(np.isfinite(uv)):
            continue
        alpha = alphas[i] if i < len(alphas) else 0.8
        if alpha <= 0.01:
            continue
        layer = out.copy()
        cv2.fillPoly(layer, [uv.astype(np.int32)], (255, 210, 40))
        out = cv2.addWeighted(layer, alpha, out, 1 - alpha, 0)
    return out


def _payload_camera(payload):
    """Return (K, R, t) for either shipping or v2 payload format."""
    if not payload:
        return None
    kval = np.asarray(payload.get('K'), float)
    if kval.shape == (4,):
        fx, fy, cx, cy = kval
        K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], float)
    else:
        K = kval.reshape(3, 3)
    return K, np.asarray(payload['R'], float), np.asarray(payload['t'], float).reshape(3)


def _font(size, bold=False):
    path = r'C:\Windows\Fonts\tahomabd.ttf' if bold else r'C:\Windows\Fonts\tahoma.ttf'
    try:
        return ImageFont.truetype(path, int(size))
    except OSError:
        return ImageFont.load_default()


CARD_SS = 4          # supersampling factor for the direction card
CARD_SHADOW_MARGIN = 18

# The controls mirror frontend-v3's NavigationView / IconButton: 44 px dark
# glass circles, with the close button on the left and camera/map controls on
# the right. The debug strip occupies the first 46 px of this offline video,
# so the controls start immediately below it.
AR_CONTROL_SIZE = 44
AR_CONTROL_TOP = 58
AR_CONTROL_MARGIN = 18
AR_CONTROL_GAP = 8
AR_CONTROL_SS = 3

_CARD_LABELS = {
    'YOU HAVE ARRIVED': ('arrived', 'Arrived'),
    'TURN RIGHT': ('right', 'Turn Right'),
    'TURN LEFT': ('left', 'Turn Left'),
}


@lru_cache(maxsize=32)
def _build_card_tile(kind, label, h, w, ss):
    """Render one direction card to a transparent tile.

    Cached: the card only depends on the instruction and the frame size, both of
    which are constant for long stretches of a render, so the supersampling is
    paid once per state instead of once per frame.

    Supersampling is what makes the card look clean - PIL's `rounded_rectangle`,
    `line` and `ellipse` have no anti-aliasing, so at 1x the pill edge and the
    3 px glyph strokes come out visibly stair-stepped. Only the card's own
    bounding box is drawn large, never the whole frame.

    Returns (tile, card_w, card_h, margin).
    """
    card_h = int(min(66, max(50, h * 0.125)))
    radius = card_h / 2.0
    glyph = card_h * 0.46
    line_w = max(2, int(round(card_h * 0.052)))

    text_font = _font(max(15, int(card_h * 0.30)) * ss, False)
    probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    text_w = probe.textlength(label, font=text_font) / ss

    pad_l = int(card_h * 0.40)
    gap = int(card_h * 0.30)
    pad_r = int(card_h * 0.40)
    card_w = min(int(pad_l + glyph * 1.2 + gap + text_w + pad_r), int(w * 0.52))

    margin = CARD_SHADOW_MARGIN
    tile_w, tile_h = card_w + margin * 2, card_h + margin * 2
    tile = Image.new('RGBA', (tile_w * ss, tile_h * ss), (0, 0, 0, 0))
    ox = oy = margin * ss
    box = (ox, oy, ox + card_w * ss, oy + card_h * ss)

    # Softer, tighter shadow than the previous card - it no longer needs to shout.
    shadow = Image.new('RGBA', tile.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0] + 2 * ss, box[1] + 5 * ss, box[2] + 2 * ss, box[3] + 5 * ss),
        radius=radius * ss, fill=(0, 0, 0, 70))
    tile = Image.alpha_composite(tile, shadow.filter(
        ImageFilter.GaussianBlur(9 * ss)))

    draw = ImageDraw.Draw(tile)
    # Hairline instead of the old 2 px outline.
    draw.rounded_rectangle(box, radius=radius * ss, fill=(253, 253, 253, 250),
                           outline=(0, 0, 0, 18), width=max(1, ss))

    ink = (28, 28, 32, 255)
    cy = oy + card_h * ss / 2.0
    cx = ox + (pad_l + glyph * 0.6) * ss
    draw_icon(draw, kind, cx, cy, glyph * 1.2 * ss, ink, line_w * ss)
    draw.text((cx + (glyph * 0.6 + gap) * ss, cy), label, anchor='lm',
              font=text_font, fill=ink)

    return tile.resize((tile_w, tile_h), Image.LANCZOS), card_w, card_h, margin


def render_instruction_card(frame, thai, english, accent=(16, 185, 129),
                            destination=None):
    """Composite the compact pill-shaped direction card onto `frame`.

    The card is sized to its own content rather than to a fixed fraction of the
    frame, so a short label gets a short card. About 65% less screen area than
    the previous 324x101 version (2.4% of the frame instead of 7.2%), which
    covered more of the corridor than it needed to.

    `thai` and `accent` are unused - kept so the existing call sites in the
    render loop do not have to change.
    """
    h, w = frame.shape[:2]
    kind, label = _CARD_LABELS.get(english, ('straight', 'Go Straight'))
    tile, card_w, card_h, margin = _build_card_tile(kind, label, h, w, CARD_SS)

    im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert('RGBA')
    x1 = (w - card_w) // 2
    # Leave a little breathing room below the debug strip; the card should not
    # compete with the status bar at the very top of the demo frame.
    y1 = max(56, int(h * 0.14))
    im.alpha_composite(tile, (x1 - margin, y1 - margin))
    return cv2.cvtColor(np.asarray(im.convert('RGB')), cv2.COLOR_RGB2BGR)


def render_ar_controls(frame, top_override=None):
    """Draw the three fixed AR controls used by frontend-v3.

    This is presentation chrome only; the offline PoC does not need to attach
    click handlers. Keeping the exact order and Lucide glyphs makes the video
    preview read like the real AR navigation screen: close / camera-off / map.
    """
    h, w = frame.shape[:2]
    ss = AR_CONTROL_SS
    size = AR_CONTROL_SIZE
    top = AR_CONTROL_TOP if top_override is None else int(top_override)
    margin = AR_CONTROL_MARGIN
    gap = AR_CONTROL_GAP
    right_x = w - margin - size * 2 - gap
    positions = (
        (margin, top, 'close'),
        (right_x, top, 'camera-off'),
        (w - margin - size, top, 'map'),
    )

    layer = Image.new('RGBA', (w * ss, h * ss), (0, 0, 0, 0))
    shadow = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, 'RGBA')
    button_draw = ImageDraw.Draw(layer, 'RGBA')
    for x, y, _icon in positions:
        box = ((x + 2) * ss, (y + 4) * ss,
               (x + size + 2) * ss, (y + size + 4) * ss)
        shadow_draw.ellipse(box, fill=(0, 0, 0, 100))
    layer = Image.alpha_composite(layer, shadow.filter(ImageFilter.GaussianBlur(6 * ss)))
    button_draw = ImageDraw.Draw(layer, 'RGBA')
    for x, y, icon_name in positions:
        box = (x * ss, y * ss, (x + size) * ss, (y + size) * ss)
        button_draw.ellipse(box, fill=(17, 19, 21, 148),
                            outline=(255, 255, 255, 41), width=ss)
        draw_icon(button_draw, icon_name,
                  (x + size / 2) * ss, (y + size / 2) * ss,
                  20 * ss, (255, 255, 255, 255), width=2 * ss)

    im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert('RGBA')
    im.alpha_composite(layer.resize((w, h), Image.LANCZOS))
    return cv2.cvtColor(np.asarray(im.convert('RGB')), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------------------
# Top-down map popup: the same symbol system as frontend-v3 / map style 1
# ---------------------------------------------------------------------------

MAP_ROUTE_DOT_SPACING = 17.0
MAP_ROUTE_DOT_RADIUS = 4.0
MAP_ROUTE_CASING_RADIUS = 6.2
MAP_POSE_RADIUS = 7.0
MAP_POSE_CASING_RADIUS = 2.4
MAP_POSE_FAN_RADIUS = 30.0
MAP_POSE_FAN_HALF_ANGLE = 32.0


@lru_cache(maxsize=2)
def _load_map_image(path):
    return Image.open(path).convert('RGBA')


@lru_cache(maxsize=8)
def _map_card_base(path, size):
    """Resize the immutable floor image once per popup size."""
    return _load_map_image(path).resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=8)
def _map_shadow(size, ss):
    """Cache the static popup shadow; only the pose/route pixels change."""
    shadow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (3 * ss, 5 * ss, size - 1, size - 1), radius=14 * ss,
        fill=(0, 0, 0, 90))
    return shadow.filter(ImageFilter.GaussianBlur(7 * ss))


def _sample_map_route(points, spacing=MAP_ROUTE_DOT_SPACING):
    """Return evenly spaced route dots in the floor-plan coordinate system."""
    if len(points) < 2 or spacing <= 0:
        return []
    points = [(float(p[0]), float(p[1])) for p in points]
    samples = [points[0]]
    carried = 0.0
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        travelled = spacing - carried
        while travelled <= length:
            ratio = travelled / length
            samples.append((a[0] + dx * ratio, a[1] + dy * ratio))
            travelled += spacing
        carried = (carried + length) % spacing
    return samples


def render_map_popup(frame, route_coords, current_xy=None, heading_deg=None,
                     floor_label=FLOOR, pose_age_s=None, corner='top-right',
                     top_override=None, size_override=None,
                     margin_override=None):
    """Composite a square, top-down map card in the pane's upper-right corner.

    The card intentionally mirrors MapCanvas style 1: one blue accent, evenly
    spaced blue dots with white casing, a radar sector for the live pose, a
    dark origin ring, and a red destination pin. The route is the cached route
    from the first valid localization, while `current_xy` comes from the same
    source frame being rendered; this keeps the popup spatially meaningful.
    The card stays in the upper-right corner for the complete navigation run;
    the control row is placed above it, matching frontend-v3.
    """
    if not route_coords or not MAP_IMAGE.exists():
        return frame

    h, w = frame.shape[:2]
    popup_top = MAP_POPUP_TOP if top_override is None else int(top_override)
    popup_size = MAP_POPUP_SIZE if size_override is None else int(size_override)
    popup_margin = MAP_POPUP_MARGIN if margin_override is None else int(margin_override)
    size = min(popup_size, w - 2 * popup_margin,
               h - popup_top - popup_margin)
    if size < 80:
        return frame

    ss = MAP_POPUP_SS
    map_size = int(size * ss)
    scale = size / 500.0
    card = _map_card_base(str(MAP_IMAGE), map_size).copy()
    draw = ImageDraw.Draw(card, 'RGBA')

    def xy(point):
        return (float(point[0]) * scale, float(point[1]) * scale)

    def ellipse(cx, cy, radius, fill):
        draw.ellipse(((cx - radius) * ss, (cy - radius) * ss,
                      (cx + radius) * ss, (cy + radius) * ss), fill=fill)

    def polygon(points, fill=None, outline=None, width=1):
        pts = [(px * ss, py * ss) for px, py in points]
        draw.polygon(pts, fill=fill)
        if outline is not None:
            draw.line(pts + [pts[0]], fill=outline, width=max(1, int(width * ss)), joint='curve')

    route_dots = _sample_map_route(route_coords)
    for point in route_dots:
        px, py = xy(point)
        ellipse(px, py, max(3.1, MAP_ROUTE_CASING_RADIUS * scale), (255, 255, 255, 255))
    for point in route_dots:
        px, py = xy(point)
        ellipse(px, py, max(2.0, MAP_ROUTE_DOT_RADIUS * scale), MAP_ROUTE_COLOR)

    origin_x, origin_y = xy(route_coords[0])
    ellipse(origin_x, origin_y, max(4.0, 8.0 * scale + 1.2), (255, 255, 255, 255))
    draw.ellipse(((origin_x - max(3.8, 8.0 * scale)) * ss,
                  (origin_y - max(3.8, 8.0 * scale)) * ss,
                  (origin_x + max(3.8, 8.0 * scale)) * ss,
                  (origin_y + max(3.8, 8.0 * scale)) * ss),
                 outline=MAP_ORIGIN_COLOR, width=max(1, int(2.1 * scale * ss)))

    dest_x, dest_y = xy(route_coords[-1])
    dest_radius = max(5.8, 11.0 * scale)
    dest_distance = dest_radius * 2.4
    pin = [((dest_x + px) * ss, (dest_y + py) * ss)
           for px, py in _teardrop(dest_radius, dest_distance)]
    draw.polygon(pin, fill=MAP_DESTINATION_COLOR, outline=(255, 255, 255, 255))
    hole = max(1.6, dest_radius * 0.30)
    hole_y = (dest_y - dest_distance) * ss
    draw.ellipse(((dest_x - hole) * ss, hole_y - hole * ss,
                  (dest_x + hole) * ss, hole_y + hole * ss),
                 fill=(255, 255, 255, 255))

    if current_xy is not None:
        pose_x, pose_y = xy(current_xy)
        if heading_deg is not None and np.isfinite(heading_deg):
            heading = math.radians(float(heading_deg))
            spread = math.radians(MAP_POSE_FAN_HALF_ANGLE)
            fan = [(pose_x, pose_y)] + [
                (pose_x + math.cos(heading - spread + 2 * spread * i / 32)
                 * MAP_POSE_FAN_RADIUS * scale,
                 pose_y + math.sin(heading - spread + 2 * spread * i / 32)
                 * MAP_POSE_FAN_RADIUS * scale)
                for i in range(33)
            ]
            polygon(fan, fill=MAP_POSE_FAN_FILL, outline=MAP_POSE_FAN_OUTLINE,
                    width=1.4)
        ellipse(pose_x, pose_y,
                max(4.0, (MAP_POSE_RADIUS + MAP_POSE_CASING_RADIUS) * scale),
                (255, 255, 255, 255))
        ellipse(pose_x, pose_y, max(3.2, MAP_POSE_RADIUS * scale), MAP_ROUTE_COLOR)

    # Round the card and add a quiet elevation shadow, matching the popup's
    # floating treatment without obscuring the floor plan.
    mask = Image.new('L', (map_size, map_size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, map_size - 1, map_size - 1), radius=14 * ss, fill=255)
    card.putalpha(mask)
    x0 = (w - popup_margin - size if corner == 'top-right'
          else popup_margin)
    y0 = popup_top
    # Keep the supersampled temporary surface local to the popup. The old
    # implementation allocated a full frame at 3x only to crop this square
    # back out, which made native-resolution exports unnecessarily expensive.
    crop = Image.new('RGBA', (map_size, map_size), (0, 0, 0, 0))
    crop.alpha_composite(_map_shadow(map_size, ss), (0, 0))
    crop.alpha_composite(card, (0, 0))
    crop = crop.resize((size, size), Image.LANCZOS)
    # Convert only the popup ROI instead of round-tripping the entire camera
    # frame through PIL. This matters for 1920x1080 native exports, where the
    # map is a small overlay but the full-frame conversion dominates runtime.
    ix0, iy0 = int(x0), int(y0)
    roi = frame[iy0:iy0 + size, ix0:ix0 + size]
    im = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)).convert('RGBA')
    im.alpha_composite(crop, (0, 0))
    frame[iy0:iy0 + size, ix0:ix0 + size] = cv2.cvtColor(
        np.asarray(im.convert('RGB')), cv2.COLOR_RGB2BGR)
    return frame


# --------------------------------------------------------------------------
# Destination marker: a landmark, not a rectangle
# --------------------------------------------------------------------------
#
# The old marker was three unrelated pieces: an axis-aligned translucent quad
# on the floor, a straight 5 px stem, and a hand-built diamond with a HERSHEY
# caption in a black box. Nothing about it said "the place you are going to" -
# and none of it was anti-aliased, while the direction cards next to it are
# supersampled through PIL.
#
# The replacement is one object seen in perspective:
#
#   floor    a real circle on the floor plane, projected - so it lands as an
#            ellipse that leans with the floor instead of a rectangle pasted
#            flat on the screen. Two rings and a centre dot, the same bullseye
#            that sits inside the head.
#   stem     tapered, wide at the floor and narrow at the head, which is what
#            a vertical post does in perspective.
#   head     a true teardrop (a circle closed by its own tangent lines, the
#            same construction the map pin in frontend-v3 uses), with the
#            bullseye inside it - or the lucide check once arrived.
#   label    the pill from the direction cards: near-white, hairline outline,
#            soft shadow, real type. Carries the name and the distance left.
#
# Colour comes from the app's own palette rather than a new one: #e5484d, the
# destination red used on the map, and #22c55e on arrival. AR and map now name
# the destination in the same colour.
#
# Everything is drawn into a small RGBA tile at PIN_SS and downsampled once, so
# the whole marker is anti-aliased without supersampling the frame.

PIN_APPROACH_BGR = (77, 72, 229)     # #e5484d
PIN_ARRIVED_BGR = (94, 197, 34)      # #22c55e
PIN_SS = 3
PIN_HEAD_M = 1.15                    # head height above the floor
PIN_STEM_MAX = 0.24                  # ...but never more than this much of the frame
PIN_RING_M = 0.48                    # outer floor ring radius
PIN_RING_INNER_M = 0.29
PIN_LABEL_GAP = 12                   # px between head and label pill


def _bgr_to_rgb(colour):
    return (int(colour[2]), int(colour[1]), int(colour[0]))


def _teardrop(radius, distance, steps=48):
    """Pin outline with its tip at (0, 0) and its head `distance` above.

    A circle of `radius` closed by the two lines tangent to it, so the taper
    meets the head smoothly instead of bulging out of it. Same construction as
    `buildPinPath` in frontend-v3's MapCanvas, so the AR marker and the map
    marker are literally the same shape.
    """
    cos_phi = radius / distance
    sin_phi = math.sqrt(max(0.0, 1.0 - cos_phi * cos_phi))
    tx, ty = radius * sin_phi, -distance + radius * cos_phi

    a1 = math.atan2(cos_phi, sin_phi)
    a2 = -math.pi - a1
    arc = [(math.cos(a1 + (a2 - a1) * i / steps) * radius,
            -distance + math.sin(a1 + (a2 - a1) * i / steps) * radius)
           for i in range(steps + 1)]
    return [(0.0, 0.0), (tx, ty)] + arc + [(-tx, ty)]


def _bullseye(draw, cx, cy, radius, ss):
    """The mark repeated on the floor and inside the head, so the two read as
    one object rather than two decorations."""
    ring_w = max(1, int(radius * 0.20))
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 outline=(255, 255, 255, 255), width=ring_w)
    dot = radius * 0.30
    draw.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=(255, 255, 255, 255))


@lru_cache(maxsize=32)
def _build_pin_label(title, sub, h, ss):
    """The direction card's pill, reused for the destination name.

    Sized off the pane height like `_build_card_tile`, so the two pieces of
    chrome stay in proportion to each other; cached on its text and that
    height, and the distance is rounded to whole metres, so this is rebuilt a
    handful of times across a walk rather than once a frame.
    """
    title_px = int(min(19, max(14, h * 0.036)))
    sub_px = int(min(15, max(11, h * 0.027)))
    title_font = _font(title_px * ss, True)
    sub_font = _font(sub_px * ss, False)

    probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    title_w = probe.textlength(title, font=title_font) / ss
    sub_w = probe.textlength(sub, font=sub_font) / ss if sub else 0

    pad_x, pad_t, pad_b = 15, 9, 11
    line_gap = 2
    title_h, sub_h = int(title_px * 1.25), int(sub_px * 1.25)
    text_w = max(title_w, sub_w)
    card_w = int(text_w + pad_x * 2)
    card_h = int(pad_t + title_h + (line_gap + sub_h if sub else 0) + pad_b)

    margin = CARD_SHADOW_MARGIN
    tile = Image.new('RGBA', ((card_w + margin * 2) * ss, (card_h + margin * 2) * ss), (0, 0, 0, 0))
    ox = oy = margin * ss
    box = (ox, oy, ox + card_w * ss, oy + card_h * ss)
    radius = 12 * ss

    shadow = Image.new('RGBA', tile.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0] + 2 * ss, box[1] + 5 * ss, box[2] + 2 * ss, box[3] + 5 * ss),
        radius=radius, fill=(0, 0, 0, 70))
    tile = Image.alpha_composite(tile, shadow.filter(ImageFilter.GaussianBlur(9 * ss)))

    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle(box, radius=radius, fill=(253, 253, 253, 250),
                           outline=(0, 0, 0, 18), width=max(1, ss))

    cx = ox + card_w * ss / 2.0
    draw.text((cx, oy + pad_t * ss), title, anchor='ma', font=title_font, fill=(28, 28, 32, 255))
    if sub:
        draw.text((cx, oy + (pad_t + title_h + line_gap) * ss), sub, anchor='ma',
                  font=sub_font, fill=(120, 124, 132, 255))

    return (tile.resize((card_w + margin * 2, card_h + margin * 2), Image.LANCZOS),
            card_w, card_h, margin)


def render_destination_pin(frame, payload, proj, destination_xy, title,
                           arrived=False, screen_filter=None, distance_m=None):
    """Draw the world-anchored destination marker onto `frame`."""
    out = frame.copy()
    camera = _payload_camera(payload)
    if camera is None or destination_xy is None:
        return out

    K, R, t = camera
    dx, dy = float(destination_xy[0]), float(destination_xy[1])

    centre = proj.floor_point(dx, dy)
    up = -np.asarray(proj.down, float)
    top = centre + proj.m(PIN_HEAD_M) * up

    # cv2.projectPoints still returns finite-looking pixels for a point behind
    # the camera. That was why, after turning away from the exit, the marker
    # appeared to jump into the middle of the frame.
    centre_cam_z = float((R @ centre + t)[2])
    top_cam_z = float((R @ top + t)[2])
    if (not np.isfinite(centre_cam_z) or not np.isfinite(top_cam_z) or
            centre_cam_z <= 0.15 or top_cam_z <= 0.15):
        if screen_filter is not None:
            screen_filter.clear()
        return out

    ex = proj.direction(dx, dy, 1.0, 0.0)
    ey = proj.direction(dx, dy, 0.0, 1.0)
    rvec, _ = cv2.Rodrigues(R)

    def project(points):
        pts = np.asarray(points, float).reshape(-1, 3)
        uv = cv2.projectPoints(pts, rvec, t, K, np.zeros(4))[0].reshape(-1, 2)
        return uv

    def floor_ring(metres, steps=64):
        r = proj.m(metres)
        return [centre + math.cos(a) * r * ex + math.sin(a) * r * ey
                for a in (2 * math.pi * i / steps for i in range(steps))]

    outer = floor_ring(PIN_RING_M)
    inner = floor_ring(PIN_RING_INNER_M)
    cardinals = [centre + proj.m(PIN_RING_M) * v for v in (ex, -ex, ey, -ey)]

    base_uv = project([centre])[0]
    top_uv = project([top])[0]
    outer_uv = project(outer)
    inner_uv = project(inner)
    card_uv = project(cardinals)

    if not (np.all(np.isfinite(base_uv)) and np.all(np.isfinite(top_uv)) and
            np.all(np.isfinite(outer_uv)) and np.all(np.isfinite(inner_uv))):
        return out

    # Smooth the marker in screen space, then move the rings by the same
    # correction. Pose noise is overwhelmingly translation, so shifting the
    # projected shape removes the shimmer without having to filter 64 points.
    if screen_filter is not None:
        h, w = out.shape[:2]
        old_top = screen_filter.top
        old_visible = old_top is not None and 0 <= old_top[0] < w and 0 <= old_top[1] < h
        new_visible = 0 <= top_uv[0] < w and 0 <= top_uv[1] < h
        raw_base = base_uv.copy()
        if old_top is not None and not old_visible and new_visible:
            base_uv, top_uv, _ = screen_filter.reset(base_uv, top_uv, card_uv)
        else:
            base_uv, top_uv, _ = screen_filter.update(base_uv, top_uv, card_uv)
        shift = base_uv - raw_base
        outer_uv = outer_uv + shift
        inner_uv = inner_uv + shift

    frame_h = out.shape[0]

    # Cap the stem in screen space. The head is anchored 1.15 m above the floor,
    # which is right at a distance but turns into a lamppost when the marker is
    # two metres away: the projected stem grows without limit as the floor point
    # drops toward the bottom of the frame. The ring on the floor is the part
    # that has to stay world-anchored; the head is a label for it, so sliding
    # the head down its own stem costs nothing and keeps the object readable.
    stem = top_uv - base_uv
    stem_len = float(np.linalg.norm(stem))
    max_stem = PIN_STEM_MAX * frame_h
    if stem_len > max_stem > 0:
        top_uv = base_uv + stem * (max_stem / stem_len)

    colour = _bgr_to_rgb(PIN_ARRIVED_BGR if arrived else PIN_APPROACH_BGR)
    head_r = min(34.0, max(19.0, frame_h * 0.053)) * (1.12 if arrived else 1.0)
    head_h = head_r * 2.45
    head = [(top_uv[0] + px, top_uv[1] + py) for px, py in _teardrop(head_r, head_h)]

    sub = ''
    if arrived:
        sub = 'Arrived'
    elif distance_m is not None and np.isfinite(distance_m):
        sub = f'{distance_m:.0f} m away'
    label, label_w, label_h, label_margin = _build_pin_label(title, sub, frame_h, CARD_SS)

    label_x = int(round(top_uv[0] - label_w / 2.0))
    label_y = int(round(top_uv[1] - head_h - head_r - PIN_LABEL_GAP - label_h))
    label_x = max(8, min(label_x, out.shape[1] - label_w - 8))
    label_y = max(56, label_y)

    # One tile around everything, drawn at PIN_SS and downsampled once.
    xs = list(outer_uv[:, 0]) + [p[0] for p in head] + [label_x, label_x + label_w]
    ys = list(outer_uv[:, 1]) + [p[1] for p in head] + [label_y, label_y + label_h]
    pad = 8
    x0 = max(0, int(math.floor(min(xs))) - pad)
    y0 = max(0, int(math.floor(min(ys))) - pad)
    x1 = min(out.shape[1], int(math.ceil(max(xs))) + pad)
    y1 = min(out.shape[0], int(math.ceil(max(ys))) + pad)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return out

    ss = PIN_SS
    tile = Image.new('RGBA', ((x1 - x0) * ss, (y1 - y0) * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile, 'RGBA')

    def T(points):
        return [((px - x0) * ss, (py - y0) * ss) for px, py in points]

    # ---- floor: a circle in perspective, not a rectangle on the screen ----
    draw.polygon(T(inner_uv), fill=colour + (46,))
    draw.line(T(outer_uv) + [T(outer_uv)[0]], fill=colour + (255,),
              width=max(1, int(3.0 * ss)), joint='curve')
    draw.line(T(inner_uv) + [T(inner_uv)[0]], fill=(255, 255, 255, 210),
              width=max(1, int(1.8 * ss)), joint='curve')

    # ---- stem: wide at the floor, narrow at the head ----
    bx, by = (base_uv[0] - x0) * ss, (base_uv[1] - y0) * ss
    tx_, ty_ = (top_uv[0] - x0) * ss, (top_uv[1] - y0) * ss
    half_base, half_top = 4.6 * ss, 2.2 * ss
    draw.polygon([(bx - half_base, by), (bx + half_base, by),
                  (tx_ + half_top, ty_), (tx_ - half_top, ty_)],
                 fill=colour + (255,), outline=(255, 255, 255, 235), width=max(1, int(1.2 * ss)))

    # ---- head ----
    draw.polygon(T(head), fill=colour + (255,),
                 outline=(255, 255, 255, 255), width=max(1, int(2.0 * ss)))
    hx, hy = tx_, ty_ - head_h * ss
    if arrived:
        draw_icon(draw, 'arrived', hx, hy, head_r * 1.15 * ss, (255, 255, 255, 255),
                  max(1, int(2.0 * ss)))
    else:
        _bullseye(draw, hx, hy, head_r * 0.52 * ss, ss)

    # The floor bullseye is drawn last so the stem does not cut through it.
    _bullseye(draw, bx, by, 4.4 * ss, ss)

    tile = tile.resize((x1 - x0, y1 - y0), Image.LANCZOS)

    region = Image.fromarray(cv2.cvtColor(out[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)).convert('RGBA')
    region.alpha_composite(tile)
    out[y0:y1, x0:x1] = cv2.cvtColor(np.asarray(region.convert('RGB')), cv2.COLOR_RGB2BGR)

    # The label sits on the frame, not in the world, so it is composited after
    # the perspective tile and clamped into view on its own.
    im = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).convert('RGBA')
    im.alpha_composite(label, (label_x - label_margin, label_y - label_margin))
    return cv2.cvtColor(np.asarray(im.convert('RGB')), cv2.COLOR_RGB2BGR)


def label(img, text, colour=(255, 255, 255)):
    cv2.rectangle(img, (0, 0), (img.shape[1], 46), (0, 0, 0), -1)
    cv2.putText(img, text, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, colour, 2, cv2.LINE_AA)
    return img


def probe_point(proj, path_coords, cum_ahead_px=45.0):
    """A fixed world point on the route, used as the jitter probe.

    Jitter has to be measured on something that does NOT move in the world, or
    the walker's own motion shows up as instability. A route point at a fixed
    arc length is nailed to the building; everything that moves it on screen is
    pose error.
    """
    if len(path_coords) < 2:
        return None
    total = 0.0
    for a, b in zip(path_coords, path_coords[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if total + d >= cum_ahead_px:
            f = (cum_ahead_px - total) / (d or 1.0)
            px, py = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
            return proj.floor_point(px, py)
        total += d
    return proj.floor_point(*path_coords[-1])


def project_one(point_world, R, t, K):
    point = np.asarray(point_world, float).reshape(-1)
    if point.size != 3:
        return None
    rvec, _ = cv2.Rodrigues(np.asarray(R, float))
    uv = cv2.projectPoints(point.reshape(1, 3), rvec,
                           np.asarray(t, float).reshape(3), np.asarray(K, float),
                           np.zeros(4))[0].reshape(-1)
    return uv if np.all(np.isfinite(uv)) else None


def second_difference(series):
    """Median |p[i+1] - 2p[i] + p[i-1]|, in px.

    A walker moving smoothly makes the probe drift smoothly, so first
    differences are large and meaningless. The second difference is ~0 for any
    smooth motion and spikes on every pose glitch, which is exactly the "swing"
    being complained about.
    """
    vals = []
    for a, b, c in zip(series, series[1:], series[2:]):
        if a is None or b is None or c is None:
            continue
        d = np.asarray(a) - 2 * np.asarray(b) + np.asarray(c)
        vals.append(float(np.linalg.norm(d)))
    if not vals:
        return float('nan'), float('nan')
    vals.sort()
    return vals[len(vals) // 2], vals[int(len(vals) * 0.9)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, default=START_FRAME)
    ap.add_argument('--end', type=int, default=END_FRAME)
    ap.add_argument('--step', type=int, default=STEP)
    ap.add_argument('--out', default=str(OUT_DIR / 'ar_poc_ui1_map.avi'))
    ap.add_argument('--metrics', default=str(OUT_DIR / 'ar_poc_ui1_map_metrics.csv'))
    ap.add_argument('--dest', default=DEST)
    ap.add_argument('--arrival-label', default=ARRIVAL_LABEL)
    ap.add_argument('--pane', choices=('both', 'left', 'right'), default='both',
                    help='Export both comparison panes or only one pane.')
    ap.add_argument('--native', action='store_true',
                    help='Keep the source video resolution instead of scaling panes.')
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not VIDEO.exists():
        raise SystemExit(f'video not found: {VIDEO}')

    # app.config chdir()s into backend/app/ at import time, so a relative --out
    # would land somewhere nobody looks (and VideoWriter fails silently there,
    # leaving a run with metrics but no video). Anchor it next to this script.
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = OUT_DIR / out_path.name
    args.out = str(out_path)
    metrics_path = Path(args.metrics)
    if not metrics_path.is_absolute():
        metrics_path = OUT_DIR / metrics_path.name

    print('init...', flush=True)
    initialize_system()
    set_active_floor(FLOOR)
    loc = state.localizer
    proj = ar_service.get_projector(FLOOR, loc)
    print(f'scale: 1 world unit = {proj.metres_per_unit:.3f} m', flush=True)

    smoother = create_smoother(lc.SMOOTHER_CONFIG['position'])
    session = _Session()
    # The comparison video contains short PnP dropouts around the second
    # corner (roughly video seconds 32–33).  A slower EMA prevents the floor
    # arrows from snapping when the next pose is reacquired, while the higher
    # turn threshold still lets a genuine phone turn follow through.
    stabilizer = PoseStabilizer(alpha=0.24, max_jump_m=1.0,
                                max_turn_deg=22.0, turn_follow_deg=6.0,
                                turn_alpha=0.50,
                                metres_per_unit=proj.metres_per_unit)
    pin_filter = _PinPoseFilter(proj.metres_per_unit)
    pose_dumped = False
    pin_screen_a = _PinScreenFilter()
    pin_screen_b = _PinScreenFilter()
    # Match the live endpoint's last-valid-fix policy. The held payload carries
    # heldAge and the browser fades confidence while waiting for a fresh pose;
    # removing it after four video frames was the source of the visible blink.
    hold_gap_s = max(3.0, 3.0 * args.step / FPS)
    hold_a = _PayloadHold(hold_gap_s)
    hold_b = _PayloadHold(hold_gap_s)
    map_route = None
    map_position = None
    map_heading = None
    map_last_fix_ts = None
    arrived = False
    arrival_xy = None
    destination_xy = None
    arrival_marker = None
    pin_payload = None
    instruction_state = ('ตรงไป', 'GO STRAIGHT', (16, 185, 129), None)

    cap = cv2.VideoCapture(str(VIDEO))
    writer = None
    rows = []
    probe_raw, probe_smooth = [], []
    reasons_a, reasons_b = {}, {}
    n_written = 0
    t0 = time.time()

    fi = args.start
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    while fi <= args.end:
        ok, frame = cap.read()
        if not ok:
            break
        source_ts = fi / FPS
        output_ts = n_written / OUT_FPS
        ts = source_ts
        result, xy = loc.localize(frame)
        x = y = None
        if result.get('success') and xy is not None:
            sm = smoother.update(float(xy[0]), float(xy[1]), ts,
                                 int(result.get('num_inliers', 0) or 0),
                                 measured_heading=result.get('heading'))
            if len(sm) >= 2 and sm[0] is not None:
                x, y = sm[0], sm[1]

        if x is not None:
            pose_for_map = result.get('pose') or {}
            measured_heading = calculate_camera_heading(
                pose_for_map.get('R'), x, y, proj
            )
            if measured_heading is None:
                theta = pose_for_map.get('theta')
                if theta is not None and np.isfinite(theta):
                    measured_heading = normalize_heading_deg(90.0 - float(theta))
            if measured_heading is not None:
                map_heading = (measured_heading if map_heading is None else
                               blend_heading_deg(map_heading, measured_heading, 0.45))
            map_position = (float(x), float(y))
            map_last_fix_ts = source_ts

        pane_a = frame
        pane_b = frame
        reason_a = reason_b = 'no_fix'
        n_a = n_b = 0
        raw_pay_a = raw_pay_b = None
        pin_visible = False

        if x is not None:
            route = _sticky_route(session, FLOOR, x, y, args.dest, FLOOR)
            pc = route['path_coords'] if route else []
            if route and pc:
                map_route = list(pc)
                candidate_arrival = (float(pc[-1][0]), float(pc[-1][1]))
                destination_xy = candidate_arrival
                distance_to_goal = math.hypot(x - candidate_arrival[0],
                                              y - candidate_arrival[1])
                if (not arrived and
                        distance_to_goal <= ARRIVAL_RADIUS_PX):
                    arrived = True
                    arrival_xy = candidate_arrival
                elif (arrived and
                      distance_to_goal >= ARRIVAL_EXIT_RADIUS_PX):
                    # The user has left the destination. Do not keep using the
                    # pose captured at arrival; resume live navigation and let
                    # the target pin track the current camera again.
                    arrived = False
                    arrival_xy = None
                    arrival_marker = None
                    pin_payload = None
                    pin_filter.clear()
                    pin_screen_a.clear()
                    pin_screen_b.clear()
                    session.active_turn = None
                    session.turn_gap = None
            if arrived and arrival_xy is None and route and pc:
                arrival_xy = (float(pc[-1][0]), float(pc[-1][1]))

            if arrived:
                instruction_state = ('ถึงปลายทางแล้ว', 'YOU HAVE ARRIVED', (16, 185, 129), 0.0)
            elif route and pc:
                next_turn = _sticky_turn(session, x, y,
                                         nav.next_turn_info(x, y, pc))
                if next_turn and next_turn['dist'] < TURN_FAR_PX:
                    if next_turn['dir'] > 0:
                        instruction_state = ('เลี้ยวขวา', 'TURN RIGHT',
                                              (245, 158, 11), next_turn['dist'])
                    else:
                        instruction_state = ('เลี้ยวซ้าย', 'TURN LEFT',
                                              (245, 158, 11), next_turn['dist'])
                else:
                    instruction_state = ('ตรงไป', 'GO STRAIGHT',
                                         (16, 185, 129), None)
            inliers = int(result.get('num_inliers', 0) or 0)
            rerr = result.get('median_reproj_error')
            size = (frame.shape[1], frame.shape[0])

            raw_pay_a, reason_a = ar_service.build_ar_world_debug(
                loc, FLOOR, result.get('pose'), x, y, pc, inliers, size, rerr)
            raw_pay_b, reason_b = build_ar_world_v2(
                loc, FLOOR, result.get('pose'), x, y, pc, inliers, size, rerr,
                stabilizer=stabilizer)

            # Jitter probe: same fixed world point through the raw pose (what
            # ships) and through the stabilized pose (what v2 uses).
            pose = result.get('pose')
            if pose and pose.get('R') is not None and pc:
                P = probe_point(proj, pc)
                K = np.asarray(loc.K, float)
                Rr = np.asarray(pose['R'], float)
                tr = np.asarray(pose['t'], float).reshape(3)
                probe_raw.append(project_one(P, Rr, tr, K))
                if raw_pay_b is not None:
                    probe_smooth.append(project_one(P, raw_pay_b['R'], raw_pay_b['t'], K))
                else:
                    probe_smooth.append(None)
            else:
                probe_raw.append(None)
                probe_smooth.append(None)
        else:
            probe_raw.append(None)
            probe_smooth.append(None)

        pay_a, held_a, age_a = hold_a.resolve(raw_pay_a, ts)
        pay_b, held_b, age_b = hold_b.resolve(raw_pay_b, ts)
        shown_reason_a = f'hold_{reason_a}' if held_a else reason_a
        shown_reason_b = f'hold_{reason_b}' if held_b else reason_b
        render_a = args.pane in ('both', 'left')
        render_b = args.pane in ('both', 'right')
        pane_a = render_shipping(frame, pay_a) if render_a else None
        pane_b = render_v2(frame, pay_b) if render_b else None
        if not arrived:
            pin_source = pay_b or pay_a
            if pin_source is not None:
                pin_payload = pin_filter.update(pin_source)
        arrival_pose_fresh = False
        if arrived:
            arrival_pose = result.get('pose') if result else None
            arrival_fallback = None
            if arrival_pose and arrival_pose.get('R') is not None and arrival_pose.get('t') is not None:
                arrival_fallback = {'K': np.asarray(loc.K, float),
                                    'R': arrival_pose['R'], 't': arrival_pose['t']}
            # Keep the destination state as Arrived, but do not keep drawing
            # with the pose captured at arrival. A fresh pose is required so
            # turning away from the goal can hide the world-anchored marker.
            current_arrival_source = raw_pay_b or raw_pay_a or arrival_fallback
            if current_arrival_source is not None:
                pin_payload = pin_filter.update(current_arrival_source)
                arrival_pose_fresh = True
        marker = pin_payload if (not arrived or arrival_pose_fresh) else None
        near_goal = bool((arrived and arrival_pose_fresh) or (
            not arrived and
            destination_xy is not None and x is not None and
            math.hypot(x - destination_xy[0], y - destination_xy[1]) <= TARGET_PIN_RADIUS_PX
        ))
        if near_goal and destination_xy is not None and marker is not None:
            pin_visible = True
            # One pose per run is kept on disk so the marker can be restyled in
            # `preview_destination_pin.py` without paying for localization
            # again - the design iterations that produced this pin were all done
            # against this file rather than by re-running the whole walk.
            if not pose_dumped:
                np.savez(OUT_DIR / 'pin_pose.npz', K=marker['K'], R=marker['R'],
                         t=marker['t'], frame=fi, x=x, y=y,
                         destination=np.asarray(destination_xy, float),
                         arrived=int(arrived))
                cv2.imwrite(str(OUT_DIR / 'pin_pose_frame.png'), frame)
                pose_dumped = True
            # Distance left, in metres: the map-pixel gap scaled by M_PER_PX,
            # the same constant the floor projector is built on.
            remaining_m = None
            if x is not None and y is not None:
                remaining_m = math.hypot(x - destination_xy[0],
                                         y - destination_xy[1]) * M_PER_PX
            if render_a:
                pane_a = render_destination_pin(pane_a, marker, proj, destination_xy,
                                                args.arrival_label, arrived=arrived,
                                                screen_filter=pin_screen_a,
                                                distance_m=remaining_m)
            if render_b:
                pane_b = render_destination_pin(pane_b, marker, proj, destination_xy,
                                                args.arrival_label, arrived=arrived,
                                                screen_filter=pin_screen_b,
                                                distance_m=remaining_m)
        n_a = len(pay_a['chevrons']) if pay_a else 0
        n_b = len(pay_b['carets']) if pay_b else 0
        visible_a = int(pay_a is not None)
        visible_b = int(pay_b is not None)
        map_pose_visible = int(
            map_position is not None and map_last_fix_ts is not None and
            source_ts - map_last_fix_ts <= hold_gap_s
        )
        popup_position = map_position if map_pose_visible else None

        reasons_a[shown_reason_a] = reasons_a.get(shown_reason_a, 0) + 1
        reasons_b[shown_reason_b] = reasons_b.get(shown_reason_b, 0) + 1
        rows.append({'frame': fi, 'source_frame': fi,
                     'output_frame': n_written,
                     't': round(source_ts, 2),
                     'source_t': round(source_ts, 3),
                     'output_t': round(output_ts, 3),
                     'x': None if x is None else round(x, 1),
                     'y': None if y is None else round(y, 1),
                     'reason_shipping': shown_reason_a,
                     'reason_shipping_raw': reason_a,
                     'held_shipping_s': None if age_a is None else round(age_a, 3),
                     'n_shipping': n_a, 'visible_shipping': visible_a,
                     'reason_v2': shown_reason_b,
                     'reason_v2_raw': reason_b,
                     'held_v2_s': None if age_b is None else round(age_b, 3),
                     'n_v2': n_b, 'visible_v2': visible_b,
                     'instruction': instruction_state[1],
                     'turn_distance_px': instruction_state[3],
                     'pin_visible': int(pin_visible),
                     'arrived': int(arrived),
                     'map_route_points': 0 if map_route is None else len(map_route),
                     'map_pose_visible': map_pose_visible,
                     'map_heading': None if map_heading is None else round(map_heading, 1)})

        if not args.native:
            scale = PANE_W / frame.shape[1]
            if render_a:
                pane_a = cv2.resize(pane_a, (PANE_W, int(frame.shape[0] * scale)))
                label(pane_a, f'SHIPPING  src f{fi}  {source_ts:.2f}s  n={n_a}', (120, 210, 255))
            if render_b:
                pane_b = cv2.resize(pane_b, (PANE_W, int(frame.shape[0] * scale)))
                label(pane_b, f'v2 floor AR  src f{fi}  {source_ts:.2f}s  n={n_b}', (180, 255, 180))
        thai, english, accent, _turn_dist = instruction_state
        if render_a:
            pane_a = render_instruction_card(pane_a, thai, english, accent, args.arrival_label)
            pane_a = render_ar_controls(pane_a, top_override=12 if args.native else None)
            pane_a = render_map_popup(
                pane_a, map_route, popup_position, map_heading,
                corner='top-right', top_override=64 if args.native else None)
        if render_b:
            pane_b = render_instruction_card(pane_b, thai, english, accent, args.arrival_label)
            pane_b = render_ar_controls(pane_b, top_override=12 if args.native else None)
            pane_b = render_map_popup(
                pane_b, map_route, popup_position, map_heading,
                corner='top-right', top_override=64 if args.native else None)
        if args.pane == 'right':
            vis = pane_b
        elif args.pane == 'left':
            vis = pane_a
        else:
            vis = np.hstack([pane_a, pane_b])

        if writer is None:
            h, w = vis.shape[:2]
            writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*'MJPG'),
                                     OUT_FPS, (w, h))
            if not writer.isOpened():
                raise SystemExit(f'cannot open video writer at {args.out}')
        writer.write(vis)
        n_written += 1
        if n_written % 25 == 0:
            print(f'  f{fi}  ({n_written} frames, {time.time() - t0:.0f}s)', flush=True)

        fi += args.step
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)

    if writer is not None:
        writer.release()
    cap.release()

    csv_path = metrics_path
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    cov_a = sum(1 for r in rows if r['reason_shipping_raw'] == 'ok')
    cov_b = sum(1 for r in rows if r['reason_v2_raw'] == 'ok')
    shown_a = sum(int(r['visible_shipping']) for r in rows)
    shown_b = sum(int(r['visible_v2']) for r in rows)
    jm_raw, j9_raw = second_difference(probe_raw)
    jm_sm, j9_sm = second_difference(probe_smooth)

    print('\n' + '=' * 64)
    print(f'frames processed      : {total}  ({n_written} written)')
    print(f'coverage shipping     : {cov_a}/{total} = {100.0 * cov_a / total:.1f}%')
    print(f'coverage v2           : {cov_b}/{total} = {100.0 * cov_b / total:.1f}%')
    print(f'visible incl. hold    : shipping {shown_a}/{total} = {100.0 * shown_a / total:.1f}%')
    print(f'visible incl. hold    : v2      {shown_b}/{total} = {100.0 * shown_b / total:.1f}%')
    print(f'arrows/frame shipping : {np.mean([r["n_shipping"] for r in rows]):.2f}')
    print(f'arrows/frame v2       : {np.mean([r["n_v2"] for r in rows]):.2f}')
    print(f'probe jitter raw pose : median {jm_raw:.1f} px   p90 {j9_raw:.1f} px')
    print(f'probe jitter v2 pose  : median {jm_sm:.1f} px   p90 {j9_sm:.1f} px')
    print(f'time mapping           : output 0.00s = source frame {args.start} ({args.start / FPS:.3f}s)')
    print(f'map popup pose frames  : {sum(int(r["map_pose_visible"]) for r in rows)}/{total}')
    print(f'gates shipping        : {dict(sorted(reasons_a.items(), key=lambda kv: -kv[1]))}')
    print(f'gates v2              : {dict(sorted(reasons_b.items(), key=lambda kv: -kv[1]))}')
    print(f'video                 : {args.out}')
    print(f'metrics               : {csv_path}')
    print('=' * 64)


if __name__ == '__main__':
    main()
