import math

import numpy as np


def normalize_heading_deg(angle: float) -> float:
    return float(angle % 360.0)


def blend_heading_deg(prev_heading: float, target_heading: float, alpha: float) -> float:
    """Circular heading blend in degrees."""
    delta = ((float(target_heading) - float(prev_heading) + 180.0) % 360.0) - 180.0
    return normalize_heading_deg(float(prev_heading) + float(alpha) * delta)


def calculate_direction(from_x: float, from_y: float, to_x: float, to_y: float) -> float:
    """Return bearing angle in degrees (0=East, 90=South) from one point to another."""
    dx = to_x - from_x
    dy = to_y - from_y
    angle = math.degrees(math.atan2(dy, dx))
    print(f"DEBUG: Calc Direction: ({from_x:.0f},{from_y:.0f})->({to_x:.0f},{to_y:.0f}) dx={dx:.1f} dy={dy:.1f} ang={angle:.1f}")
    return angle


def calculate_camera_heading(R, map_x: float, map_y: float, projector) -> float | None:
    """Return the camera's forward direction in the floor-plan frame.

    ``R`` is the OpenCV world-to-camera rotation, so ``R.T @ [0, 0, 1]`` is
    the direction the camera is looking in world space. Project that vector
    onto the calibrated floor plane, then solve it in the local map-pixel
    basis. This is the same pose-first idea used by AR tracking systems; it
    avoids guessing a fixed ``90 - theta`` conversion after the homography and
    floor basis have already rotated the world.

    The returned frame is the repository's map frame: 0° right/east and +90°
    down/south.
    """
    try:
        rotation = np.asarray(R, dtype=float).reshape(3, 3)
        forward_world = rotation.T @ np.array([0.0, 0.0, 1.0], dtype=float)
        normal = np.asarray(projector.down, dtype=float).reshape(3)
        normal /= np.linalg.norm(normal) or 1.0
        forward_floor = forward_world - normal * float(np.dot(forward_world, normal))
        if np.linalg.norm(forward_floor) < 1e-9:
            return None

        origin = np.asarray(projector.plane_point(float(map_x), float(map_y)), dtype=float)
        map_x_axis = np.asarray(projector.plane_point(float(map_x) + 1.0, float(map_y)), dtype=float) - origin
        map_y_axis = np.asarray(projector.plane_point(float(map_x), float(map_y) + 1.0), dtype=float) - origin
        coefficients, _, rank, _ = np.linalg.lstsq(
            np.column_stack((map_x_axis, map_y_axis)), forward_floor, rcond=None
        )
        if rank < 2 or np.linalg.norm(coefficients) < 1e-9:
            return None
        return normalize_heading_deg(math.degrees(math.atan2(coefficients[1], coefficients[0])))
    except (TypeError, ValueError, np.linalg.LinAlgError, AttributeError):
        return None
