"""Builds the world-space AR payload the three.js overlay renders.

The browser gets real 3D geometry plus the real camera (K, R, t) and does the
projection itself, instead of receiving pre-flattened 2D screen coordinates.
That keeps the tricky, already-validated parts — H_matrix inverse, floor plane,
and the metres-per-world-unit scale — in core.ar_geometry, while letting the
GPU redraw at display refresh rate rather than at the localization rate.

The payload is deliberately small: a handful of chevron polygons, the 4
intrinsics, and the pose.
"""
import math

import cv2
import numpy as np

import app.localization_config as lc
from app.core import navigation as nav
from app.core.ar_geometry import FloorProjector, to_camera, M_PER_PX

# Arrow layout along the route, in floor-plan px (~0.18 m per px).
#
# Keep the original ~2.2 m spacing so the visual rhythm does not become denser.
# Extend the lookahead with more fixed stations instead: a new mark can enter
# from the far end before the last visible mark is reached, while the total AR
# guidance covers much more of the route ahead.
CHEVRON_SPACING_PX = 12.0
MAX_CHEVRONS = 20
# Perspective compresses floor markings as they recede. Keep the near part
# readable at the original station spacing, but thin the distant carets while
# leaving the continuous ribbon untouched. The physical route remains long;
# only the visual repetition is reduced in the far field.
FAR_CHEVRON_START_M = 8.0
FAR_CHEVRON_SKIP = 2
# How far past a corner the trail keeps going, in chevron spacings. Enough to
# show the bend itself; not so far that it paints a long line through the wall
# the corner turns behind.
CORNER_OVERSHOOT = 2.0

# Within this distance of a corner the user is at its mouth and can see around
# it, so the wall-occlusion clip stops applying. Declared in metres because it
# describes a real sight line, not a map-pixel quantity.
# (A fixed "corner is close enough to see around" distance used to live here.
# It was guesswork - the distance that actually matters is how far away the
# camera starts seeing the floor, which depends on the lens and how the phone
# is held. build_ar_world now discovers that per frame and drops the clip only
# when keeping it would leave nothing visible.)



# A floor quad closer than this to the phone is behind the user in practice and
# degenerate under projection.
NEAR_CLIP_M = 0.9

# Fade band, in metres of camera depth. The near ramp runs across roughly the
# distance walked between two updates, so an arrow dims over a step or two as
# it is reached rather than blinking out; the far ramp lets the next one arrive
# the same way.
FADE_NEAR_M = 3.4
FADE_NEAR_FULL_M = 5.6
FADE_FAR_M = 18.0
FADE_FAR_SPAN_M = 8.0

# Guards against drawing a shape that has collapsed to a line. These were once
# set high enough to prune far-away arrows, back when a placement bug pushed the
# whole trail 16 m out and squashed it; that bug is fixed, and thresholds tight
# enough to prune are also tight enough to CHATTER - the farthest arrow sat right
# on the limit and blinked in and out on every update. They are now only a
# degeneracy check, so a distant arrow simply gets small, the way distance
# should look.
MIN_ARROW_SPAN_FRAC = 0.008
MIN_ARROW_ASPECT = 0.04

# Pose quality required before geometry is registered to the world.
#
# Inlier COUNT is a crude proxy; median reprojection error measures the thing
# that actually matters here - how well this pose explains this image - so it
# is the gate, and the inlier floor is simply the localizer's own. An earlier
# +4 margin on the inlier floor was arbitrary and cost ~7% of frames whose
# counts sat at 10-13, i.e. just under the line, with no evidence their poses
# were bad.
#
# The threshold is tighter than the localizer's own accept bar because drawing
# on the floor needs more accuracy than placing a dot on a map: a pose good
# enough to say "you are in this corridor" can still be a metre out, which is
# invisible on the map and glaring when an arrow lands on a wall.
MIN_INLIERS = lc.LOCALIZATION_PARAMS['min_inliers']
MAX_REPROJ_ERROR_PX = lc.LOCALIZATION_PARAMS['max_median_reproj_error'] * 0.7

_projectors = {}


def get_projector(floor_id, localizer):
    """Cached FloorProjector for a floor (H_matrix/floor_config never change)."""
    cached = _projectors.get(floor_id)
    if cached is None:
        H = getattr(localizer, 'H_matrix', None)
        fc = getattr(localizer, 'floor_config', None)
        if H is None or fc is None:
            return None
        cached = FloorProjector(H, fc)
        _projectors[floor_id] = cached
    return cached


def _lateral_offset(x, y, path_coords):
    """Signed sideways offset from the user to their on-path projection, in px.

    The topology graph is hand-drawn on the floor plan, so its centreline sits
    ~0.5 m off the line people actually walk on this map. Chevrons pinned to
    that centreline inherit the error and drift toward a wall. Measuring the
    offset lets it be removed.
    """
    best_i, feet = nav._nearest_on_path(x, y, path_coords)
    ahead = nav._forward_point(path_coords, best_i, feet, 25.0)
    dx, dy = ahead[0] - feet[0], ahead[1] - feet[1]
    L = (dx * dx + dy * dy) ** 0.5
    if L < 1e-6:
        return 0.0, (0.0, 0.0)
    dx, dy = dx / L, dy / L
    nx, ny = -dy, dx                       # right-normal in the y-down map frame
    return (feet[0] - x) * nx + (feet[1] - y) * ny, (nx, ny)


def _arc_table(path_coords):
    """Cumulative arc length at each vertex of the route, in floor-plan px."""
    cum = [0.0]
    for i in range(len(path_coords) - 1):
        ax, ay = path_coords[i]
        bx, by = path_coords[i + 1]
        cum.append(cum[-1] + math.hypot(bx - ax, by - ay))
    return cum


def _point_at_arc(path_coords, cum, s):
    """The route point at arc length `s` from the route's start.

    Negative `s` extrapolates BACK along the first segment. The route begins at
    the nearest graph node, which is regularly several metres ahead of the
    walker, so without this the whole stretch between them carries no stations
    at all: the trail started ~16 m out, where the floor is compressed so hard
    that the arrows flattened into slivers - the "tilted AR" that gets reported.
    """
    if s < 0:
        ax, ay = path_coords[0]
        bx, by = path_coords[1]
        L = math.hypot(bx - ax, by - ay) or 1.0
        return (ax + s * (bx - ax) / L, ay + s * (by - ay) / L)
    if s == 0:
        return path_coords[0]
    if s >= cum[-1]:
        return path_coords[-1]
    lo, hi = 0, len(cum) - 1
    while lo + 1 < hi:                      # binary search for the segment
        mid = (lo + hi) // 2
        if cum[mid] <= s:
            lo = mid
        else:
            hi = mid
    seg = cum[lo + 1] - cum[lo]
    f = (s - cum[lo]) / seg if seg > 1e-9 else 0.0
    ax, ay = path_coords[lo]
    bx, by = path_coords[lo + 1]
    return (ax + f * (bx - ax), ay + f * (by - ay))


def _user_arc(path_coords, cum, x, y):
    """How far along the route the user is, in floor-plan px. May be NEGATIVE.

    _nearest_on_path clamps a position that lies before the route's first
    vertex onto that vertex, reporting 0. Since the route starts at the nearest
    graph node - often metres ahead of the walker - that clamp silently erased
    the gap between them and pushed the first station a whole node-spacing
    further out. Returning a signed distance keeps that stretch on the ruler.
    """
    best_i, proj = nav._nearest_on_path(x, y, path_coords)
    base = cum[best_i] + math.hypot(proj[0] - path_coords[best_i][0],
                                    proj[1] - path_coords[best_i][1])
    if best_i == 0 and base < 1e-6 and len(path_coords) >= 2:
        ax, ay = path_coords[0]
        bx, by = path_coords[1]
        L = math.hypot(bx - ax, by - ay)
        if L > 1e-6:
            behind = ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L
            if behind < 0:
                return behind          # signed: the walker is before the start
    return base


def chevron_anchors(x, y, path_coords, clip_at_corner=True, recenter=True):
    """Chevron positions along the route, in floor-plan px.

    Pinned to fixed stations measured from the START of the route, not to fixed
    distances ahead of the walker. Measuring from the walker kept every chevron
    at the same remove from them, so the trail slid along as they moved, never
    grew, and could never be reached - it read as a HUD, not as markings lying
    on the floor. Fixed stations behave the way paint on the ground behaves:
    each one grows as it is approached, then passes underfoot and is gone.

    Clipped just short of the next real corner: the projection has no notion of
    walls, so path points past a 90 deg turn would be drawn straight through the
    wall that actually hides them, reading as "turn here" at a spot the user has
    not reached.

    With recenter=False, world stations stay on the surveyed route regardless
    of camera motion. Video replay uses this mode to avoid moving the floor
    markings whenever a new localization fix changes the lateral offset.

    The legacy recenter=True mode shifts sideways through the user rather than through
    the surveyed centreline - the same reason car navigation draws its guidance
    line from the vehicle and takes only the *direction* from the route. Without
    this the map's own ~0.5 m centreline error lands the arrows against a wall.
    """
    if not path_coords or len(path_coords) < 2:
        return []
    cum = _arc_table(path_coords)
    here = _user_arc(path_coords, cum, x, y)

    far = here + CHEVRON_SPACING_PX * (MAX_CHEVRONS + 3)
    if clip_at_corner:
        nt = nav.next_turn_info(x, y, path_coords)
        if nt and nt['dist'] < far - here:
            # Reach a little way PAST the corner instead of stopping short of
            # it. Stopping short meant that once the corner was within a few
            # metres there was no route floor left inside the visible band at
            # all: the trail thinned to two arrows and then vanished, so the
            # walk read as "straight, straight, ...nothing, now you're turning".
            # Continuing around the bend lets the arrows curve into the turn
            # while it is still ahead - the transition a walker expects.
            # Anything that lands behind a wall or off frame is dropped by the
            # visibility and legibility checks further down.
            far = min(far, here + nt['dist'] + CHEVRON_SPACING_PX * CORNER_OVERSHOOT)
    far = min(far, cum[-1])

    # Stations sit on a grid fixed to the route, so the same physical spots come
    # up every frame; the walker simply passes them.
    k0 = int(math.floor(here / CHEVRON_SPACING_PX)) + 1
    stations = []
    k = k0
    while True:
        s = k * CHEVRON_SPACING_PX
        if s > far:
            break
        if s > here:
            stations.append(s)
        k += 1
    if not stations:
        return []

    off, (nx, ny) = _lateral_offset(x, y, path_coords) if recenter else (0.0, (0.0, 0.0))
    out = []
    for s in stations:
        px, py = _point_at_arc(path_coords, cum, s)
        out.append((float(px - off * nx), float(py - off * ny)))
    return out


def thin_far_anchors(anchors, proj, R, t, max_count=MAX_CHEVRONS):
    """Keep near carets dense and every Nth caret in the far field.

    Selection is based on camera depth, so it follows what the user actually
    sees rather than an arbitrary map distance. Points behind the camera are
    ignored before applying the count limit; the same helper is used by the
    live and PoC world renderers to keep their caret rhythm consistent.
    """
    selected = []
    far_seen = 0
    for point in anchors:
        depth = float(to_camera(proj.floor_point(point[0], point[1]), R, t)[0, 2])
        if depth <= 0.0:
            continue
        depth_m = depth * proj.metres_per_unit
        if depth_m <= FAR_CHEVRON_START_M:
            selected.append(point)
        elif far_seen % FAR_CHEVRON_SKIP == 0:
            selected.append(point)
        far_seen += int(depth_m > FAR_CHEVRON_START_M)
        if len(selected) >= max_count:
            break
    return selected


def _first_visible_index(anchors, proj, R, t, K, img_w, img_h, margin=0.06):
    """Index of the first anchor that actually lands inside the frame.

    A camera held at chest height sees the floor only from a few metres out -
    for a 1.5 m phone with this lens the near edge of the visible floor is
    ~3.9 m away, and everything nearer projects below the bottom of the image.
    Anchors placed closer than that are computed, projected, and drawn
    perfectly correctly into pixels nobody can see, which is exactly how the
    trail came to vanish while approaching a turn.

    Rather than assume a standoff distance (it depends on lens, resolution,
    how high the phone is held and how far it is pitched), this asks the
    projection where the floor actually starts being visible on THIS frame.
    """
    rvec, _ = cv2.Rodrigues(R)
    lo_y = img_h * (1.0 - margin)
    for i, (px, py) in enumerate(anchors):
        world = proj.floor_point(px, py)
        if to_camera(world, R, t)[0, 2] <= 0:
            continue
        uv = cv2.projectPoints(world.reshape(1, 3), rvec, t, K, np.zeros(4))[0].reshape(-1)
        # Inside the frame, not merely near it. Allowing half a frame-width of
        # overshoot let anchors that are plainly off screen count as visible,
        # and the payload then carried chevrons the user could not see - the
        # same "reported present, actually invisible" failure this check exists
        # to prevent.
        if 0 <= uv[0] < img_w and uv[1] < lo_y:
            return i
    return None


def _tangent(pts, i):
    n = len(pts)
    a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = (dx * dx + dy * dy) ** 0.5 or 1.0
    return dx / L, dy / L


def _tangent(pts, i):
    n = len(pts)
    a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = (dx * dx + dy * dy) ** 0.5 or 1.0
    return dx / L, dy / L


def _depth_alpha(depth_m):
    """Per-arrow opacity, so arrows arrive and leave instead of popping.

    Updates land ~1.5 s apart, so an arrow that simply stops being sent
    vanishes between one frame and the next. Ramping it down as it closes on
    the near edge of the visible floor - and up as it enters at the far end -
    turns that into the arrow being walked over and a fresh one appearing
    behind it, which is how markings on a floor behave.
    """
    if depth_m <= FADE_NEAR_M:
        return 0.0
    if depth_m < FADE_NEAR_FULL_M:
        a = (depth_m - FADE_NEAR_M) / (FADE_NEAR_FULL_M - FADE_NEAR_M)
    elif depth_m > FADE_FAR_M:
        a = max(0.0, 1.0 - (depth_m - FADE_FAR_M) / FADE_FAR_SPAN_M)
    else:
        a = 1.0
    return round(max(0.0, min(1.0, a)), 3)


def _payload(K, img_w, img_h, R, t, polys, marker=False, alphas=None):
    """Serialise world polygons + camera into the shape the frontend expects."""
    out = {
        'K': [float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])],
        'imgWH': [int(img_w), int(img_h)],
        'R': [[float(v) for v in row] for row in R],
        't': [float(v) for v in t],
        'chevrons': [[[round(float(c), 4) for c in p] for p in poly] for poly in polys],
        'marker': bool(marker),
    }
    if alphas is not None:
        out['alphas'] = [float(a) for a in alphas]
    return out


def _readable_on_screen(poly, rvec, t, K, img_w, img_h):
    """Is this arrow inside the frame AND big enough to read?

    An arrow lying on the floor but well off to one side is seen almost
    edge-on: perspective squashes it into a thin skewed sliver a few pixels
    tall. Its position is perfectly correct, but from that angle it reads as
    visual noise - or as "the AR looks crooked" - rather than as direction, so
    drawing it costs more than it gives.
    """
    uv = cv2.projectPoints(np.asarray(poly, float), rvec, t, K,
                           np.zeros(4))[0].reshape(-1, 2)
    if not np.all(np.isfinite(uv)):
        return False
    cx, cy = uv[:, 0].mean(), uv[:, 1].mean()
    if not (0 <= cx < img_w and 0 <= cy < img_h):
        return False
    w = uv[:, 0].max() - uv[:, 0].min()
    h = uv[:, 1].max() - uv[:, 1].min()
    if max(w, h) < img_w * MIN_ARROW_SPAN_FRAC:
        return False
    if min(w, h) < max(w, h) * MIN_ARROW_ASPECT:   # squashed nearly edge-on
        return False
    return True


def _any_on_screen(polys, rvec, t, K, img_w, img_h):
    """True if at least one arrow is on screen and legible."""
    return any(_readable_on_screen(p, rvec, t, K, img_w, img_h) for p in polys)


def build_ar_world_debug(localizer, floor_id, pose, x, y, path_coords, num_inliers,
                         image_size=None, reproj_error=None):
    """build_ar_world, but returns (payload, reason).

    `reason` names the gate that suppressed the overlay ('ok' when it did not).
    A dropped frame is a visible gap in the overlay, so which gate dropped it is
    the difference between a tuning problem and a geometry problem - worth being
    able to count rather than guess at.
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

    # Lay the trail out from where the camera actually is for THIS frame, not
    # from the smoothed map position, which lags ~0.5 m while walking. Anchors
    # measured forward from a lagging origin were landing behind the camera and
    # being discarded, blanking the overlay for over a second at a stretch.
    try:
        cam_px = proj.camera_floor_px(R, t)
        ax, ay = float(cam_px[0]), float(cam_px[1])
    except Exception:  # noqa: BLE001 - fall back to the smoothed position
        ax, ay = x, y

    if image_size:
        img_w, img_h = int(image_size[0]), int(image_size[1])
    else:                                   # principal point is the centre
        img_w, img_h = int(round(K[0, 2] * 2)), int(round(K[1, 2] * 2))

    anchors = chevron_anchors(ax, ay, path_coords)
    if len(anchors) < 1:
        return None, 'no_anchors'

    # Start the trail at the first point the camera can actually see, then take
    # every Nth sample from there to restore the intended spacing.
    start = _first_visible_index(anchors, proj, R, t, K, img_w, img_h)
    if start is None:
        # Everything before the next corner is nearer than the camera can see
        # the floor, so the clip that keeps arrows off the far side of a wall
        # has left nothing drawable. Approaching a turn that is the norm, not
        # the exception. Draw around the corner instead: slightly ahead of the
        # wall the user is about to pass beats a blank screen at the one moment
        # they need to be told which way to go.
        anchors = chevron_anchors(ax, ay, path_coords, clip_at_corner=False)
        start = _first_visible_index(anchors, proj, R, t, K, img_w, img_h) if anchors else None
    if start is None:
        return None, 'floor_not_visible'
    # Anchors are already one chevron apart - they are the fixed stations - so
    # take them in order from the first visible one.
    picked = thin_far_anchors(anchors[start:], proj, R, t)
    if not picked:
        return None, 'floor_not_visible'

    near_clip = proj.m(NEAR_CLIP_M)
    chevrons, alphas = [], []
    for i in range(len(picked)):
        px, py = picked[i]
        dx, dy = _tangent(picked, i)
        # Test the anchor, not every vertex: the GPU clips whatever crosses the
        # near plane by itself, and rejecting a whole marker because one corner
        # dips close threw away perfectly drawable geometry.
        anchor_depth = to_camera(proj.floor_point(px, py), R, t)[0, 2]
        if anchor_depth < near_clip:
            continue
        poly = proj.chevron_polygon(px, py, dx, dy)
        if np.any(to_camera(poly, R, t)[:, 2] <= 0.0):
            continue
        chevrons.append([[round(float(c), 4) for c in p] for p in poly])
        alphas.append(_depth_alpha(anchor_depth * proj.metres_per_unit))
    if not chevrons:
        return None, 'all_near_clipped'

    # Keep only the arrows that are actually legible where they land. Every
    # earlier gate reasons about anchor POINTS, and an anchor can pass while the
    # shape drawn around it falls outside the frame or collapses into an
    # edge-on sliver - which is how frames came to be counted as covered while
    # the user saw nothing useful. Judging the drawn geometry is the only test
    # that matches what reaches the screen.
    rvec, _ = cv2.Rodrigues(R)
    keep = [j for j, c in enumerate(chevrons)
            if _readable_on_screen(c, rvec, t, K, img_w, img_h)]
    if not keep:
        return None, 'drawn_off_screen'
    chevrons = [chevrons[j] for j in keep]
    alphas = [alphas[j] for j in keep]

    return _payload(K, img_w, img_h, R, t, chevrons, alphas=alphas), 'ok'


def build_ar_world(localizer, floor_id, pose, x, y, path_coords, num_inliers,
                   image_size=None, reproj_error=None):
    """World-space AR payload for the frontend, or None when not renderable.

    None means "do not register anything to the world this frame" - a weak pose,
    no route ahead, or nothing that survives the near clip. The frontend keeps
    showing its screen-fixed guidance in that case.
    """
    payload, _reason = build_ar_world_debug(
        localizer, floor_id, pose, x, y, path_coords, num_inliers, image_size, reproj_error
    )
    return payload


def build_ar_world_poc(localizer, floor_id, pose, x, y, path_coords, num_inliers,
                       image_size=None, reproj_error=None, stabilizer=None, pin_route=False,
                       timestamp=None, progress_tracker=None):
    """Use the floor-ribbon AR geometry from ``poc_ar_arrow``.

    The PoC intentionally lives beside the backend so it can be rendered and
    compared offline.  The replay UI needs the same world geometry as JSON,
    so this adapter keeps the PoC builder as the single source of truth and
    only converts NumPy arrays to JSON-safe lists at the API boundary.
    """
    from poc_ar_arrow.ar_arrow_v2 import build_ar_world_v2

    payload, _reason = build_ar_world_poc_debug(
        localizer, floor_id, pose, x, y, path_coords, num_inliers,
        image_size=image_size, reproj_error=reproj_error, stabilizer=stabilizer,
        pin_route=pin_route, timestamp=timestamp, progress_tracker=progress_tracker,
    )
    return payload


def build_ar_world_poc_debug(localizer, floor_id, pose, x, y, path_coords, num_inliers,
                             image_size=None, reproj_error=None, stabilizer=None,
                             pin_route=False, timestamp=None, progress_tracker=None):
    """Return the production AR payload and the geometry gate that decided it."""
    from poc_ar_arrow.ar_arrow_v2 import build_ar_world_v2

    payload, reason = build_ar_world_v2(
        localizer, floor_id, pose, x, y, path_coords, num_inliers,
        image_size=image_size, reproj_error=reproj_error, stabilizer=stabilizer,
        pin_route=pin_route, timestamp=timestamp, progress_tracker=progress_tracker,
    )
    if payload is None:
        return None, reason

    def point_list(point):
        return [round(float(value), 5) for value in point]

    def polygon_list(polygon):
        return [point_list(point) for point in polygon]

    K = np.asarray(payload['K'], dtype=float)
    return {
        'arVersion': 'poc_ar_arrow_v2',
        'K': [float(K[0, 0]), float(K[1, 1]),
              float(K[0, 2]), float(K[1, 2])],
        'imgWH': [int(payload['imgWH'][0]), int(payload['imgWH'][1])],
        'R': [[float(value) for value in row] for row in payload['R']],
        't': [float(value) for value in payload['t']],
        # Keep ``chevrons`` for older clients; v2 clients use ``carets``.
        'chevrons': [polygon_list(polygon) for polygon in payload['carets']],
        'carets': [polygon_list(polygon) for polygon in payload['carets']],
        'alphas': [float(value) for value in payload['alphas']],
        'metres_per_unit': float(payload.get('metres_per_unit', 1.0)),
        'guidance_mode': payload.get('guidance_mode', 'directional'),
        'local_bend_deg': float(payload.get('local_bend_deg', 0.0)),
        'ribbon_quads': [
            [polygon_list(quad), float(depth)]
            for quad, depth in payload['ribbon_quads']
        ],
        'ribbon_edges': [
            [point_list(point) for point in edge]
            for edge in payload['ribbon_edges']
        ],
        'marker': False,
    }, 'ok'


def add_poc_destination_marker(payload, localizer, floor_id, destination_xy,
                               title, arrived=False, distance_m=None):
    """Attach the perspective destination landmark used by the AR PoC."""
    if not payload or not destination_xy:
        return payload
    if not all(math.isfinite(float(value)) for value in destination_xy):
        return payload

    proj = get_projector(floor_id, localizer)
    if proj is None:
        return payload

    dx, dy = float(destination_xy[0]), float(destination_xy[1])
    centre = proj.floor_point(dx, dy)
    up = -np.asarray(proj.down, dtype=float)
    ex = proj.direction(dx, dy, 1.0, 0.0)
    ey = proj.direction(dx, dy, 0.0, 1.0)
    top = centre + proj.m(1.15) * up

    def ring(radius_m, steps=48):
        radius = proj.m(radius_m)
        return [centre + math.cos(angle) * radius * ex +
                math.sin(angle) * radius * ey
                for angle in (2.0 * math.pi * i / steps for i in range(steps))]

    def poly(points):
        return [[round(float(value), 5) for value in point] for point in points]

    def point_list(point):
        return [round(float(value), 5) for value in point]

    # A small 3-D teardrop in the vertical plane.  The PoC's final head is
    # screen-sized, but this world construction preserves its tip, bullseye,
    # and perspective relationship to the floor ring in the browser.
    head_radius = proj.m(0.23)
    head_centre = top + proj.m(0.34) * up
    head = [top]
    for index in range(25):
        angle = math.pi * (0.12 + 1.76 * index / 24.0)
        head.append(head_centre + math.cos(angle) * head_radius * ex +
                    math.sin(angle) * head_radius * up)
    head.append(top)

    base_half = proj.m(0.055)
    top_half = proj.m(0.027)
    stem = [centre - base_half * ex, centre + base_half * ex,
            top + top_half * ex, top - top_half * ex]

    payload['destination_marker'] = {
        'centre': point_list(centre),
        'top': point_list(top),
        'floor_outer': [point_list(point) for point in ring(0.48)],
        'floor_inner': [point_list(point) for point in ring(0.29)],
        'stem': poly(stem),
        'head': poly(head),
        'title': str(title or 'Destination'),
        'distance_m': float(distance_m) if distance_m is not None and math.isfinite(float(distance_m)) else None,
        'arrived': bool(arrived),
    }
    return payload
