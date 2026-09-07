"""Diagnostic only. Tests two candidate root causes for heading instability
found in round 10 (gravity-constraining rotation did not help, so the cause
is likely in the correspondences/retrieval, not the rotation parametrization):

1. Spatial clustering of the 2D keypoints used by PnP -- correspondences
   clustered in one small region of the image are a classic, well-known
   cause of rotation ambiguity in pose estimation (the further apart the
   points, the better-constrained the rotation; this is why calibration
   patterns/PnP benchmarks emphasize point spread, e.g. discussed in
   Lepetit, Moreno-Noguer & Fua, "EPnP: An Accurate O(n) Solution to the
   PnP Problem", IJCV 2009, motivating their own point-spread analysis).
2. Whether retrieval jumps to a very different keyframe (different
   viewpoint) between consecutive timestamps -- if each timestamp matches
   an unrelated keyframe, heading "instability" may simply reflect that the
   camera really did face a different direction relative to a different
   nearby keyframe, not a pipeline defect.

No production code is changed; this only re-analyzes what the unmodified
pipeline already produced.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for path in (BACKEND_DIR, BACKEND_DIR / "app", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app.core.localization as loc  # noqa: E402
import app.localization_config as localization_config  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA, DEFAULT_GRAPH, DEFAULT_MAP, DEFAULT_OUT, DEFAULT_VIDEO,
    find_reference_size,
)


def recover_accepted(localizer, frame):
    captured = []
    original_quality = loc.compute_pnp_quality

    def wrapper(points_2d, points_3d, inliers, R, t, k):
        ratio, error = original_quality(points_2d, points_3d, inliers, R, t, k)
        captured.append({
            "points_2d": np.asarray(points_2d, dtype=np.float64).copy(),
            "inliers": None if inliers is None else np.asarray(inliers).reshape(-1).copy(),
            "ratio": float(ratio), "error": float(error),
        })
        return ratio, error

    loc.compute_pnp_quality = wrapper
    try:
        result, xy = localizer.localize(frame)
    finally:
        loc.compute_pnp_quality = original_quality

    if not result.get("success") or xy is None:
        return None, result
    target_ratio = float(result.get("inlier_ratio", 0.0) or 0.0)
    target_error = result.get("median_reproj_error")
    target_inliers = int(result.get("num_inliers", 0))
    for record in captured:
        n = 0 if record["inliers"] is None else len(record["inliers"])
        if (n == target_inliers and abs(record["ratio"] - target_ratio) < 1e-9
                and target_error is not None and abs(record["error"] - float(target_error)) < 1e-9):
            return record["points_2d"][record["inliers"]], result
    return None, result


def get_yaw_from_R(R: np.ndarray) -> float:
    return float(np.degrees(np.arctan2(R[2, 0], R[2, 2])))


def wrap(a):
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

    cap = cv2.VideoCapture(str(DEFAULT_VIDEO))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(10.0 * fps)))
    frame_indices = list(range(0, frame_count, step))[:53]

    ref_w, ref_h = reference_size
    rows = []
    for frame_index in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        pts2d, result = recover_accepted(localizer, frame)
        if pts2d is None:
            continue
        pose = result.get("pose") or {}
        R = np.asarray(pose.get("R"))
        heading = get_yaw_from_R(R) if R is not None else None

        # spatial spread: bounding-box coverage of the used keypoints relative to full frame
        x_range = (pts2d[:, 0].max() - pts2d[:, 0].min()) / ref_w
        y_range = (pts2d[:, 1].max() - pts2d[:, 1].min()) / ref_h
        centroid_x = float(pts2d[:, 0].mean() / ref_w)
        centroid_y = float(pts2d[:, 1].mean() / ref_h)

        rows.append({
            "frame": frame_index, "time_s": round(frame_index / fps, 3),
            "matched_keyframe": result.get("matched_keyframe"),
            "n_points": len(pts2d),
            "x_coverage_frac": round(float(x_range), 3),
            "y_coverage_frac": round(float(y_range), 3),
            "centroid_x_frac": round(centroid_x, 3),
            "centroid_y_frac": round(centroid_y, 3),
            "heading_deg": heading,
        })

    # heading jump vs keyframe-id jump vs point coverage
    print(f"{'t':>7} {'kf':>6} {'n_pts':>5} {'x_cov':>6} {'y_cov':>6} {'heading':>8}")
    for r in rows:
        print(f"{r['time_s']:7.1f} {str(r['matched_keyframe']):>6} {r['n_points']:5d} "
              f"{r['x_coverage_frac']:6.2f} {r['y_coverage_frac']:6.2f} {r['heading_deg']:8.1f}")

    heading_jumps, kf_jumps, coverage_at_jump = [], [], []
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        if a["heading_deg"] is None or b["heading_deg"] is None:
            continue
        h_jump = abs(wrap(b["heading_deg"] - a["heading_deg"]))
        try:
            kf_jump = abs(int(b["matched_keyframe"]) - int(a["matched_keyframe"]))
        except (TypeError, ValueError):
            kf_jump = None
        heading_jumps.append(h_jump)
        kf_jumps.append(kf_jump)
        coverage_at_jump.append(min(a["x_coverage_frac"], a["y_coverage_frac"]))

    heading_jumps = np.array(heading_jumps)
    valid_kf = np.array([j for j in kf_jumps if j is not None], dtype=float)
    print()
    print("median heading jump:", np.median(heading_jumps))
    print("median keyframe-id jump (proxy for viewpoint change):", np.median(valid_kf) if len(valid_kf) else None)
    if len(valid_kf) == len(heading_jumps):
        corr = np.corrcoef(heading_jumps, valid_kf)[0, 1]
        print("correlation(heading_jump, keyframe_id_jump):", round(float(corr), 3))
    coverage_arr = np.array(coverage_at_jump)
    corr2 = np.corrcoef(heading_jumps, coverage_arr)[0, 1]
    print("correlation(heading_jump, point_coverage_of_frame_i):", round(float(corr2), 3))
    print("median point coverage (min of x/y bbox frac):", round(float(np.median(coverage_arr)), 3))


if __name__ == "__main__":
    main()
