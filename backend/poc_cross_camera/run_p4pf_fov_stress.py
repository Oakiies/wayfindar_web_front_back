"""Stress-test unknown-focal P4Pf on simulated phone fields of view.

The source MOV has no trusted per-frame camera calibration.  We therefore
render finite-FoV query variants at several HFoVs, run the unchanged feature
pipeline, and solve pose/focal jointly from the resulting 2D-3D candidates.
This evaluates the camera-parameter recovery path, not metric ground truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np

from run_floor1_wide_production_sweep import (
    DEFAULT_DATA,
    DEFAULT_GRAPH,
    DEFAULT_MAP,
    DEFAULT_OUT,
    DEFAULT_VIDEO,
    QueryConfig,
    find_reference_size,
    fov_preserving_canvas,
    prepare_query,
)
from run_p4pf_poselib import capture_candidates, p4pf_ransac

from app.core.localizer import Localizer
import app.localization_config as localization_config
from run_temporal_landmark_propagation import accelerate_localizer


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
    parser.add_argument("--hfovs", default="45,70,90,120")
    parser.add_argument("--tag", default="p4pf_fov_stress")
    args = parser.parse_args()

    hfovs = [float(value.strip()) for value in args.hfovs.split(",") if value.strip()]
    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    localizer.debug_mode = True

    reference_size = find_reference_size(args.data_dir)
    map_f = float(localizer.K[0, 0])
    map_hfov = math.degrees(2.0 * math.atan(reference_size[0] / (2.0 * map_f)))

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
        print(f"[{ordinal}/{len(frame_indices)}] frame={frame_index}", flush=True)

        for hfov in hfovs:
            config = QueryConfig(
                name=f"vc_hfov_{hfov:g}", kind="virtual_camera", exact_size=False,
                source_hfov=hfov, yaw_deg=0.0,
            )
            query, valid_fraction = prepare_query(
                frame, config, localizer.K, reference_size, map_hfov
            )
            render_size, query_k = fov_preserving_canvas(
                localizer.K, reference_size, hfov, map_hfov
            )
            points_2d, points_3d, production = capture_candidates(localizer, query)
            estimate = p4pf_ransac(
                points_2d, points_3d, float(query_k[0, 2]), float(query_k[1, 2]),
                iterations=args.iterations, threshold=args.threshold,
                seed=frame_index + int(round(hfov * 10)),
            )
            row = {
                "frame": frame_index,
                "time_s": round(frame_index / fps, 3),
                "hfov_deg": hfov,
                "render_width": render_size[0],
                "render_height": render_size[1],
                "valid_source_fraction": valid_fraction,
                "candidate_matches": 0 if points_2d is None else len(points_2d),
                "production_success": int(bool(production.get("success"))),
                "production_inliers": production.get("num_inliers"),
                "p4pf_success": int(estimate is not None),
                "p4pf_focal_px": None if estimate is None else estimate["focal_px"],
                "p4pf_focal_ratio_to_map": None if estimate is None else estimate["focal_px"] / map_f,
                "p4pf_inliers": None if estimate is None else len(estimate["inliers"]),
                "p4pf_gate_10_inliers": int(estimate is not None and len(estimate["inliers"]) >= 10),
                "p4pf_median_reproj_error_px": None if estimate is None else estimate["median_reproj_error_px"],
            }
            rows.append(row)
            print(
                f"  hfov={hfov:g} candidates={row['candidate_matches']} "
                f"prod={row['production_success']} p4pf={row['p4pf_success']} "
                f"f_ratio={row['p4pf_focal_ratio_to_map']} inliers={row['p4pf_inliers']}",
                flush=True,
            )
    cap.release()

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"floor1_wide_{args.tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    per_hfov: dict[str, dict] = {}
    for hfov in hfovs:
        selected = [row for row in rows if row["hfov_deg"] == hfov]
        focal = [row["p4pf_focal_ratio_to_map"] for row in selected if row["p4pf_focal_ratio_to_map"] is not None]
        inlier_rows = [row["p4pf_inliers"] for row in selected if row["p4pf_inliers"] is not None]
        per_hfov[f"{hfov:g}"] = {
            "attempts": len(selected),
            "production_successes": sum(row["production_success"] for row in selected),
            "p4pf_solver_successes": sum(row["p4pf_success"] for row in selected),
            "p4pf_gate_10_inliers_successes": sum(row["p4pf_gate_10_inliers"] for row in selected),
            "median_focal_ratio_to_map": float(np.median(focal)) if focal else None,
            "mean_focal_ratio_to_map": float(np.mean(focal)) if focal else None,
            "std_focal_ratio_to_map": float(np.std(focal)) if focal else None,
            "median_inliers": float(np.median(inlier_rows)) if inlier_rows else None,
        }

    summary = {
        "experiment": "P4Pf unknown-focal solver over simulated source HFoVs",
        "video": str(args.video),
        "map_focal_px": map_f,
        "map_hfov_deg": map_hfov,
        "reference_size": list(reference_size),
        "hfovs_deg": hfovs,
        "sampled_frames": len(frame_indices),
        "per_hfov": per_hfov,
        "solver": "PoseLib P4Pf in custom RANSAC; unknown focal, zero radial distortion",
        "limitations": [
            "HFoV variants are simulated because the MOV has no trusted per-device K.",
            "Production success is the existing PnP gate, not metric pose accuracy.",
            "This is P4Pf, not the distortion-aware P5Pfr solver.",
        ],
        "csv": str(csv_path),
    }
    summary_path = args.out / f"floor1_wide_{args.tag}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
