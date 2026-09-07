"""Compare theta (get_yaw fallback) vs calculate_camera_heading (real production path).

api/localization.py only falls back to `theta` when `calculate_camera_heading`
returns None (missing R/projector). This script checks whether the heading
noise found via `theta` in the sweep CSVs also shows up in the function
production actually calls, or whether it was an artifact of measuring the
fallback path instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for path in (BACKEND_DIR, BACKEND_DIR / "app", BACKEND_DIR / "core", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app.localization_config as localization_config  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
from app.services.ar_service import get_projector  # noqa: E402
from app.utils.heading import calculate_camera_heading  # noqa: E402
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA, DEFAULT_GRAPH, DEFAULT_MAP, DEFAULT_VIDEO, QueryConfig,
    find_reference_size, run_attempt,
)


def wrap(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def main() -> None:
    reference_size = find_reference_size(DEFAULT_DATA)
    localizer = Localizer(
        floor_id="floor1", data_dir=DEFAULT_DATA,
        floor_plan_path=DEFAULT_MAP, json_map_path=DEFAULT_GRAPH,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = 20
    localizer.debug_mode = True
    projector = get_projector("floor1", localizer)
    print("projector available:", projector is not None)

    cap = cv2.VideoCapture(str(DEFAULT_VIDEO))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(10.0 * fps)))
    frame_indices = list(range(0, frame_count, step))[:53]

    config = QueryConfig("raw_exact_1920x1080", "raw", exact_size=True)
    rows = []
    for frame_index in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        result, xy, _elapsed, _observer = run_attempt(localizer, frame, config, reference_size)
        if not result.get("success") or xy is None:
            continue
        pose = result.get("pose") or {}
        theta = pose.get("theta")
        heading = calculate_camera_heading(pose.get("R"), float(xy[0]), float(xy[1]), projector) if projector else None
        rows.append({
            "time_s": frame_index / fps,
            "theta": theta,
            "camera_heading": heading,
        })
        print(f"t={frame_index/fps:7.1f}s theta={theta} calculate_camera_heading={heading}")
    cap.release()

    for key in ("theta", "camera_heading"):
        values = [r[key] for r in rows if r[key] is not None]
        if len(values) < 2:
            print(f"{key}: not enough data ({len(values)} points)")
            continue
        diffs = [abs(wrap(values[i + 1] - values[i])) for i in range(len(values) - 1)]
        print(f"{key}: n={len(values)} median |consecutive diff| = {sorted(diffs)[len(diffs)//2]:.1f} deg")


if __name__ == "__main__":
    main()
