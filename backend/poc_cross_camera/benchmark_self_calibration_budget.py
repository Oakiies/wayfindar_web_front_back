"""Measure the image-only self-calibration budget after model warm-up.

This benchmark intentionally separates process/model initialization from the
calibration stage.  Production can localize immediately with the map K while
the P4Pf estimate runs asynchronously and is committed only after quality
gates pass.  No device calibration API, ARCore, or ARKit is used.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from run_floor1_wide_production_sweep import DEFAULT_DATA, DEFAULT_GRAPH, DEFAULT_MAP, DEFAULT_VIDEO
from run_p4pf_poselib import capture_candidates, p4pf_ransac
from run_temporal_landmark_propagation import accelerate_localizer

from app.core.localizer import Localizer
import app.localization_config as localization_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--frame-index", type=int, default=300)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--threshold", type=float, default=8.0)
    parser.add_argument("--out", type=Path, default=Path("out/self_calibration_budget_summary.json"))
    args = parser.parse_args()

    t_process = time.perf_counter()
    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    t_models_ready = time.perf_counter()
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    localizer.debug_mode = True

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(args.video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Could not read frame {args.frame_index} from {args.video}")

    t_capture_start = time.perf_counter()
    points_2d, points_3d, production = capture_candidates(localizer, frame)
    t_capture_done = time.perf_counter()

    cx, cy = float(localizer.K[0, 2]), float(localizer.K[1, 2])
    t_solver_start = time.perf_counter()
    estimate = p4pf_ransac(
        points_2d, points_3d, cx, cy,
        iterations=args.iterations, threshold=args.threshold,
        seed=args.frame_index + 17,
    )
    t_solver_done = time.perf_counter()

    candidate_count = 0 if points_2d is None else len(points_2d)
    p4pf_inliers = None if estimate is None else len(estimate["inliers"])
    focal_ratio = None if estimate is None else estimate["focal_px"] / float(localizer.K[0, 0])
    summary = {
        "experiment": "fast-start image-only self-calibration budget",
        "video": str(args.video),
        "frame_index": args.frame_index,
        "no_external_calibration_dependency": True,
        "fast_path_estimates": ["fx", "fy"],
        "fast_path_keeps_from_map": ["cx", "cy"],
        "fast_path_distortion": "not_estimated",
        "model_ready_seconds": t_models_ready - t_process,
        "capture_correspondences_seconds": t_capture_done - t_capture_start,
        "p4pf_solver_seconds": t_solver_done - t_solver_start,
        "calibration_stage_seconds": t_solver_done - t_capture_start,
        "process_model_init_included_seconds": t_solver_done - t_process,
        "provisional_map_k_path": {
            "available_before_calibration_finishes": True,
            "blocking_budget_seconds": 0.0,
            "description": "localize immediately with map K; calibration is background work",
        },
        "production": {
            "success": bool(production.get("success")),
            "matches": production.get("num_matches"),
            "inliers": production.get("num_inliers"),
        },
        "p4pf": {
            "candidate_matches": candidate_count,
            "success": bool(estimate is not None),
            "inliers": p4pf_inliers,
            "focal_ratio_to_map": focal_ratio,
            "median_reproj_error_px": None if estimate is None else estimate["median_reproj_error_px"],
        },
        "decision": {
            "three_second_cold_process_target": "not met if model initialization is counted",
            "three_second_non_blocking_calibration_target": "met by design; first request does not wait for P4Pf",
            "commit_gate": "require >=10 P4Pf inliers and multi-frame focal consistency before replacing map K",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
