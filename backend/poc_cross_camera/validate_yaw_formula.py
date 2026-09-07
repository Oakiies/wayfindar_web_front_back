"""Check app.core.localization.get_yaw against the map's own ground-truth motion.

Does not change production code. `get_yaw(R) = atan2(R[0,2], R[2,2])` reads the
Z-axis-in-camera-frame from Tcw (world->camera). For heading we want the
camera's own forward axis expressed in world frame, which for Tcw is the
third *row* of R (R^T @ [0,0,1] picks out row 2, not column 2):
atan2(R[2,0], R[2,2]).

This script scores both formulas against the direction of travel implied by
consecutive map keyframe positions (pose.txt already ships with the map, no
external ground truth needed) and reports which one tracks real motion
better. It does not modify app/core/localization.py.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DEFAULT_KEYFRAMES = BACKEND_DIR / "app" / "data" / "map_data" / "result_floor1_4" / "keyframes"


def load_pose(path: Path) -> np.ndarray:
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
    values = [float(x) for line in lines for x in line.split()]
    return np.array(values[:12], dtype=np.float64).reshape(3, 4)


def wrap_deg(a: np.ndarray) -> np.ndarray:
    return (a + 180.0) % 360.0 - 180.0


def circular_mean_offset(a_minus_b_deg: np.ndarray) -> float:
    return float(np.degrees(np.arctan2(
        np.mean(np.sin(np.radians(a_minus_b_deg))),
        np.mean(np.cos(np.radians(a_minus_b_deg))),
    )))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyframes-dir", type=Path, default=DEFAULT_KEYFRAMES)
    parser.add_argument("--min-motion", type=float, default=0.05, help="Min XZ displacement (map units) to count as motion")
    args = parser.parse_args()

    dirs = sorted(
        (d for d in args.keyframes_dir.iterdir() if d.is_dir()),
        key=lambda d: int(d.name),
    )
    yaw_current, yaw_proposed, positions = [], [], []
    for d in dirs:
        pose_path = d / "pose.txt"
        if not pose_path.exists():
            continue
        pose = load_pose(pose_path)
        R, t = pose[:, :3], pose[:, 3]
        camera_center = -R.T @ t
        positions.append(camera_center)
        yaw_current.append(np.degrees(np.arctan2(R[0, 2], R[2, 2])))
        yaw_proposed.append(np.degrees(np.arctan2(R[2, 0], R[2, 2])))

    positions = np.array(positions)
    displacement = np.diff(positions, axis=0)
    distance_xz = np.linalg.norm(displacement[:, [0, 2]], axis=1)
    moving = distance_xz > args.min_motion

    yaw_motion = np.degrees(np.arctan2(displacement[:, 0], displacement[:, 2]))[moving]
    yaw_current = np.array(yaw_current[:-1])[moving]
    yaw_proposed = np.array(yaw_proposed[:-1])[moving]

    off_current = circular_mean_offset(yaw_motion - yaw_current)
    off_proposed = circular_mean_offset(yaw_motion - yaw_proposed)
    err_current = np.median(np.abs(wrap_deg(yaw_current + off_current - yaw_motion)))
    err_proposed = np.median(np.abs(wrap_deg(yaw_proposed + off_proposed - yaw_motion)))

    print(f"keyframes total: {len(dirs)}, with significant motion: {int(moving.sum())}")
    print(f"current  get_yaw = atan2(R[0,2], R[2,2]) : median error vs travel direction = {err_current:.2f} deg (best-fit offset {off_current:.1f} deg)")
    print(f"proposed        = atan2(R[2,0], R[2,2]) : median error vs travel direction = {err_proposed:.2f} deg (best-fit offset {off_proposed:.1f} deg)")
    print("Lower is better. This does not prove correctness on its own (only 1 heuristic, no external GT) "
          "but a large, consistent gap here is a strong flag to investigate get_yaw before trusting heading output.")


if __name__ == "__main__":
    main()
