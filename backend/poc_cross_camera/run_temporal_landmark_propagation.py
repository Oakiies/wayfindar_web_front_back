"""Experiment 1: temporal propagation of map-landmark associations.

This is an experiment-only implementation.  It keeps the existing map,
MegaLoc retrieval, SuperPoint/LightGlue matcher, camera matrix and PnP gates.
It does not pool 2D points from different camera frames into one PnP call:
source-frame 2D observations are tracked into the target frame first, and the
target-frame coordinates are the only image points passed to PnP.

The experiment is motivated by:
  - Sarlin et al., CVPR 2019 (hierarchical localization / local matching)
  - Karaev et al., CoTracker 2023 (joint temporal point tracking)
  - Ventura et al., CVPR 2014 (generalized pose for multi-frame observations;
    cited here to make explicit why this script does NOT use that shortcut)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
APP_DIR = BACKEND_DIR / "app"
REPO_ROOT = BACKEND_DIR.parent.parent
for path in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core import localization as loc  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
import app.localization_config as localization_config  # noqa: E402


DEFAULT_VIDEO = REPO_ROOT / "floor1_wide.MOV"
DEFAULT_DATA = APP_DIR / "data" / "map_data" / "result_floor1_4"
DEFAULT_MAP = APP_DIR / "data" / "map" / "floor1.jpg"
DEFAULT_GRAPH = APP_DIR / "data" / "json_map" / "floor1.json"
DEFAULT_OUT = SCRIPT_DIR / "out"

PAPERS = {
    "hierarchical_localization": "https://openaccess.thecvf.com/content_CVPR_2019/html/Sarlin_From_Coarse_to_Fine_Robust_Hierarchical_Localization_at_Large_Scale_CVPR_2019_paper.html",
    "cotracker": "https://arxiv.org/abs/2307.07635",
    "generalized_pose": "https://openaccess.thecvf.com/content_cvpr_2014/html/Ventura_A_Minimal_Solution_2014_CVPR_paper.html",
}


def find_reference_size(data_dir: Path) -> tuple[int, int]:
    kf_root = data_dir / "keyframes_superpoint"
    for kf_dir in sorted(kf_root.iterdir()):
        for name in ("image.jpg", "image.png"):
            image_path = kf_dir / name
            if image_path.exists():
                image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
                if image is not None:
                    return int(image.shape[1]), int(image.shape[0])
    raise FileNotFoundError(f"No keyframe image found under {kf_root}")


def finite_float(value, default=float("nan")) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def angular_diff_deg(a: float, b: float) -> float:
    return float((a - b + 180.0) % 360.0 - 180.0)


def spatial_metrics(points_2d: np.ndarray, width: int, height: int) -> dict:
    if points_2d is None or len(points_2d) == 0:
        return {
            "x_coverage": 0.0,
            "y_coverage": 0.0,
            "bbox_area_fraction": 0.0,
            "convex_hull_area_fraction": 0.0,
            "occupied_cells_4x3": 0,
        }
    pts = np.asarray(points_2d, dtype=np.float32)
    x_range = float(np.ptp(pts[:, 0])) / max(float(width), 1.0)
    y_range = float(np.ptp(pts[:, 1])) / max(float(height), 1.0)
    bbox_area = max(0.0, x_range) * max(0.0, y_range)
    hull_area = 0.0
    if len(pts) >= 3:
        hull = cv2.convexHull(pts.reshape(-1, 1, 2))
        hull_area = float(cv2.contourArea(hull)) / max(float(width * height), 1.0)
    cell_x = np.clip((pts[:, 0] / max(float(width), 1.0) * 4).astype(int), 0, 3)
    cell_y = np.clip((pts[:, 1] / max(float(height), 1.0) * 3).astype(int), 0, 2)
    occupied = len(set(zip(cell_x.tolist(), cell_y.tolist())))
    return {
        "x_coverage": round(x_range, 6),
        "y_coverage": round(y_range, 6),
        "bbox_area_fraction": round(bbox_area, 6),
        "convex_hull_area_fraction": round(hull_area, 6),
        "occupied_cells_4x3": occupied,
    }


def extract_query(localizer: Localizer, frame: np.ndarray, reference_size: tuple[int, int]) -> dict:
    kpts, desc, scores, gray = loc.extract_features(
        frame,
        localizer.superpoint_extractor,
        target_size=reference_size,
        use_superpoint=True,
    )
    if desc is None or kpts is None or len(kpts) < 4:
        return {"kpts": None, "desc": None, "scores": None, "gray": gray, "global": None}
    global_desc = loc.extract_global_features(frame, localizer.retrieval_model)
    if localizer.pca_model is not None:
        global_desc = loc.apply_pca(global_desc.reshape(1, -1), localizer.pca_model).reshape(-1)
    return {"kpts": kpts, "desc": desc, "scores": scores, "gray": gray, "global": global_desc}


def make_correspondences(localizer: Localizer, query: dict, top_k: int) -> list[dict]:
    """Return candidate matches with map IDs preserved."""
    if query["desc"] is None or query["global"] is None:
        return []
    retrieved = loc.image_retrieval(
        query["global"], localizer.database, top_k=top_k, use_netvlad=True
    )
    candidates = []
    for candidate in retrieved:
        kf_idx = int(candidate["index"])
        kf_kpts = localizer.database["keypoints"][kf_idx]
        kf_desc = localizer.database["descriptors"][kf_idx]
        kf_scores = localizer.database["keypoint_scores"][kf_idx]
        kf_mp_ids = localizer.database["mappoint_ids"][kf_idx]
        match_indices, match_scores = localizer.superglue_matcher.match(
            query["kpts"], query["desc"], query["scores"],
            kf_kpts, kf_desc, kf_scores,
        )
        points_2d = []
        points_3d = []
        mp_ids = []
        query_indices = []
        match_conf = []
        for pair, conf in zip(match_indices, match_scores):
            query_idx, kf_keypoint_idx = int(pair[0]), int(pair[1])
            mp_id = int(kf_mp_ids[kf_keypoint_idx])
            if mp_id <= 0 or mp_id not in localizer.mappoint_dict:
                continue
            points_2d.append(query["kpts"][query_idx])
            points_3d.append(localizer.mappoint_dict[mp_id])
            mp_ids.append(mp_id)
            query_indices.append(query_idx)
            match_conf.append(float(conf))
        if len(points_2d) < 4:
            continue
        points_2d = np.asarray(points_2d, dtype=np.float32)
        points_3d = np.asarray(points_3d, dtype=np.float32)
        raw_ok, R, t, inliers = loc.solve_pnp_ransac(
            points_2d,
            points_3d,
            localizer.K,
            reproj_threshold=8.0,
            min_inliers=4,
        )
        inlier_count = int(len(inliers)) if raw_ok and inliers is not None else 0
        ratio, error = (0.0, float("inf"))
        if raw_ok and inliers is not None:
            ratio, error = loc.compute_pnp_quality(points_2d, points_3d, inliers, R, t, localizer.K)
        score = float(inlier_count) + float(ratio) * 40.0 - float(error if math.isfinite(error) else 1000.0) * 2.0
        candidates.append({
            "keyframe_id": int(candidate["keyframe_id"]),
            "retrieval_score": float(candidate.get("score", 0.0)),
            "points_2d": points_2d,
            "points_3d": points_3d,
            "mp_ids": np.asarray(mp_ids, dtype=np.int64),
            "query_indices": np.asarray(query_indices, dtype=np.int32),
            "match_conf": np.asarray(match_conf, dtype=np.float32),
            "raw_inliers": inlier_count,
            "raw_inlier_ratio": float(ratio),
            "raw_reproj_error": float(error),
            "raw_R": R,
            "raw_t": t,
            "score": score,
        })
    candidates.sort(key=lambda item: (item["score"], item["retrieval_score"]), reverse=True)
    return candidates


def dedupe_correspondences(items: list[dict]) -> dict:
    best = {}
    for item in items:
        mp_id = int(item["mp_id"])
        old = best.get(mp_id)
        if old is None or float(item.get("track_error", 1e9)) < float(old.get("track_error", 1e9)):
            best[mp_id] = item
    values = list(best.values())
    if not values:
        return {"points_2d": np.empty((0, 2), np.float32), "points_3d": np.empty((0, 3), np.float32), "mp_ids": np.empty((0,), np.int64)}
    return {
        "points_2d": np.asarray([v["point_2d"] for v in values], dtype=np.float32),
        "points_3d": np.asarray([v["point_3d"] for v in values], dtype=np.float32),
        "mp_ids": np.asarray([v["mp_id"] for v in values], dtype=np.int64),
    }


def solve_and_measure(localizer: Localizer, corr: dict, width: int, height: int) -> dict:
    points_2d = corr["points_2d"]
    points_3d = corr["points_3d"]
    if len(points_2d) < 4:
        return {
            "success": 0,
            "num_matches": int(len(points_2d)),
            "num_inliers": 0,
            "inlier_ratio": 0.0,
            "median_reproj_error": float("inf"),
            "heading_deg": float("nan"),
            "x_px": float("nan"),
            "y_px": float("nan"),
            **spatial_metrics(points_2d, width, height),
        }
    ok, R, t, inliers = loc.solve_pnp_ransac(
        points_2d, points_3d, localizer.K,
        reproj_threshold=8.0, min_inliers=4,
    )
    if not ok or inliers is None:
        return {
            "success": 0,
            "num_matches": int(len(points_2d)),
            "num_inliers": 0,
            "inlier_ratio": 0.0,
            "median_reproj_error": float("inf"),
            "heading_deg": float("nan"),
            "x_px": float("nan"),
            "y_px": float("nan"),
            **spatial_metrics(points_2d, width, height),
        }
    inlier_count = int(len(inliers))
    ratio, error = loc.compute_pnp_quality(points_2d, points_3d, inliers, R, t, localizer.K)
    success = int(
        inlier_count >= int(localization_config.LOCALIZATION_PARAMS["min_inliers"])
        and ratio >= float(localization_config.LOCALIZATION_PARAMS["min_inlier_ratio"])
        and math.isfinite(error)
        and error <= float(localization_config.LOCALIZATION_PARAMS["max_median_reproj_error"])
    )
    heading = float(loc.get_yaw(R)) if R is not None else float("nan")
    position = loc.get_camera_position(R, t)
    xy = loc.project_to_floor_plan(position, localizer.H_matrix, localizer.floor_config) if position is not None else None
    return {
        "success": success,
        "num_matches": int(len(points_2d)),
        "num_inliers": inlier_count,
        "inlier_ratio": float(ratio),
        "median_reproj_error": float(error),
        "heading_deg": heading,
        "x_px": float(xy[0]) if xy is not None else float("nan"),
        "y_px": float(xy[1]) if xy is not None else float("nan"),
        **spatial_metrics(points_2d[inliers.reshape(-1)], width, height),
    }


def track_source_to_target(source_gray: np.ndarray, target_gray: np.ndarray, source_items: list[dict], max_error: float) -> list[dict]:
    if not source_items:
        return []
    source_points = np.asarray([item["point_2d"] for item in source_items], dtype=np.float32).reshape(-1, 1, 2)
    target_points, status_fwd, _ = cv2.calcOpticalFlowPyrLK(
        source_gray, target_gray, source_points, None,
        winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if target_points is None:
        return []
    source_back, status_back, _ = cv2.calcOpticalFlowPyrLK(
        target_gray, source_gray, target_points, None,
        winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    h, w = target_gray.shape[:2]
    output = []
    for idx, item in enumerate(source_items):
        if int(status_fwd[idx, 0]) == 0 or int(status_back[idx, 0]) == 0:
            continue
        target_xy = target_points[idx, 0]
        back_xy = source_back[idx, 0]
        error = float(np.linalg.norm(back_xy - source_points[idx, 0]))
        if error > max_error or not (0 <= target_xy[0] < w and 0 <= target_xy[1] < h):
            continue
        output.append({
            "point_2d": target_xy.astype(np.float32),
            "point_3d": item["point_3d"],
            "mp_id": int(item["mp_id"]),
            "track_error": error,
            "source_frame": int(item["source_frame"]),
        })
    return output


def read_frame(cap: cv2.VideoCapture, frame_index: int) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
    ok, frame = cap.read()
    return frame if ok else None


def evaluate_target(localizer: Localizer, frame: np.ndarray, reference_size: tuple[int, int], top_k: int) -> tuple[dict, dict, list[dict]]:
    query = extract_query(localizer, frame, reference_size)
    candidates = make_correspondences(localizer, query, top_k)
    direct = {"points_2d": np.empty((0, 2), np.float32), "points_3d": np.empty((0, 3), np.float32), "mp_ids": np.empty((0,), np.int64)}
    best = candidates[0] if candidates else None
    if best is not None:
        direct = {
            "points_2d": best["points_2d"],
            "points_3d": best["points_3d"],
            "mp_ids": best["mp_ids"],
        }
    direct_metrics = solve_and_measure(localizer, direct, reference_size[0], reference_size[1])
    direct_metrics.update({
        "matched_keyframe": best["keyframe_id"] if best else "",
        "retrieval_score": best["retrieval_score"] if best else float("nan"),
        "raw_candidate_inliers": best["raw_inliers"] if best else 0,
    })
    return query, direct, candidates


def build_source_items(source: dict, source_frame: int) -> list[dict]:
    return [
        {
            "point_2d": point,
            "point_3d": point3d,
            "mp_id": int(mp_id),
            "source_frame": int(source_frame),
        }
        for point, point3d, mp_id in zip(source["points_2d"], source["points_3d"], source["mp_ids"])
    ]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict], baseline_name: str, config_names: list[str]) -> dict:
    by_config = {}
    for config in config_names:
        part = [row for row in rows if row["config"] == config]
        successes = sum(int(row["success"]) for row in part)
        by_config[config] = {
            "attempts": len(part),
            "successes": successes,
            "success_rate": successes / len(part) if part else 0.0,
            "median_matches": float(np.median([row["num_matches"] for row in part])) if part else 0.0,
            "median_inliers": float(np.median([row["num_inliers"] for row in part])) if part else 0.0,
            "median_occupied_cells": float(np.median([row["occupied_cells_4x3"] for row in part])) if part else 0.0,
        }
    baseline = {int(row["frame"]): int(row["success"]) for row in rows if row["config"] == baseline_name}
    pairwise = {}
    for config in config_names:
        if config == baseline_name:
            continue
        current = {int(row["frame"]): int(row["success"]) for row in rows if row["config"] == config}
        gains = sum(1 for frame, value in current.items() if not baseline.get(frame, 0) and value)
        losses = sum(1 for frame, value in current.items() if baseline.get(frame, 0) and not value)
        pairwise[config] = {"gains": gains, "losses": losses, "net": gains - losses}
    return {"per_config": by_config, "paired_vs_baseline": pairwise}


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
    parser.add_argument("--window-seconds", type=float, default=0.25)
    parser.add_argument("--offsets", default="-0.25,-0.125,0.125,0.25")
    parser.add_argument("--fb-error", type=float, default=1.5)
    parser.add_argument("--tag", default="temporal_landmark_propagation")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)

    reference_size = find_reference_size(args.data_dir)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {args.video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(args.step_seconds * fps)))
    frame_indices = list(range(0, frame_count, step))[:args.max_frames]
    offset_seconds = [float(value) for value in args.offsets.split(",") if value.strip()]

    rows = []
    feature_cache: dict[int, dict] = {}
    direct_cache: dict[int, dict] = {}
    gray_cache: dict[int, np.ndarray] = {}

    def get_direct(frame_index: int) -> tuple[dict, dict]:
        if frame_index in direct_cache:
            return feature_cache[frame_index], direct_cache[frame_index]
        frame = read_frame(cap, frame_index)
        if frame is None:
            empty = {"points_2d": np.empty((0, 2), np.float32), "points_3d": np.empty((0, 3), np.float32), "mp_ids": np.empty((0,), np.int64)}
            query = {"kpts": None, "desc": None, "scores": None, "gray": None, "global": None}
        else:
            query, direct, _ = evaluate_target(localizer, frame, reference_size, args.top_k)
            feature_cache[frame_index] = query
            direct_cache[frame_index] = direct
            gray_cache[frame_index] = query["gray"]
            return query, direct
        feature_cache[frame_index] = query
        direct_cache[frame_index] = empty
        return query, empty

    for ordinal, target_frame in enumerate(frame_indices, start=1):
        started = time.perf_counter()
        target_frame_image = read_frame(cap, target_frame)
        if target_frame_image is None:
            continue
        target_query, target_direct = get_direct(target_frame)
        direct_metrics = solve_and_measure(localizer, target_direct, *reference_size)
        direct_metrics["config"] = "direct"
        direct_metrics["source_offset_s"] = 0.0

        all_propagated = []
        past_propagated = []
        for offset in offset_seconds:
            source_frame = int(round(target_frame + offset * fps))
            if source_frame < 0 or source_frame >= frame_count or source_frame == target_frame:
                continue
            source_frame_image = read_frame(cap, source_frame)
            if source_frame_image is None:
                continue
            source_query, source_direct = get_direct(source_frame)
            source_items = build_source_items(source_direct, source_frame)
            tracked = track_source_to_target(
                source_query["gray"], target_query["gray"], source_items, args.fb_error
            )
            for item in tracked:
                item["source_offset_s"] = float(offset)
            all_propagated.extend(tracked)
            if offset < 0:
                past_propagated.extend(tracked)

        propagated = dedupe_correspondences(all_propagated)
        past_only = dedupe_correspondences(past_propagated)
        combined = dedupe_correspondences(
            [
                *[
                    {"point_2d": p2, "point_3d": p3, "mp_id": int(mp), "track_error": 0.0}
                    for p2, p3, mp in zip(target_direct["points_2d"], target_direct["points_3d"], target_direct["mp_ids"])
                ],
                *all_propagated,
            ]
        )
        combined_past = dedupe_correspondences(
            [
                *[
                    {"point_2d": p2, "point_3d": p3, "mp_id": int(mp), "track_error": 0.0}
                    for p2, p3, mp in zip(target_direct["points_2d"], target_direct["points_3d"], target_direct["mp_ids"])
                ],
                *past_propagated,
            ]
        )

        configs = {
            "direct": target_direct,
            "propagated": propagated,
            "direct_plus_propagated": combined,
            "past_only": past_only,
            "direct_plus_past": combined_past,
        }
        for config, corr in configs.items():
            metrics = solve_and_measure(localizer, corr, *reference_size)
            row = {
                "frame": int(target_frame),
                "time_s": round(target_frame / fps, 3),
                "config": config,
                "success": int(metrics["success"]),
                "num_matches": int(metrics["num_matches"]),
                "num_inliers": int(metrics["num_inliers"]),
                "inlier_ratio": metrics["inlier_ratio"],
                "median_reproj_error": metrics["median_reproj_error"],
                "x_px": metrics["x_px"],
                "y_px": metrics["y_px"],
                "heading_deg": metrics["heading_deg"],
                "x_coverage": metrics["x_coverage"],
                "y_coverage": metrics["y_coverage"],
                "bbox_area_fraction": metrics["bbox_area_fraction"],
                "convex_hull_area_fraction": metrics["convex_hull_area_fraction"],
                "occupied_cells_4x3": metrics["occupied_cells_4x3"],
                "propagated_raw_count": len(all_propagated),
                "propagated_past_count": len(past_propagated),
                "deduplicated_count": int(len(corr["points_2d"])),
                "elapsed_s": round(time.perf_counter() - started, 3),
            }
            rows.append(row)
        print(f"[{ordinal}/{len(frame_indices)}] frame={target_frame} direct={direct_metrics['success']} propagated={len(all_propagated)} combined={int(rows[-3]['success'])}", flush=True)

    cap.release()
    tag = args.tag.replace(" ", "_")
    csv_path = args.out / f"floor1_wide_{tag}.csv"
    summary_path = args.out / f"floor1_wide_{tag}_summary.json"
    write_csv(csv_path, rows)
    configs = ["direct", "propagated", "direct_plus_propagated", "past_only", "direct_plus_past"]
    summary = {
        "experiment": "temporal landmark propagation into target-frame PnP",
        "pipeline_locked": {
            "retrieval": "MegaLoc",
            "local_features": "SuperPoint",
            "matcher": "LightGlue via existing accelerated matcher",
            "pose": "existing PnP-RANSAC implementation and gates",
            "map_rebuilt": False,
            "map_data": str(args.data_dir),
        },
        "sampling": {
            "video": str(args.video),
            "fps": fps,
            "frame_count": frame_count,
            "step_seconds": args.step_seconds,
            "sampled_frames": len(frame_indices),
            "offset_seconds": offset_seconds,
            "fb_error_px": args.fb_error,
        },
        "results": summarize(rows, "direct", configs),
        "papers_and_official_code": PAPERS,
        "limitations": [
            "Success means unchanged PnP gate-pass, not ground-truth accuracy.",
            "Past+future is an offline upper bound; past-only is the online-compatible condition.",
            "KLT propagation is an ablation before CoTracker and is not a claim to reproduce CoTracker.",
            "No 2D points from source frames are passed directly to target-frame PnP.",
        ],
        "outputs": {"csv": str(csv_path)},
    }
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, allow_nan=True), flush=True)


if __name__ == "__main__":
    main()
