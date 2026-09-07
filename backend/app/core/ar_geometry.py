"""Shared AR geometry: floor-plan pixels <-> real 3D world, at the true map scale.

The one thing everything here exists to get right: **one SLAM world unit is NOT
one metre.** Monocular SLAM fixes its own arbitrary scale, and on this dataset a
world unit is ~6 m. Code that assumed "world units (~meters)" produced a floor
plane ~0.9 m below the real floor (arrows projected off the bottom of the frame,
worst right before a corner where they matter most) and chevrons ~2.4 m wide -
wider than the corridor they sat in.

So nothing here is a hand-tuned constant in world units. Sizes are declared in
METRES and converted through the scale actually measured from the map:

    1 world unit = |H_matrix linear part| px/unit * M_PER_PX m/px

Frames
------
floor-plan px : map image pixels, y-down. Route/topology coordinates live here.
world (3D)    : the SLAM frame the camera pose (R, t) is expressed in.
camera        : OpenCV convention - x right, y down, z forward.
"""
import math

import numpy as np

# Metres per floor-plan pixel. Measured and validated across the localization
# benchmark (see LOCALIZATION_BENCHMARK_SUMMARY.md); every px->m figure in the
# benchmark results divides by 1/0.181 = 5.5249 px/m exactly.
M_PER_PX = 0.181

# Where the phone is held, in metres above the floor. The floor plane sits this
# far below the camera-trajectory plane that PCA fits through the mapping walk.
CAMERA_HEIGHT_M = 1.5

# Arrow footprint in METRES. A corridor is ~2 m wide, so a half-width of 0.55 m
# fills a bit over half of it - readable at a glance from several metres back
# without looking like it covers the whole walkway. Seen at a shallow angle the
# floor compresses hard in depth, so the arrow is longer than it is wide or it
# would foreshorten into a stripe.
CHEVRON_HALF_WIDTH_M = 0.42
ARROW_LENGTH_M = 1.45


def _round_corners(points, radius, segments=4):
    """Round every corner of a closed 2D outline by `radius`.

    Each corner is replaced by a quadratic arc that starts and ends on the
    adjacent edges, so the silhouette keeps its proportions while losing its
    hard points. The radius is clamped per corner to just under half the
    shorter adjoining edge, which keeps short edges - the notch either side of
    the shaft - from collapsing or self-intersecting.
    """
    n = len(points)
    if n < 3 or radius <= 0:
        return list(points)

    out = []
    for i in range(n):
        px, py = points[(i - 1) % n]
        cx, cy = points[i]
        nx, ny = points[(i + 1) % n]

        v1 = (px - cx, py - cy)
        v2 = (nx - cx, ny - cy)
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            out.append((cx, cy))
            continue
        r = min(radius, 0.49 * l1, 0.49 * l2)
        a = (cx + v1[0] / l1 * r, cy + v1[1] / l1 * r)
        b = (cx + v2[0] / l2 * r, cy + v2[1] / l2 * r)
        for k in range(segments + 1):
            t = k / segments
            u = 1.0 - t
            # quadratic Bezier a -> corner -> b
            out.append((u * u * a[0] + 2 * u * t * cx + t * t * b[0],
                        u * u * a[1] + 2 * u * t * cy + t * t * b[1]))
    return out


def world_scale(H_matrix):
    """Metres per SLAM world unit, from the map's own similarity transform.

    H_matrix maps floor-plane (u, v) -> floor-plan px, so the norm of its linear
    part is px per world unit; multiplying by M_PER_PX gives metres per unit.
    """
    H = np.asarray(H_matrix, float)
    px_per_unit = math.hypot(H[0, 0], H[0, 1])
    if px_per_unit <= 1e-9:
        raise ValueError('degenerate H_matrix: cannot recover world scale')
    return px_per_unit * M_PER_PX


class FloorProjector:
    """Maps floor-plan px onto the real floor plane in SLAM world coordinates.

    Positions come from H_matrix's inverse; the floor plane itself is the
    camera-trajectory plane (PCA of the mapping walk) pushed down by the camera
    height. `floor_normal` is stored sign-corrected so that +normal points from
    the trajectory plane toward the floor in this dataset's convention.
    """

    def __init__(self, H_matrix, floor_config, camera_height_m=CAMERA_HEIGHT_M):
        self.H = np.asarray(H_matrix, float)
        self.H_inv = np.linalg.inv(np.asarray(H_matrix, float))
        self.metres_per_unit = world_scale(H_matrix)
        self.units_per_metre = 1.0 / self.metres_per_unit

        self.traj_center = np.asarray(floor_config['traj_center'], float)
        self.v1 = np.asarray(floor_config['floor_v1'], float)
        self.v2 = np.asarray(floor_config['floor_v2'], float)
        down = np.asarray(floor_config['floor_normal'], float)
        self.down = down / (np.linalg.norm(down) + 1e-9)

        self.camera_height_m = camera_height_m
        self.drop = self.m(camera_height_m)

    def m(self, metres):
        """Metres -> world units."""
        return metres * self.units_per_metre

    def plane_point(self, px, py):
        """Floor-plan px -> world point ON THE TRAJECTORY PLANE (eye height)."""
        p = self.H_inv @ np.array([float(px), float(py), 1.0])
        p = p[:2] / p[2]
        return self.traj_center + p[0] * self.v1 + p[1] * self.v2

    def floor_point(self, px, py):
        """Floor-plan px -> world point ON THE FLOOR."""
        return self.plane_point(px, py) + self.drop * self.down

    def world_to_floor_px(self, point_world):
        """World point -> floor-plan px (its ground track; height is dropped)."""
        rel = np.asarray(point_world, float) - self.traj_center
        q = self.H @ np.array([rel @ self.v1, rel @ self.v2, 1.0])
        return q[:2] / q[2]

    def camera_floor_px(self, R, t):
        """Where the camera itself stands, in floor-plan px.

        Geometry drawn for a frame has to be laid out from the pose that frame
        was captured with. The smoothed (x, y) shown on the map trails the true
        position by roughly half a metre while walking, which is invisible on a
        map and fatal here: anchors placed a short distance "ahead" of a
        trailing origin end up behind the camera and cannot be drawn at all.
        """
        R = np.asarray(R, float)
        t = np.asarray(t, float).reshape(3)
        return self.world_to_floor_px(-R.T @ t)

    def direction(self, px, py, dx, dy, eps=1.0):
        """A floor-plan direction (dx, dy) at (px, py) as a world unit vector.

        Finite-differenced through plane_point so it picks up H_matrix's
        rotation. Rotating a pixel-space vector by hand instead is what once
        left chevrons correctly positioned but pointing the wrong way - which
        reads exactly like an arrow aiming through a wall.
        """
        a = self.plane_point(px, py)
        b = self.plane_point(px + dx * eps, py + dy * eps)
        w = b - a
        n = np.linalg.norm(w)
        return w / n if n > 1e-9 else w

    def chevron_polygon(self, px, py, dx, dy,
                        half_width_m=CHEVRON_HALF_WIDTH_M,
                        length_m=ARROW_LENGTH_M):
        """One caret lying flat on the floor at (px, py), aiming (dx, dy).

        A solid arrow paints a lot of floor and, once perspective squashes it,
        reads as a blob. A caret keeps the same directional read from far less
        ink and leaves the floor visible underneath. Corners are rounded because
        sharp points on a shape only tens of pixels across look crude.

        Deliberately ONE shape per station, not a stacked pair: the stations are
        already close enough that the trail itself reads as stacked chevrons.
        Drawing a pair at each one made the upper half of one collide with the
        lower half of the next, and perspective fused them into a smear further
        down the corridor.

        Returns a closed outline in world coordinates. It is CONCAVE, so callers
        must triangulate rather than fan from the first vertex.
        """
        origin = self.floor_point(px, py)
        fwd = self.direction(px, py, dx, dy)
        right = self.direction(px, py, -dy, dx)
        s = self.m(half_width_m)
        L = self.m(length_m)

        rise = 0.42 * L          # how far the apex leads the arms
        thick = 0.20 * L         # stroke thickness
        outline = [
            (-s, 0.0), (0.0, rise), (s, 0.0),
            (s, thick), (0.0, rise + thick), (-s, thick),
        ]
        outline = _round_corners(outline, radius=0.16 * s)
        return np.array([origin + r * right + f * fwd for r, f in outline], float)



def camera_forward(R):
    """World-space direction the camera is looking, from a world->camera R."""
    return np.asarray(R, float).T @ np.array([0.0, 0.0, 1.0])


def to_camera(points_world, R, t):
    """World points -> camera frame. Accepts (3,) or (N, 3)."""
    P = np.atleast_2d(np.asarray(points_world, float))
    R = np.asarray(R, float)
    t = np.asarray(t, float).reshape(3)
    return (R @ P.T).T + t
