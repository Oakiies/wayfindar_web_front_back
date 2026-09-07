"""PoC: a floor-glued AR arrow trail (v2), built to fix three complaints about
the shipping overlay.

Everything here is a candidate, not production code — it imports the validated
geometry (core.ar_geometry) and anchor layout (services.ar_service) rather than
re-deriving them, so only the parts under test differ from what ships.

What v2 changes and why
-----------------------
1. "It floats, it doesn't sit on the floor."
   The shipping overlay draws isolated carets. Isolated shapes have nothing
   touching the ground between them, so the eye reads them as hovering cards.
   v2 lays a CONTINUOUS ribbon on the floor through every station and puts the
   carets on top of it. A surface that runs unbroken from under the user's feet
   to the far end of the corridor is the single strongest ground-contact cue —
   the same trick car navigation uses.

2. "It should get bigger as I get closer."
   It already is a fixed size in metres, so projection does grow it — but
   _depth_alpha fades an arrow to zero below 3.4 m and it is fully gone by the
   time it would look big. The arrow is therefore never seen at the size that
   would sell the effect. v2 holds full opacity right down to PASS_UNDER_M and
   lets the frame edge do the clipping, which is what walking over a floor
   marking actually looks like.

3. "The AR swings around."
   Every frame's overlay is registered with that frame's raw PnP pose, so pose
   noise moves the whole world. v2 runs the AR pose through a small EMA with an
   outlier hold (PoseStabilizer): the trail is nailed to the route, so residual
   jitter is pose jitter and nothing else.
"""
import math

import cv2
import numpy as np

from app.core.ar_geometry import FloorProjector, to_camera
from app.services.ar_service import (
    chevron_anchors,
    get_projector,
    CHEVRON_SPACING_PX,
    MIN_INLIERS,
    MAX_REPROJ_ERROR_PX,
    _first_visible_index,
    _readable_on_screen,
    thin_far_anchors,
)

# ── Sizes, all in METRES (converted through the map's measured scale) ─────────

# The ribbon is the ground-contact cue, so it has to look like a painted lane:
# narrower than the corridor (~2 m) but wide enough to read as a surface.
RIBBON_HALF_WIDTH_M = 0.20
# Carets sit on the ribbon and must stay narrower than it or they read as a
# separate object floating above rather than paint applied to it.
CARET_HALF_WIDTH_M = 0.42
CARET_LENGTH_M = 1.45

# Depth band. Full strength until the marking is about to pass under the phone;
# the frame edge, not an alpha ramp, is what removes it from view.
PASS_UNDER_M = 0.9
PASS_UNDER_FULL_M = 1.3
# Keep the floor lane visible farther ahead; this extends route coverage rather
# than increasing caret density.
FADE_FAR_M = 30.0
FADE_FAR_SPAN_M = 12.0
# POC37 never exposed more than six readable floor carets in this route. Keep
# the same visual density after the around-turn escape hatch reveals the
# post-corner stations; the ribbon still communicates the complete route.
MAX_VISIBLE_CARETS = 6

# How finely the ribbon is subdivided, in floor-plan px. The floor plane is
# straight in world space, so this only matters where the route bends: coarse
# segments would cut the corner and lift the ribbon off the walkway.
RIBBON_STEP_PX = 3.0

# Colours (BGR) — one hue, three values, so the trail reads as a single surface
# lit from the far end rather than as a pile of separate widgets.
RIBBON_COLOR = (250, 180, 60)
CARET_COLOR = (255, 236, 180)
EDGE_COLOR = (150, 90, 10)


class PoseStabilizer:
    """EMA on the AR camera pose, with a hold for implausible jumps.

    The map position is already smoothed, but the AR pose is not: R and t come
    straight from PnP, and PnP noise rotates the entire world under the overlay.
    A degree of yaw error swings a marking 8 m out by ~14 cm, which is exactly
    the "wobble" that makes the trail feel unglued.

    Position is averaged in world units; rotation is averaged as a rotation
    vector relative to the running estimate, which is stable for the small
    frame-to-frame deltas seen here and avoids a quaternion dependency.
    """

    def __init__(self, alpha=0.35, max_jump_m=1.2, max_turn_deg=25.0,
                 metres_per_unit=1.0, turn_follow_deg=2.0,
                 turn_alpha=0.82):
        self.alpha = float(alpha)
        self.max_jump = float(max_jump_m) / max(metres_per_unit, 1e-9)
        self.max_turn = math.radians(float(max_turn_deg))
        self.turn_follow = math.radians(float(turn_follow_deg))
        self.turn_alpha = min(1.0, max(self.alpha, float(turn_alpha)))
        self.R = None
        self.C = None          # camera centre in world units
        self.held = 0
        # Caret visibility is evaluated against a moving camera frustum. Near
        # a corner, one station can cross that boundary for a single update and
        # then come back. Keep the previous set long enough to avoid a visible
        # one-caret blink, and reveal a large newly-visible group gradually.
        self.last_carets = None
        self.last_alphas = None
        self.caret_hold_updates = 0

    def update(self, R, t):
        """Feed a raw pose; get back the smoothed (R, t). Never returns None."""
        R = np.asarray(R, float)
        t = np.asarray(t, float).reshape(3)
        C = -R.T @ t

        if self.R is None:
            self.R, self.C = R.copy(), C.copy()
            return self.R, -self.R @ self.C

        # An implausible step is far more likely to be a bad PnP solution than a
        # real movement at walking pace, so hold the last good pose instead of
        # snapping the world to it.
        step = float(np.linalg.norm(C - self.C))
        turn = float(np.linalg.norm(cv2.Rodrigues(R @ self.R.T)[0]))
        if step > self.max_jump or turn > self.max_turn:
            self.held += 1
            if self.held < 4:                     # a sustained jump is real
                return self.R, -self.R @ self.C
        self.held = 0

        # A fixed low EMA is stable on a straight corridor but visibly lags a
        # real phone turn. Once the measured rotation is larger than normal
        # PnP noise, follow the turn faster so the route corner stays in view.
        a_pos = self.alpha
        a_rot = self.turn_alpha if turn > self.turn_follow else self.alpha
        self.C = (1.0 - a_pos) * self.C + a_pos * C
        delta = cv2.Rodrigues(R @ self.R.T)[0].reshape(3) * a_rot
        self.R = cv2.Rodrigues(delta)[0] @ self.R
        # Re-orthonormalise: repeated small products drift off SO(3).
        u, _, vt = np.linalg.svd(self.R)
        self.R = u @ vt
        return self.R, -self.R @ self.C


def _resample(anchors, step_px):
    """Densify the station polyline so the ribbon follows a bend properly."""
    if len(anchors) < 2:
        return list(anchors)
    out = [anchors[0]]
    for a, b in zip(anchors, anchors[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(d / step_px))
        for k in range(1, n + 1):
            f = k / n
            out.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
    return out


def _tangent(pts, i):
    n = len(pts)
    a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1.0
    return dx / L, dy / L


# A ribbon sample nearer than this is at or behind the phone. Unlike a caret,
# which is one small quad that can simply be dropped, the ribbon is ONE polygon:
# a single vertex with negative depth projects to a wild coordinate and drags
# the whole fill across the screen (seen as a blue wash over half the frame).
# So the centre line is clipped in 3D first, and only then given width.
RIBBON_NEAR_M = 1.1


def _centre_frames(proj, centre_pts):
    """Per-sample (floor point, right vector) in world space."""
    frames = []
    for i, (px, py) in enumerate(centre_pts):
        dx, dy = _tangent(centre_pts, i)
        frames.append((proj.floor_point(px, py), proj.direction(px, py, -dy, dx)))
    return frames


def _clip_frames_by_depth(frames, R, t, near_units):
    """Drop the stretch of ribbon at or behind the camera, splicing the crossing.

    Interpolating the crossing point (rather than just dropping samples) keeps
    the ribbon's near end a straight edge across the walkway instead of letting
    it start at whatever sample happened to survive, which would make its start
    jump around by a sample spacing every frame.
    """
    if len(frames) < 2:
        return []
    depths = [float(to_camera(P, R, t)[0, 2]) for P, _ in frames]
    out = []
    for i in range(len(frames)):
        d = depths[i]
        if d >= near_units:
            if not out and i > 0:
                # splice a point exactly on the near plane
                d0, (P0, r0) = depths[i - 1], frames[i - 1]
                P1, r1 = frames[i]
                span = (d - d0) or 1.0
                f = (near_units - d0) / span
                f = min(max(f, 0.0), 1.0)
                out.append((P0 + f * (P1 - P0), r0 + f * (r1 - r0)))
            out.append(frames[i])
    return out


def ribbon_polygon(proj, centre_pts, R, t, half_width_m=RIBBON_HALF_WIDTH_M):
    """One closed world-space strip lying on the floor along the route.

    Built as left edge forward + right edge back so it stays a simple polygon.
    The width is applied through FloorProjector.direction at each sample, so it
    inherits H_matrix's rotation the same way the carets do.
    """
    if len(centre_pts) < 2:
        return None
    frames = _clip_frames_by_depth(_centre_frames(proj, centre_pts), R, t,
                                   proj.m(RIBBON_NEAR_M))
    if len(frames) < 2:
        return None
    s = proj.m(half_width_m)
    left = [P - s * rv for P, rv in frames]
    right = [P + s * rv for P, rv in frames]

    # Emitted as per-segment quads, not one polygon, so each piece can carry its
    # own depth alpha. A single filled strip has to end on a hard edge, and a
    # painted lane that stops dead a few metres out looks like a rug, not like
    # floor markings receding into the distance.
    quads = []
    for i in range(len(frames) - 1):
        quad = np.array([left[i], left[i + 1], right[i + 1], right[i]], float)
        depth = float(to_camera(frames[i][0], R, t)[0, 2])
        quads.append((quad, depth))
    edges = (np.array(left, float), np.array(right, float))
    return quads, edges


def caret_polygon(proj, px, py, dx, dy,
                  half_width_m=CARET_HALF_WIDTH_M, length_m=CARET_LENGTH_M):
    """A chevron lying on the ribbon at one station."""
    # Reuse the validated shipping geometry, including its rounded corners.
    # The old POC rebuilt a sharper, shorter caret here, which is why the
    # candidate looked more like a HUD marker than the original AR paint.
    if (half_width_m == CARET_HALF_WIDTH_M and
            length_m == CARET_LENGTH_M):
        return proj.chevron_polygon(px, py, dx, dy)
    origin = proj.floor_point(px, py)
    fwd = proj.direction(px, py, dx, dy)
    right = proj.direction(px, py, -dy, dx)
    s = proj.m(half_width_m)
    L = proj.m(length_m)
    rise = 0.55 * L
    thick = 0.30 * L
    outline = [
        (-s, 0.0), (0.0, rise), (s, 0.0),
        (s, thick), (0.0, rise + thick), (-s, thick),
    ]
    return np.array([origin + r * right + f * fwd for r, f in outline], float)


def depth_alpha(depth_m):
    """Opacity by depth. Unlike the shipping ramp this stays full up close."""
    if depth_m <= PASS_UNDER_M:
        return 0.0
    if depth_m < PASS_UNDER_FULL_M:
        return round((depth_m - PASS_UNDER_M) / (PASS_UNDER_FULL_M - PASS_UNDER_M), 3)
    if depth_m > FADE_FAR_M:
        return round(max(0.0, 1.0 - (depth_m - FADE_FAR_M) / FADE_FAR_SPAN_M), 3)
    return 1.0


def _project(points_world, R, t, K):
    rvec, _ = cv2.Rodrigues(np.asarray(R, float))
    uv, _ = cv2.projectPoints(np.asarray(points_world, float), rvec,
                              np.asarray(t, float).reshape(3), np.asarray(K, float),
                              np.zeros(4))
    return uv.reshape(-1, 2)


def _on_screen_area(uv, img_w, img_h):
    """Rough share of the polygon's bounding box that lands inside the frame.

    The shipping check requires the CENTROID to be inside the image, which
    throws away exactly the near markings v2 wants to keep: the one being walked
    over is half below the bottom edge, and that is what passing over a floor
    marking looks like. Judging by overlap keeps it until it is genuinely gone.
    """
    x0, y0 = uv[:, 0].min(), uv[:, 1].min()
    x1, y1 = uv[:, 0].max(), uv[:, 1].max()
    ix = max(0.0, min(x1, img_w) - max(x0, 0.0))
    iy = max(0.0, min(y1, img_h) - max(y0, 0.0))
    box = max((x1 - x0) * (y1 - y0), 1e-6)
    return (ix * iy) / box


def build_ar_world_v2(localizer, floor_id, pose, x, y, path_coords, num_inliers,
                      image_size=None, reproj_error=None, stabilizer=None):
    """v2 payload: {'ribbon': poly, 'carets': [...], 'alphas': [...], K/R/t}.

    Same gates as the shipping builder for pose quality, so the comparison is
    about the geometry and not about accepting worse poses.
    """
    if not pose or pose.get('R') is None or pose.get('t') is None:
        return None, 'no_pose'
    if (num_inliers or 0) < MIN_INLIERS:
        return None, 'low_inliers'
    if reproj_error is not None and reproj_error > MAX_REPROJ_ERROR_PX:
        return None, 'high_reproj_error'

    proj = get_projector(floor_id, localizer)
    if proj is None:
        return None, 'no_projector'
    K = getattr(localizer, 'K', None)
    if K is None:
        return None, 'no_K'
    K = np.asarray(K, float)

    R = np.asarray(pose['R'], float)
    t = np.asarray(pose['t'], float).reshape(3)
    if stabilizer is not None:
        R, t = stabilizer.update(R, t)

    if image_size:
        img_w, img_h = int(image_size[0]), int(image_size[1])
    else:
        img_w, img_h = int(round(K[0, 2] * 2)), int(round(K[1, 2] * 2))

    try:
        cam_px = proj.camera_floor_px(R, t)
        ax, ay = float(cam_px[0]), float(cam_px[1])
    except Exception:  # noqa: BLE001
        ax, ay = x, y

    anchors = chevron_anchors(ax, ay, path_coords)
    if len(anchors) < 2:
        anchors = chevron_anchors(ax, ay, path_coords, clip_at_corner=False)
    if len(anchors) < 2:
        return None, 'no_anchors'

    # Match the shipping turn escape hatch: when the clipped route has no
    # anchor on the visible floor, allow stations around the bend rather than
    # returning a ribbon-only payload. This is the case where the original
    # still shows a turn arrow while v2 previously showed nothing.
    if _first_visible_index(anchors, proj, R, t, K, img_w, img_h) is None:
        around_turn = chevron_anchors(ax, ay, path_coords, clip_at_corner=False)
        if len(around_turn) >= 2:
            anchors = around_turn
    thinned_anchors = thin_far_anchors(anchors, proj, R, t)
    # A ribbon needs two stations to define its first segment. Near a turn or
    # at the edge of the camera, far-field thinning can legitimately leave only
    # one drawable station; keep the original pair in that edge case instead
    # of indexing anchors[1] and failing the whole localization response.
    if len(thinned_anchors) >= 2:
        anchors = thinned_anchors

    # ``chevron_anchors`` already clips with the shipping corner policy and
    # keeps CORNER_OVERSHOOT stations beyond the bend. Do not trim again here:
    # the old v2 second trim removed exactly those post-corner stations, so the
    # route looked straight and then became blank at the turn.

    # The ribbon starts at the walker's own feet, not at the first station:
    # a lane that begins several metres out floats exactly the way the isolated
    # carets did. Extending it back under the camera gives the trail somewhere
    # to be anchored that the user can see is on their floor. (The stretch that
    # ends up behind the phone is clipped in 3D inside ribbon_polygon.)
    # Extend BACKWARDS along the route's own direction rather than splicing in
    # the raw camera point. chevron_anchors has already shifted the stations
    # sideways so the trail passes through the walker; joining to the unshifted
    # camera position undoes that for the first segment and puts a visible kink
    # in the lane right where the eye is most sensitive to it.
    a0, a1 = anchors[0], anchors[1]
    bx, by = a0[0] - a1[0], a0[1] - a1[1]
    bl = math.hypot(bx, by) or 1.0
    back = [(a0[0] + bx / bl * CHEVRON_SPACING_PX * k,
             a0[1] + by / bl * CHEVRON_SPACING_PX * k) for k in (2.0, 1.0)]
    centre = _resample(back + list(anchors), RIBBON_STEP_PX)

    built = ribbon_polygon(proj, centre, R, t)
    if built is None:
        return None, 'no_ribbon'
    ribbon_quads, ribbon_edges = built

    carets, alphas = [], []
    rvec, _ = cv2.Rodrigues(R)
    for i, (px, py) in enumerate(anchors):
        dx, dy = _tangent(anchors, i)
        depth = float(to_camera(proj.floor_point(px, py), R, t)[0, 2])
        if depth <= 0:
            continue
        depth_m = depth * proj.metres_per_unit
        a = depth_alpha(depth_m)
        if a <= 0.01:
            continue
        poly = caret_polygon(proj, px, py, dx, dy)
        if np.any(to_camera(poly, R, t)[:, 2] <= 0.0):
            continue
        # Match the shipping visibility rule here. The previous bounding-box
        # overlap gate rejected a whole chevron when a turn put part of it near
        # the frame edge, even though its centroid and readable dimensions were
        # still on screen. That is why v2 had ribbon but no turn arrows.
        if not _readable_on_screen(poly, rvec, t, K, img_w, img_h):
            continue
        carets.append(poly)
        alphas.append(a)

    # Match POC37's visual density. The route/ribbon is not shortened; only the
    # farthest repeated caret stations are omitted from the current frame.
    if len(carets) > MAX_VISIBLE_CARETS:
        carets = carets[:MAX_VISIBLE_CARETS]
        alphas = alphas[:MAX_VISIBLE_CARETS]

    # If smoothing lags a real turn far enough that every caret leaves the
    # image, retry this frame with the raw registered pose. The raw pose is the
    # same pose used by shipping AR and is preferable to showing a floor lane
    # with no direction marker. Normal frames still use the stabilized pose.
    if not carets and stabilizer is not None:
        return build_ar_world_v2(
            localizer, floor_id, pose, x, y, path_coords, num_inliers,
            image_size, reproj_error, stabilizer=None)

    if stabilizer is not None and stabilizer.last_carets is not None:
        previous_carets = stabilizer.last_carets
        previous_alphas = stabilizer.last_alphas or []
        previous_count = len(previous_carets)
        current_count = len(carets)

        if previous_count > 0 and current_count < previous_count:
            # A station leaving the frustum is not a reason to remove the
            # complete tail immediately. Reuse the previous registered set and
            # retire only one station per update; this is the same temporal
            # continuity users see in the stable PoC during a turn.
            limit = max(current_count, previous_count - 1)
            carets = [np.asarray(poly, float).copy()
                      for poly in previous_carets[:limit]]
            alphas = [float(value) for value in previous_alphas[:limit]]
        elif current_count > previous_count + 1 and previous_count > 0:
            # The around-turn escape hatch can expose several post-corner
            # stations at once. Reveal only the next station per update so the
            # lane does not pop from one caret to a full group.
            limit = previous_count + 1
            carets = carets[:limit]
            alphas = alphas[:limit]

    if stabilizer is not None:
        stabilizer.last_carets = [np.asarray(poly, float).copy() for poly in carets]
        stabilizer.last_alphas = [float(value) for value in alphas]

    # A frame with the lane but no caret is still useful guidance — the ribbon
    # alone says "the walkway goes this way", which is exactly the moment
    # (mid-turn, marking passing underfoot) the shipping overlay goes blank.
    # Only a frame with neither is worth suppressing.
    if not carets and len(ribbon_quads) < 2:
        return None, 'nothing_visible'

    return {
        'K': K, 'R': R, 't': t, 'imgWH': (img_w, img_h),
        'metres_per_unit': proj.metres_per_unit,
        # The live client uses these two floor-plane basis vectors to carry
        # the PDR delta into the same SLAM world as this AR payload.
        'pdr_anchor_map': (float(ax), float(ay)),
        'pdr_map_x_axis_world': (
            proj.plane_point(float(ax) + 1.0, float(ay)) - proj.plane_point(float(ax), float(ay))
        ).tolist(),
        'pdr_map_y_axis_world': (
            proj.plane_point(float(ax), float(ay) + 1.0) - proj.plane_point(float(ax), float(ay))
        ).tolist(),
        'ribbon_quads': ribbon_quads, 'ribbon_edges': ribbon_edges,
        'carets': carets, 'alphas': alphas,
        'anchors': anchors,
    }, 'ok'


def render_v2(frame, payload):
    """Draw a v2 payload. Mirrors what a three.js layer would do."""
    out = frame.copy()
    if not payload:
        return out
    K, R, t = payload['K'], payload['R'], payload['t']
    img_h, img_w = out.shape[:2]

    # Ribbon first, under everything, at low alpha: it is the surface, not the
    # message. Each quad fades with its own depth so the lane arrives out of the
    # distance and passes under the viewer instead of ending on a hard edge.
    metres_per_unit = payload.get('metres_per_unit', 1.0)
    for quad, depth in payload['ribbon_quads']:
        # The ribbon is only a floor-contact shadow. Keep the original
        # chevrons visually dominant so the route does not become a blue lane.
        a = depth_alpha(depth * metres_per_unit) * 0.14
        if a <= 0.01:
            continue
        uv = _project(quad, R, t, K)
        if not np.all(np.isfinite(uv)):
            continue
        layer = out.copy()
        cv2.fillPoly(layer, [uv.astype(np.int32)], RIBBON_COLOR)
        out = cv2.addWeighted(layer, a, out, 1 - a, 0)

    for edge in payload['ribbon_edges']:
        uv = _project(edge, R, t, K)
        if not np.all(np.isfinite(uv)):
            continue
        layer = out.copy()
        cv2.polylines(layer, [uv.astype(np.int32)], False, EDGE_COLOR, 2, cv2.LINE_AA)
        out = cv2.addWeighted(layer, 0.22, out, 0.78, 0)

    for poly_world, alpha in zip(payload['carets'], payload['alphas']):
        uv = _project(poly_world, R, t, K)
        if not np.all(np.isfinite(uv)):
            continue
        poly = uv.astype(np.int32)
        layer = out.copy()
        cv2.fillPoly(layer, [poly], CARET_COLOR)
        cv2.polylines(layer, [poly], True, EDGE_COLOR, 2, cv2.LINE_AA)
        out = cv2.addWeighted(layer, min(1.0, alpha * 0.92), out, 1 - min(1.0, alpha * 0.92), 0)
    return out
