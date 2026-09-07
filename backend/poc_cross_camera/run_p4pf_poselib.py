"""Paper-faithful P4Pf adaptation using PoseLib's minimal unknown-focal solver.

The original P4P/P5Pfr family solves pose with unknown focal length from 2D-3D
correspondences.  PoseLib exposes the P4Pf solver (unknown focal, zero radial
distortion).  This script feeds it the same query-side 2D-3D candidates as the
existing localizer and wraps the minimal solver in a small RANSAC loop.

This is not P5Pfr: radial distortion is intentionally held at zero because the
available PoseLib binding exposes P4Pf, not the ICCV-2013 P5Pfr solver.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import poselib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import localization as loc  # noqa: E402
import app.localization_config as localization_config  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA,
    DEFAULT_GRAPH,
    DEFAULT_MAP,
    DEFAULT_OUT,
    DEFAULT_VIDEO,
    find_reference_size,
)
from run_temporal_landmark_propagation import accelerate_localizer  # noqa: E402


P4PF_PAPER = "https://openaccess.thecvf.com/content_iccv_2013/html/Kukelova_Real-Time_Solution_to_2013_ICCV_paper.html"


def capture_candidates(localizer: Localizer, frame: np.ndarray):
    captured: list[dict] = []
    original_quality = loc.compute_pnp_quality

    def quality_wrapper(points_2d, points_3d, inliers, R, t, k):
        ratio, error = original_quality(points_2d, points_3d, inliers, R, t, k)
        captured.append({
            "points_2d": np.asarray(points_2d, dtype=np.float64).copy(),
            "points_3d": np.asarray(points_3d, dtype=np.float64).copy(),
            "inliers": None if inliers is None else np.asarray(inliers).reshape(-1).copy(),
            "ratio": float(ratio),
            "error": float(error),
        })
        return ratio, error

    loc.compute_pnp_quality = quality_wrapper
    try:
        result, _xy = localizer.localize(frame)
    finally:
        loc.compute_pnp_quality = original_quality

    if not captured:
        return None, None, result
    # The last quality call is the final candidate passed through the existing
    # matcher/PnP path.  Keep all candidates, including outliers, for P4Pf RANSAC.
    record = captured[-1]
    return record["points_2d"], record["points_3d"], result


def score_pose(pose, focal: float, points_2d: np.ndarray, points_3d: np.ndarray, cx: float, cy: float, threshold: float):
    cam = (pose.R @ points_3d.T + pose.t.reshape(3, 1)).T
    valid = cam[:, 2] > 1e-8
    errors = np.full(len(points_2d), np.inf, dtype=np.float64)
    centered = points_2d - np.array([cx, cy], dtype=np.float64)
    projected = focal * cam[:, :2] / np.maximum(cam[:, 2:3], 1e-8)
    errors[valid] = np.linalg.norm(projected[valid] - centered[valid], axis=1)
    inliers = np.flatnonzero(errors <= threshold)
    median_error = float(np.median(errors[inliers])) if len(inliers) else float("inf")
    return len(inliers), median_error, inliers


def p4pf_ransac(points_2d, points_3d, cx, cy, iterations=1000, threshold=8.0, seed=0):
    if points_2d is None or len(points_2d) < 4:
        return None
    centered = points_2d - np.array([cx, cy], dtype=np.float64)
    rng = np.random.default_rng(seed)
    best = None
    n = len(points_2d)
    for _ in range(iterations):
        sample = rng.choice(n, size=4, replace=False)
        try:
            poses, focals = poselib.p4pf(centered[sample], points_3d[sample], True)
        except Exception:
            continue
        for pose, focal in zip(poses, focals):
            if not np.isfinite(focal) or focal <= 0:
                continue
            count, median_error, inliers = score_pose(
                pose, float(focal), points_2d, points_3d, cx, cy, threshold
            )
            key = (count, -median_error)
            if best is None or key > best["key"]:
                best = {
                    "key": key,
                    "pose": pose,
                    "focal_px": float(focal),
                    "inliers": inliers,
                    "median_reproj_error_px": median_error,
                }
    if best is None:
        return None
    best.pop("key", None)
    return best


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
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--threshold", type=float, default=8.0)
    parser.add_argument("--tag", default="p4pf_poselib")
    args = parser.parse_args()

    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    localizer.debug_mode = True
    cx, cy = float(localizer.K[0, 2]), float(localizer.K[1, 2])
    map_f = float(localizer.K[0, 0])

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
        points_2d, points_3d, production = capture_candidates(localizer, frame)
        estimate = p4pf_ransac(
            points_2d, points_3d, cx, cy,
            iterations=args.iterations, threshold=args.threshold, seed=frame_index + 17,
        )
        row = {
            "frame": frame_index,
            "time_s": round(frame_index / fps, 3),
            "candidate_matches": 0 if points_2d is None else len(points_2d),
            "production_success": int(bool(production.get("success"))),
            "production_inliers": production.get("num_inliers"),
            "p4pf_success": int(estimate is not None),
            "p4pf_focal_px": None if estimate is None else estimate["focal_px"],
            "p4pf_focal_ratio": None if estimate is None else estimate["focal_px"] / map_f,
            "p4pf_inliers": None if estimate is None else len(estimate["inliers"]),
            "p4pf_median_reproj_error_px": None if estimate is None else estimate["median_reproj_error_px"],
        }
        rows.append(row)
        print(
            f"[{ordinal}/{len(frame_indices)}] frame={frame_index} candidates={row['candidate_matches']} "
            f"p4pf={row['p4pf_success']} f={row['p4pf_focal_px']} inliers={row['p4pf_inliers']}",
            flush=True,
        )
    cap.release()

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"floor1_wide_{args.tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    focal_values = [row["p4pf_focal_px"] for row in rows if row["p4pf_focal_px"]]
    summary = {
        "experiment": "PoseLib P4Pf minimal solver wrapped in query-side RANSAC",
        "paper": {"Kukelova et al., ICCV 2013 P4Pfr/P5Pfr family": P4PF_PAPER},
        "solver": "P4Pf (unknown focal, zero radial distortion), not P5Pfr",
        "map_focal_px": map_f,
        "sampled_frames": len(rows),
        "p4pf_successes": sum(row["p4pf_success"] for row in rows),
        "median_focal_ratio": float(np.median(focal_values) / map_f) if focal_values else None,
        "mean_focal_ratio": float(np.mean(focal_values) / map_f) if focal_values else None,
        "std_focal_ratio": float(np.std(focal_values) / map_f) if focal_values else None,
        "median_inliers": float(np.median([row["p4pf_inliers"] for row in rows if row["p4pf_inliers"] is not None])) if focal_values else None,
        "csv": str(csv_path),
    }
    summary_path = args.out / f"floor1_wide_{args.tag}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
