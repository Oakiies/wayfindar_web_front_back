"""Compare localization positions produced by map K vs an estimated focal K.

The same retrieved/matched 2D-3D candidate sets are reused for both camera
matrices. This isolates the effect of K instead of comparing two independent
retrieval/matching runs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
APP_DIR = BACKEND_DIR / "app"
for path in (BACKEND_DIR, APP_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core import localization as loc  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
import app.localization_config as localization_config  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA,
    DEFAULT_GRAPH,
    DEFAULT_MAP,
    DEFAULT_OUT,
    DEFAULT_VIDEO,
    find_reference_size,
)


def capture_candidates_fixed(localizer: Localizer, frame: np.ndarray, K: np.ndarray):
    candidates: list[tuple[np.ndarray, np.ndarray]] = []
    original_match = loc.match_2d_3d

    def match_wrapper(*args, **kwargs):
        points_2d, points_3d = original_match(*args, **kwargs)
        if points_2d is not None and points_3d is not None and len(points_2d) >= 4:
            candidates.append((
                np.asarray(points_2d, dtype=np.float64).copy(),
                np.asarray(points_3d, dtype=np.float64).copy(),
            ))
        return points_2d, points_3d

    loc.match_2d_3d = match_wrapper
    try:
        floor_plan_size = None
        if localizer.floor_plan_path.exists():
            floor_plan = cv2.imread(str(localizer.floor_plan_path))
            if floor_plan is not None:
                floor_plan_size = floor_plan.shape[:2]
        p = localization_config.LOCALIZATION_PARAMS
        result = loc.localize_image(
            frame, localizer.database, localizer.mappoint_dict, K,
            pca_model=localizer.pca_model,
            floor_config=localizer.floor_config,
            netvlad_model=localizer.retrieval_model,
            superpoint_extractor=localizer.superpoint_extractor,
            superglue_matcher=localizer.superglue_matcher,
            H_matrix=localizer.H_matrix,
            top_k=p["top_k"],
            reproj_threshold=p["reproj_threshold"],
            min_inliers=p["min_inliers"],
            min_inlier_ratio=p["min_inlier_ratio"],
            max_median_reproj_error=p["max_median_reproj_error"],
            floor_plan_size=floor_plan_size,
            verbose=False,
            debug_mode=False,
            allow_orb_fallback=False,
            allow_keyframe_fallback=False,
            use_superpoint=True,
            use_superglue=True,
            calibration_callback=None,
        )
    finally:
        loc.match_2d_3d = original_match
    return candidates, result


def best_pose(candidates, K, localizer: Localizer):
    p = localization_config.LOCALIZATION_PARAMS
    floor_plan_size = None
    if localizer.floor_plan_path.exists():
        floor_plan = cv2.imread(str(localizer.floor_plan_path))
        if floor_plan is not None:
            floor_plan_size = floor_plan.shape[:2]
    best = None
    for points_2d, points_3d in candidates:
        success, R, t, inliers = loc.solve_pnp_ransac(
            points_2d, points_3d, K,
            reproj_threshold=p["reproj_threshold"],
            min_inliers=p["min_inliers"],
        )
        if not success or inliers is None:
            continue
        ratio, error = loc.compute_pnp_quality(points_2d, points_3d, inliers, R, t, K)
        if ratio < float(p["min_inlier_ratio"]):
            continue
        if not np.isfinite(error) or error > float(p["max_median_reproj_error"]):
            continue
        pose = loc.get_6dof_pose(R, t)
        if not loc.is_pose_valid(pose, floor_plan_size, localizer.H_matrix, localizer.floor_config):
            continue
        score = float(len(inliers)) + float(ratio) * 40.0 - float(error) * 2.0
        if best is None or score > best["score"]:
            position = np.asarray(pose["position"], dtype=np.float64).reshape(3)
            xy = loc.project_to_floor_plan(position, localizer.H_matrix, localizer.floor_config)
            best = {
                "success": True,
                "position_3d": position,
                "xy": None if xy is None else np.asarray(xy, dtype=np.float64).reshape(2),
                "inliers": int(len(inliers)),
                "inlier_ratio": float(ratio),
                "median_reproj_error": float(error),
                "score": score,
            }
    return best or {"success": False, "position_3d": None, "xy": None,
                    "inliers": 0, "inlier_ratio": 0.0,
                    "median_reproj_error": None, "score": None}


def make_K(map_K: np.ndarray, focal: float) -> np.ndarray:
    K = np.asarray(map_K, dtype=np.float64).copy()
    K[0, 0] = focal
    K[1, 1] = focal
    return K


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=53)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--estimated-focal", type=float, default=949.3154351982264)
    parser.add_argument("--tag", default="map_vs_estimated_k")
    args = parser.parse_args()

    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    localizer.debug_mode = False

    map_K = localizer.K.copy()
    estimated_K = make_K(map_K, args.estimated_focal)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(args.video)
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(args.step_seconds * fps)))
    frame_indices = list(range(0, frame_count, step))[: args.max_frames]
    rows: list[dict] = []

    for ordinal, frame_index in enumerate(frame_indices, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        candidates, _map_pipeline_result = capture_candidates_fixed(localizer, frame, map_K)
        map_result = best_pose(candidates, map_K, localizer)
        estimated_result = best_pose(candidates, estimated_K, localizer)
        map_xy = map_result["xy"]
        estimated_xy = estimated_result["xy"]
        distance = None
        dx = dy = None
        if map_xy is not None and estimated_xy is not None:
            delta = estimated_xy - map_xy
            dx, dy = float(delta[0]), float(delta[1])
            distance = float(np.linalg.norm(delta))
        row = {
            "frame": frame_index,
            "time_s": round(frame_index / fps, 3),
            "candidate_sets": len(candidates),
            "map_success": int(map_result["success"]),
            "map_x": None if map_xy is None else float(map_xy[0]),
            "map_y": None if map_xy is None else float(map_xy[1]),
            "map_inliers": map_result["inliers"],
            "map_reproj_px": map_result["median_reproj_error"],
            "estimated_success": int(estimated_result["success"]),
            "estimated_x": None if estimated_xy is None else float(estimated_xy[0]),
            "estimated_y": None if estimated_xy is None else float(estimated_xy[1]),
            "estimated_inliers": estimated_result["inliers"],
            "estimated_reproj_px": estimated_result["median_reproj_error"],
            "delta_x_px": dx,
            "delta_y_px": dy,
            "delta_distance_px": distance,
        }
        rows.append(row)
        print(
            f"[{ordinal}/{len(frame_indices)}] frame={frame_index} candidates={len(candidates)} "
            f"map={row['map_success']} est={row['estimated_success']} delta={distance}",
            flush=True,
        )
    cap.release()

    both = [row["delta_distance_px"] for row in rows if row["delta_distance_px"] is not None]
    summary = {
        "experiment": "same-correspondence position comparison: map K vs estimated K",
        "video": str(args.video),
        "map_K": map_K.tolist(),
        "estimated_K": estimated_K.tolist(),
        "map_focal_px": float(map_K[0, 0]),
        "estimated_focal_px": float(args.estimated_focal),
        "focal_ratio_estimated_to_map": float(args.estimated_focal / map_K[0, 0]),
        "map_hfov_deg": math.degrees(2.0 * math.atan(1920.0 / (2.0 * map_K[0, 0]))),
        "estimated_hfov_deg": math.degrees(2.0 * math.atan(1920.0 / (2.0 * args.estimated_focal))),
        "sampled_frames": len(rows),
        "map_successes": sum(row["map_success"] for row in rows),
        "estimated_successes": sum(row["estimated_success"] for row in rows),
        "both_successes": len(both),
        "position_delta_px_when_both_success": {
            "median": float(np.median(both)) if both else None,
            "mean": float(np.mean(both)) if both else None,
            "p95": float(np.percentile(both, 95)) if both else None,
            "max": float(np.max(both)) if both else None,
        },
        "caveat": "No metric ground truth; delta measures sensitivity to K, not which K is correct.",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"floor1_wide_{args.tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary["csv"] = str(csv_path)
    summary_path = args.out / f"floor1_wide_{args.tag}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
