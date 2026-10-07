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
from app.core import navigation as nav
from app.services.ar_service import (
    chevron_anchors,
    get_projector,
    CHEVRON_SPACING_PX,
    MIN_INLIERS,
    MAX_REPROJ_ERROR_PX,
    _first_visible_index,
    _readable_on_screen,
    _arc_table,
    _user_arc,
    _point_at_arc,
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

# A shallow corridor transition is not a turn instruction. The navigation
# module measures the route bend ahead from the current on-path projection;
# keep the repeated directional caret only for a real manoeuvre. These bounds
# are deliberately wider than the observed 11–21 degree M21 transition, while
# still leaving a normal 90-degree junction as a turn cue.
GENTLE_BEND_MIN_DEG = 7.0
GENTLE_BEND_MAX_DEG = 30.0
# A chamfer is usually represented by two nearby graph vertices: enter the
# diagonal, then leave it. Keep one semantic envelope around that complete
# cluster so guidance does not flip back to directional in the straight-looking
# middle of the chamfer or immediately after its exit.
GENTLE_BEND_CLUSTER_GAP_PX = 75.0
# Padding kept short: it exists to stop the mode flipping back to directional
# right at a chamfer's own two vertices, not to silence carets for metres of
# ordinary straight corridor on either side of it (the original 45px each way
# padded a single ~64px jog out to a ~154px/28m window - see
# GENTLE_BEND_CLUSTER_TOTAL_MAX_DEG below for the matching fix on cluster size).
GENTLE_BEND_APPROACH_PX = 20.0
GENTLE_BEND_DEPART_PX = 20.0
HARD_TURN_MIN_DEG = 45.0
# Total unsigned turning a cluster of shallow kinks may absorb before it is
# treated as a real manoeuvre instead of one continuous gentle curve. Same
# scale as GENTLE_BEND_MAX_DEG (a single kink's own cap) since a two-kink jog
# whose parts sum past it asks the walker for just as much turning.
GENTLE_BEND_CLUSTER_TOTAL_MAX_DEG = 30.0

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
                 turn_alpha=0.82, expected_interval_s=1.0,
                 max_speed_mps=2.5, jump_margin_m=0.75,
                 max_turn_rate_dps=35.0, turn_margin_deg=12.0):
        self.alpha = float(alpha)
        # Localization is sampled, not continuous. A fixed 1m gate rejects
        # perfectly normal walking motion when the next visual fix arrives
        # 1–1.5s later. Expand the gate from the expected sampling interval,
        # while keeping the explicit minimum as a safety floor.
        interval = max(0.25, float(expected_interval_s))
        jump_limit_m = max(
            float(max_jump_m),
            float(max_speed_mps) * interval + float(jump_margin_m),
        )
        turn_limit_deg = max(
            float(max_turn_deg),
            float(max_turn_rate_dps) * interval + float(turn_margin_deg),
        )
        self.max_jump_m = jump_limit_m
        self.max_jump = jump_limit_m / max(metres_per_unit, 1e-9)
        self.max_turn = math.radians(turn_limit_deg)
        self.turn_follow = math.radians(float(turn_follow_deg))
        self.turn_alpha = min(1.0, max(self.alpha, float(turn_alpha)))
        # The jump/turn gates above are sized for ONE step of `interval`
        # seconds. A real tracking dropout (motion blur through a fast phone
        # turn is the common cause) can leave a gap several times longer -
        # found on the M21 walk, where a ~2s dropout produced a gate-rejected
        # pose that held the PRE-dropout rotation over POST-dropout video for
        # up to 3 more updates (see DIAGNOSIS_ar_m21_walk.md). That reads as
        # the AR world "floating"/tilted right when tracking resumes - it is
        # a genuinely different pose being judged against a stale reference,
        # not noise. Past this many seconds since the last update, skip the
        # gate and reacquire immediately instead of holding a stale pose.
        self.reacquire_gap_s = interval * 3.0
        self.last_timestamp = None
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

    def update(self, R, t, timestamp=None):
        """Feed a raw pose; get back the smoothed (R, t). Never returns None.

        `timestamp` is optional only for backward compatibility with other
        callers of this class (e.g. render_poc.py's destination-pin filter,
        which does not currently track it) - passing it is what lets the
        gate below recognise a real dropout instead of gating the pose that
        follows it.
        """
        R = np.asarray(R, float)
        t = np.asarray(t, float).reshape(3)
        C = -R.T @ t

        if self.R is None:
            self.R, self.C = R.copy(), C.copy()
            self.last_timestamp = timestamp
            return self.R, -self.R @ self.C

        if timestamp is not None and self.last_timestamp is not None:
            dt = float(timestamp) - float(self.last_timestamp)
            if dt > self.reacquire_gap_s:
                self.R, self.C = R.copy(), C.copy()
                self.held = 0
                self.last_timestamp = timestamp
                return self.R, -self.R @ self.C
        self.last_timestamp = timestamp

        # An implausible step is far more likely to be a bad PnP solution than a
        # real movement at walking pace, so hold the last good pose instead of
        # snapping the world to it.
        step = float(np.linalg.norm(C - self.C))
        turn = float(np.linalg.norm(cv2.Rodrigues(R @ self.R.T)[0]))
        if step > self.max_jump or turn > self.max_turn:
            self.held += 1
            if self.held < 4:                     # a sustained jump is real
                # Keep the complete previous pose together. Mixing the old
                # rotation with the new camera centre creates a synthetic
                # pose that can throw the floor overlay off the route.
                return self.R, -self.R @ self.C
        self.held = 0

        # A fixed low EMA is stable on a straight corridor but visibly lags a
        # real phone turn. Once the measured rotation is larger than normal
        # PnP noise, follow the turn faster so the route corner stays in view.
        #
        # a_pos and a_rot used to speed up independently: a_rot alone jumped to
        # turn_alpha while a_pos stayed at the slow constant. For a few updates
        # during a fast turn that left R already facing close to the new
        # heading while C (the smoothed camera CENTRE) was still lagging in
        # the pre-turn position - a self-INCONSISTENT pose, since t = -R@C
        # combines them. The ribbon itself stayed perfectly smooth in world
        # space (verified directly), but projecting it through that
        # inconsistent pose put near-camera anchors at extreme camera-space
        # lateral offsets relative to their depth, which a pinhole projection
        # sends to wild screen coordinates - the streaks a user reported
        # seeing right at a turn (~33s into the m21 clip). Coupling a_pos to
        # the same turn condition keeps R and C moving at the same rate, so
        # the pose stays self-consistent throughout the blend.
        a_pos = self.turn_alpha if turn > self.turn_follow else self.alpha
        a_rot = a_pos
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


def _route_progress_and_bends(x, y, path_coords):
    """Return user arc progress and route bend events on a cleaned polyline."""
    if not path_coords or len(path_coords) < 3:
        return 0.0, []
    path = nav.simplify_collinear(nav._strip_start_stub(path_coords))
    if len(path) < 3:
        return 0.0, []

    segment_index, projection = nav._nearest_on_path(x, y, path)
    cumulative = [0.0]
    for start, end in zip(path, path[1:]):
        cumulative.append(cumulative[-1] + math.hypot(
            end[0] - start[0], end[1] - start[1]))
    progress = cumulative[segment_index] + math.hypot(
        projection[0] - path[segment_index][0],
        projection[1] - path[segment_index][1],
    )

    bends = []
    for index in range(1, len(path) - 1):
        a, b, c = path[index - 1], path[index], path[index + 1]
        incoming = math.atan2(b[1] - a[1], b[0] - a[0])
        outgoing = math.atan2(c[1] - b[1], c[0] - b[0])
        angle = math.degrees((outgoing - incoming + math.pi) % (2.0 * math.pi) - math.pi)
        if abs(angle) >= GENTLE_BEND_MIN_DEG:
            bends.append({'progress': cumulative[index], 'angle': angle})
    return progress, bends


def route_guidance_mode(x, y, path_coords):
    """Classify a local route bend for rendering, not for route planning.

    ``gentle_corridor`` means the route is continuously changing direction,
    but is not asking the user to execute a discrete left/right turn. Keeping
    this separate from ``next_turn_info`` prevents a shallow chamfer from
    being represented by a stack of turn-looking carets.
    """
    try:
        local_bend = abs(float(nav.path_turn_angle(x, y, path_coords)))
        progress, bends = _route_progress_and_bends(x, y, path_coords)
    except (TypeError, ValueError, AttributeError, IndexError):
        return 'directional', 0.0

    # A real manoeuvre always wins while it is locally relevant. This avoids
    # suppressing the caret where a shallow map chamfer sits close to a real
    # junction.
    for event in bends:
        distance = event['progress'] - progress
        if (abs(event['angle']) >= HARD_TURN_MIN_DEG and
                -GENTLE_BEND_DEPART_PX <= distance <= GENTLE_BEND_APPROACH_PX):
            return 'directional', local_bend

    shallow = [event for event in bends
               if GENTLE_BEND_MIN_DEG <= abs(event['angle']) <= GENTLE_BEND_MAX_DEG]
    clusters = []
    for event in shallow:
        if (clusters and
                event['progress'] - clusters[-1][-1]['progress'] <= GENTLE_BEND_CLUSTER_GAP_PX):
            clusters[-1].append(event)
        else:
            clusters.append([event])
    for cluster in clusters:
        # Two (or more) shallow kinks close together are usually a single
        # S-jog: enter the offset, leave it. Each kink alone is mild, but a
        # walker still has to execute the FULL turning effort of the cluster.
        # Measured on the M21 route this method was tuned against: two 23 deg
        # kinks 64px apart (an offset corridor, not a gentle curve) summed to
        # 46 deg and merged into one window - every sample taken while walking
        # that jog landed inside it, so carets were cleared for the entire
        # ~28s transit (see poc_ar_arrow/out/DIAGNOSIS_ar_m21_walk.md). Capping
        # the cluster's TOTAL unsigned turn — not just its largest single kink
        # — routes a real multi-kink jog back to 'directional' while leaving a
        # true single chamfer (one kink, nothing nearby to cluster with)
        # governed by GENTLE_BEND_MAX_DEG as before.
        cluster_total = sum(abs(event['angle']) for event in cluster)
        if cluster_total > GENTLE_BEND_CLUSTER_TOTAL_MAX_DEG:
            continue
        start = cluster[0]['progress'] - GENTLE_BEND_APPROACH_PX
        end = cluster[-1]['progress'] + GENTLE_BEND_DEPART_PX
        if start <= progress <= end:
            cluster_bend = max(abs(event['angle']) for event in cluster)
            return 'gentle_corridor', max(local_bend, cluster_bend)
    return 'directional', local_bend


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


class RouteProgressTracker:
    """Monotonic ratchet on how far along the route the walker has gotten.

    ``chevron_anchors`` (app/services/ar_service.py) decides which stations
    are "ahead" - and therefore still worth drawing - from a single arc-length
    number: how far along path_coords the walker's position projects to. That
    number has to come from the raw, un-lagged camera-floor position (not the
    smoothed map dot) or newly-visible stations would keep landing behind the
    actual camera and getting clipped, which is why build_ar_world_v2 feeds it
    ax/ay - but the raw position is exactly what DIAGNOSIS_ar_m21_walk.md
    measured jumping 2.5-9.7 m between consecutive updates in low-inlier
    stretches. Recomputing progress fresh from that every frame means a single
    noisy sample can walk it BACKWARD past a corner the person already turned
    - the corner (or a station just behind them) reappears as "ahead" again,
    which is the exact complaint that prompted this class: AR not respecting
    where the walker actually is, holding stale guidance after they have
    already passed a turn.

    Real forward walking cannot produce a large backward jump in route arc
    length; a real reversal (the person turned around) shows up as a
    SUSTAINED drop over several updates, not one outlier sample. So: ratchet
    forward on every update, and only accept a large backward move once it
    has persisted for `reset_after` consecutive updates in a row - one bad
    frame is absorbed, a genuine reversal still gets through in ~2 seconds at
    this update rate.

    This does not change how any position is estimated (PnP/EKF are
    untouched) - it only changes which of an already-computed position's
    readings the AR-guidance layer is willing to believe, frame to frame.
    """

    def __init__(self, allowed_backslide_px=40.0, reset_after=4):
        self.progress = None
        self.allowed_backslide_px = float(allowed_backslide_px)
        self.reset_after = int(reset_after)
        self.behind_streak = 0

    def update(self, raw_progress):
        raw_progress = float(raw_progress)
        if self.progress is None:
            self.progress = raw_progress
            self.behind_streak = 0
            return self.progress
        if raw_progress >= self.progress - self.allowed_backslide_px:
            self.progress = max(self.progress, raw_progress)
            self.behind_streak = 0
        else:
            self.behind_streak += 1
            if self.behind_streak >= self.reset_after:
                self.progress = raw_progress
                self.behind_streak = 0
        return self.progress

    def reset(self):
        self.progress = None
        self.behind_streak = 0


# A projected ribbon vertex should never land far outside the frame: every
# station is metres away on a floor plane, so its screen-space footprint is
# bounded by ordinary perspective. When it isn't - reported directly by a
# user watching this walk, right at the Intersection-1/M23_A corner (~33s
# into the m21 clip) - a quad or edge segment stretches into a thin diagonal
# streak across a large fraction of the frame instead of paint on the floor.
# The "back" extension (anchors[0]-anchors[1], a few lines above) straddling
# a sharp corner is the leading suspect, but this check is independent of the
# exact cause: it filters the PROJECTED geometry actually about to be drawn
# or sent to the frontend, the same way `_readable_on_screen` already does
# for carets. Only the offending piece is dropped - the rest of the ribbon
# for this frame is still valid geometry and still draws.
RIBBON_MAX_SPAN_FRAC = 0.6  # of image diagonal, per quad or per edge segment


def _sanitize_ribbon_quads(quads, R, t, K, img_w, img_h):
    diag_cap = RIBBON_MAX_SPAN_FRAC * math.hypot(img_w, img_h)
    out = []
    for quad, depth in quads:
        uv = _project(quad, R, t, K)
        if not np.all(np.isfinite(uv)):
            continue
        span = math.hypot(uv[:, 0].max() - uv[:, 0].min(), uv[:, 1].max() - uv[:, 1].min())
        if span > diag_cap:
            continue
        out.append((quad, depth))
    return out


def _sanitize_ribbon_edges(edges, R, t, K, img_w, img_h):
    """Split each edge polyline wherever its projection jumps too far,
    dropping only the anomalous segment and keeping valid runs as separate
    edges (the payload already carries ribbon_edges as a LIST of polylines,
    so this needs no change on the consuming side - see
    frontend-v3 ARFloorThreeOverlay.tsx's `ribbon_edges?.forEach`).
    """
    seg_cap = RIBBON_MAX_SPAN_FRAC * math.hypot(img_w, img_h)
    out = []
    for edge in edges:
        pts = np.asarray(edge, float)
        if len(pts) < 2:
            continue
        uv = _project(pts, R, t, K)
        run = [pts[0]]
        for i in range(1, len(pts)):
            bad = not np.all(np.isfinite(uv[i])) or not np.all(np.isfinite(uv[i - 1]))
            if bad or math.hypot(*(uv[i] - uv[i - 1])) > seg_cap:
                if len(run) >= 2:
                    out.append(np.array(run, float))
                run = [pts[i]]
            else:
                run.append(pts[i])
        if len(run) >= 2:
            out.append(np.array(run, float))
    return out


def build_ar_world_v2(localizer, floor_id, pose, x, y, path_coords, num_inliers,
                      image_size=None, reproj_error=None, stabilizer=None, pin_route=False,
                      timestamp=None, progress_tracker=None):
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
        R, t = stabilizer.update(R, t, timestamp=timestamp)

    if image_size:
        img_w, img_h = int(image_size[0]), int(image_size[1])
    else:
        img_w, img_h = int(round(K[0, 2] * 2)), int(round(K[1, 2] * 2))

    try:
        cam_px = proj.camera_floor_px(R, t)
        ax, ay = float(cam_px[0]), float(cam_px[1])
    except Exception:  # noqa: BLE001
        ax, ay = x, y

    # Ratchet ax/ay's arc-length progress along the route before it reaches
    # chevron_anchors, so a single noisy fix cannot un-pass a corner or
    # station the walker already walked through (see RouteProgressTracker).
    # Kept as a SEPARATE point from ax/ay: pdr_anchor_map below must stay the
    # real (unratcheted) camera-floor position, since the live client uses it
    # to anchor dead-reckoning deltas to the actual estimated pose, not to a
    # path-snapped proxy used only to decide which stations are "ahead".
    anchor_ax, anchor_ay = ax, ay
    raw_here = None
    try:
        raw_here = _user_arc(path_coords, _arc_table(path_coords), ax, ay)
    except Exception:  # noqa: BLE001 - keep rendering when a malformed route slips through
        pass
    if progress_tracker is not None:
        try:
            tracker_here = raw_here if raw_here is not None else _user_arc(path_coords, _arc_table(path_coords), ax, ay)
            ratcheted_here = progress_tracker.update(tracker_here)
            cum = _arc_table(path_coords)
            anchor_ax, anchor_ay = _point_at_arc(path_coords, cum, ratcheted_here)
        except Exception:  # noqa: BLE001 - fall back to the unratcheted position
            pass

    # Rendering geometry is registered with the camera-floor projection, but
    # navigation semantics must use the same user position shown on the
    # top-down map. Otherwise pose noise can classify a different graph segment
    # from the one the navigation UI says the user occupies.
    try:
        semantic_x, semantic_y = float(x), float(y)
        if not (math.isfinite(semantic_x) and math.isfinite(semantic_y)):
            raise ValueError("non-finite navigation position")
    except (TypeError, ValueError):
        semantic_x, semantic_y = ax, ay
    guidance_mode, local_bend_deg = route_guidance_mode(
        semantic_x, semantic_y, path_coords)

    # Route finding starts at the nearest graph node, which can be several
    # metres ahead of the camera. Before the user reaches that first route
    # segment, the renderer must show the approach from the current camera
    # position to the nearest point on the route. Otherwise the first fixed
    # station follows the direction of the route's NEXT segment and can appear
    # sideways across the image (or on a wall).
    geometry_path = path_coords
    try:
        if raw_here is not None and raw_here <= 1.0:
            nearest_i, nearest_point = nav._nearest_on_path(ax, ay, path_coords)
            gap = math.hypot(float(nearest_point[0]) - ax, float(nearest_point[1]) - ay)
            if gap > 12.0:
                approach = [(float(ax), float(ay)),
                            (float(nearest_point[0]), float(nearest_point[1]))]
                route_tail = [tuple(map(float, point)) for point in path_coords[nearest_i + 1:]]
                geometry_path = approach + [point for point in route_tail
                                            if math.hypot(point[0] - approach[-1][0],
                                                          point[1] - approach[-1][1]) > 1e-3]
                anchor_ax, anchor_ay = ax, ay
    except Exception:  # noqa: BLE001 - use the graph route if projection fails
        geometry_path = path_coords

    # A registered world route must not be translated with the latest camera
    # fix. Keep legacy recentering available for existing PoC/live callers.
    anchors = chevron_anchors(anchor_ax, anchor_ay, geometry_path, recenter=not pin_route)
    if len(anchors) < 2:
        anchors = chevron_anchors(anchor_ax, anchor_ay, geometry_path, clip_at_corner=False, recenter=not pin_route)
    if len(anchors) < 2:
        return None, 'no_anchors'

    # Match the shipping turn escape hatch: when the clipped route has no
    # anchor on the visible floor, allow stations around the bend rather than
    # returning a ribbon-only payload. This is the case where the original
    # still shows a turn arrow while v2 previously showed nothing.
    if _first_visible_index(anchors, proj, R, t, K, img_w, img_h) is None:
        around_turn = chevron_anchors(anchor_ax, anchor_ay, geometry_path, clip_at_corner=False, recenter=not pin_route)
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

    centre_frames = _centre_frames(proj, centre)
    depth_frames = _clip_frames_by_depth(centre_frames, R, t, proj.m(RIBBON_NEAR_M))
    if len(depth_frames) < 2:
        return None, (
            f'no_ribbon:centre_frames={len(centre_frames)}:'
            f'depth_frames={len(depth_frames)}:'
            f'anchors={len(anchors)}'
        )
    built = ribbon_polygon(proj, centre, R, t)
    if built is None:
        return None, (
            f'no_ribbon:centre_frames={len(centre_frames)}:'
            f'depth_frames={len(depth_frames)}:anchors={len(anchors)}'
        )
    ribbon_quads, ribbon_edges = built
    ribbon_quads = _sanitize_ribbon_quads(ribbon_quads, R, t, K, img_w, img_h)
    ribbon_edges = _sanitize_ribbon_edges(ribbon_edges, R, t, K, img_w, img_h)

    def projects_into_frame(points):
        try:
            uv = _project(points, R, t, K)
        except (TypeError, ValueError, cv2.error):
            return False
        if not np.isfinite(uv).all():
            return False
        return bool(
            np.any((uv[:, 0] >= 0) & (uv[:, 0] < img_w) &
                   (uv[:, 1] >= 0) & (uv[:, 1] < img_h))
        )

    # A payload with a valid PnP pose is not necessarily drawable: a ribbon
    # can be entirely behind/aside the camera after the route turn. Sending it
    # anyway makes the WebGL layer suppress its screen-fixed fallback while
    # painting no pixels. Keep only pieces that can reach this frame, and give
    # the caller a useful U-turn diagnostic when none remain.
    ribbon_quads = [item for item in ribbon_quads if projects_into_frame(item[0])]
    ribbon_edges = [edge for edge in ribbon_edges if projects_into_frame(edge)]

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
        poly_depth = to_camera(poly, R, t)[:, 2]
        if np.any(poly_depth <= 0.0):
            continue
        # The anchor is at the BACK of the caret (chevron_polygon's origin),
        # so a caret can extend up to CARET_LENGTH_M further toward the
        # camera than the single point depth_alpha just judged. A caret whose
        # anchor reads as comfortably far can still have its near tip well
        # inside the zone this codebase already treats as "too close to
        # render legibly" (PASS_UNDER_M) - not literally behind the camera,
        # so the check above missed it, but close enough for a pinhole
        # projection to stretch it into the lopsided, asymmetric shape a
        # user reported seeing (~39s into the m21 clip; the near tip
        # projected at a wildly different scale than the far tip of the same
        # symmetric 3D shape). Judge the WHOLE polygon's nearest point, not
        # just its anchor.
        if float(poly_depth.min()) * proj.metres_per_unit < PASS_UNDER_M:
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
            image_size=image_size, reproj_error=reproj_error, stabilizer=None,
            pin_route=pin_route, timestamp=timestamp,
            progress_tracker=progress_tracker)

    if guidance_mode == 'gentle_corridor':
        # A shallow bend should read as one continuous walkable corridor. Do
        # not keep old carets from the previous anchor, otherwise the user sees
        # a turn instruction that outlives the actual bend.
        carets = []
        alphas = []
        if stabilizer is not None:
            stabilizer.last_carets = []
            stabilizer.last_alphas = []

    if stabilizer is not None:
        stabilizer.last_carets = [np.asarray(poly, float).copy() for poly in carets]
        stabilizer.last_alphas = [float(value) for value in alphas]

    # A frame with the lane but no caret is still useful guidance — the ribbon
    # alone says "the walkway goes this way", which is exactly the moment
    # (mid-turn, marking passing underfoot) the shipping overlay goes blank.
    # Only a frame with neither is worth suppressing.
    if not carets and not ribbon_quads and not ribbon_edges:
        max_depth = max((float(to_camera(proj.floor_point(px, py), R, t)[0, 2]) for px, py in anchors), default=0.0)
        return None, 'route_behind_camera' if max_depth <= 0.0 else 'geometry_off_screen'

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
        'guidance_mode': guidance_mode,
        'local_bend_deg': float(local_bend_deg),
        'anchors': anchors,
    }, 'ok'


def render_v2(frame, payload):
    """Draw a v2 payload. Mirrors what a three.js layer would do."""
    out = frame.copy()
    if not payload:
        return out
    K, R, t = payload['K'], payload['R'], payload['t']
    img_h, img_w = out.shape[:2]

    # build_ar_world_v2 already sanitizes ribbon geometry against the POSE IT
    # WAS BUILT WITH. A caller that reprojects the same payload through a
    # DIFFERENT pose - e.g. poc_ar_arrow/render_walk_video.py interpolates a
    # pose between two real localizer fixes so its preview video plays back
    # smoothly instead of as a slideshow - can still turn perfectly good
    # geometry into the same on-screen streak, because the pose being drawn
    # with is no longer the one it was validated against. Re-check here,
    # against whatever R/t this call actually received, so it's caught
    # regardless of which pose produced it. (Reported directly by a user
    # watching this preview at ~33s into the m21 clip - confirmed to appear
    # only on INTERPOLATED frames between two real fixes, never on a real fix
    # itself, which is what pointed at reprojection rather than the payload.)
    ribbon_quads = _sanitize_ribbon_quads(payload['ribbon_quads'], R, t, K, img_w, img_h)
    ribbon_edges = _sanitize_ribbon_edges(payload['ribbon_edges'], R, t, K, img_w, img_h)

    # Ribbon first, under everything, at low alpha: it is the surface, not the
    # message. Each quad fades with its own depth so the lane arrives out of the
    # distance and passes under the viewer instead of ending on a hard edge.
    metres_per_unit = payload.get('metres_per_unit', 1.0)
    for quad, depth in ribbon_quads:
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

    for edge in ribbon_edges:
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
