"""Benchmark multi-frame estimation of the full query camera model.

This is an experiment, not the production calibration path.  It reuses the
accepted 2D-3D correspondences from the existing localizer and estimates
fx, fy, cx, cy and the standard 5 OpenCV distortion coefficients jointly
with one pose per view.  The result is accepted only when the camera model
is numerically plausible and the reprojection errors are reasonable.

The feature pipeline resizes query frames to the map reference resolution,
so the reported K is in that same pixel coordinate system.  It must not be
copied directly to a raw camera stream without applying the same resize/crop
transform.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for path in (BACKEND_DIR, BACKEND_DIR / "app", BACKEND_DIR / "core", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app.core.localization as loc  # noqa: E402
import app.localization_config as localization_config  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
from estimate_query_focal import recover_accepted_correspondences  # noqa: E402
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA,
    DEFAULT_GRAPH,
    DEFAULT_MAP,
    DEFAULT_OUT,
    DEFAULT_VIDEO,
)


class _MapOnlyCalibrator:
    """Keep the benchmark's localization K fixed at the map K."""

    def __init__(self, K: np.ndarray):
        self._K = np.asarray(K, dtype=np.float64).copy()

    def active_K(self) -> np.ndarray:
        return self._K.copy()

    def submit(self, *_args, **_kwargs) -> bool:
        return False

    def snapshot(self) -> dict:
        return {
            "status": "disabled_for_full_intrinsics_benchmark",
            "committed": False,
            "focal_px": float(self._K[0, 0]),
        }


def _pose_from_correspondences(points_2d, points_3d, K, distortion):
    ok, rvec, tvec = cv2.solvePnP(
        np.asarray(points_3d, dtype=np.float64),
        np.asarray(points_2d, dtype=np.float64),
        np.asarray(K, dtype=np.float64),
        np.asarray(distortion, dtype=np.float64),
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        return None
    R, _ = cv2.Rodrigues(rvec)
    t = np.asarray(tvec, dtype=np.float64).reshape(3)
    position = -R.T @ t
    projected, _ = cv2.projectPoints(
        np.asarray(points_3d, dtype=np.float64), rvec, t.reshape(3, 1),
        np.asarray(K, dtype=np.float64), np.asarray(distortion, dtype=np.float64),
    )
    error = np.linalg.norm(
        projected.reshape(-1, 2) - np.asarray(points_2d, dtype=np.float64), axis=1
    )
    return {
        "R": R,
        "t": t,
        "position": position,
        "median_reproj_px": float(np.median(error)),
        "p95_reproj_px": float(np.percentile(error, 95)),
    }


def _calibrate(views, image_size, initial_K, distortion_model):
    object_points = [np.asarray(view["points_3d"], dtype=np.float32) for view in views]
    image_points = [np.asarray(view["points_2d"], dtype=np.float32) for view in views]
    K0 = np.asarray(initial_K, dtype=np.float64).copy()
    D0 = np.zeros((5, 1), dtype=np.float64)
    flags = cv2.CALIB_USE_INTRINSIC_GUESS
    if distortion_model == "none":
        flags |= (
            cv2.CALIB_ZERO_TANGENT_DIST
            | cv2.CALIB_FIX_K1
            | cv2.CALIB_FIX_K2
            | cv2.CALIB_FIX_K3
            | cv2.CALIB_FIX_K4
            | cv2.CALIB_FIX_K5
            | cv2.CALIB_FIX_K6
        )
    elif distortion_model == "radial2":
        # Estimate only k1/k2.  Tangential and higher-order terms are too
        # weakly observable for a short handheld corridor clip.
        flags |= (
            cv2.CALIB_ZERO_TANGENT_DIST
            | cv2.CALIB_FIX_K3
            | cv2.CALIB_FIX_K4
            | cv2.CALIB_FIX_K5
            | cv2.CALIB_FIX_K6
        )
    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT,
        100,
        1e-7,
    )
    try:
        rms, K, D, rvecs, tvecs, std_K, std_D, per_view_errors = cv2.calibrateCameraExtended(
            object_points,
            image_points,
            image_size,
            K0,
            D0,
            flags=flags,
            criteria=criteria,
        )
    except cv2.error as exc:
        return {"success": False, "error": f"OpenCV calibration failed: {exc}"}

    return {
        "success": True,
        "rms_reproj_px": float(rms),
        "K": np.asarray(K, dtype=np.float64),
        "D": np.asarray(D, dtype=np.float64).reshape(-1),
        "std_K": np.asarray(std_K, dtype=np.float64).reshape(-1),
        "std_D": np.asarray(std_D, dtype=np.float64).reshape(-1),
        "per_view_errors": np.asarray(per_view_errors, dtype=np.float64).reshape(-1),
        "rvecs": rvecs,
        "tvecs": tvecs,
    }


def _plausibility(K, D, image_size, map_K):
    width, height = image_size
    reasons = []
    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])
    if not np.isfinite(K).all() or not np.isfinite(D).all():
        reasons.append("non-finite parameter")
    if fx <= 0 or fy <= 0:
        reasons.append("non-positive focal")
    if not (0.35 * map_K[0, 0] <= fx <= 2.5 * map_K[0, 0]):
        reasons.append("fx outside broad map-relative range")
    if not (0.35 * map_K[1, 1] <= fy <= 2.5 * map_K[1, 1]):
        reasons.append("fy outside broad map-relative range")
    if not (-0.25 * width <= cx <= 1.25 * width):
        reasons.append("cx outside image bounds")
    if not (-0.25 * height <= cy <= 1.25 * height):
        reasons.append("cy outside image bounds")
    if abs(fx - fy) / max(fx, fy, 1e-9) > 0.35:
        reasons.append("fx/fy aspect ratio implausible")
    if np.max(np.abs(D)) > 1.0:
        reasons.append("distortion magnitude too large")
    return len(reasons) == 0, reasons


def _jsonable_matrix(matrix):
    return np.asarray(matrix, dtype=float).tolist()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "full_intrinsics_calibration")
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=12)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-inliers", type=int, default=12)
    parser.add_argument(
        "--distortion-model",
        choices=("none", "radial2", "standard5"),
        default="radial2",
        help="none, k1/k2 only, or standard OpenCV k1/k2/p1/p2/k3",
    )
    args = parser.parse_args()
    # accelerate_localizer may change cwd while preparing the inference stack;
    # resolve output paths before that happens so artifacts stay with this PoC.
    args.out = args.out.resolve()

    localizer = Localizer(
        floor_id="floor1",
        data_dir=args.data_dir,
        floor_plan_path=args.map_image,
        json_map_path=args.graph_json,
        matching_mode="superpoint",
        retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    localizer.debug_mode = False
    map_K = np.asarray(localizer.K, dtype=np.float64).copy()
    # Prevent the existing one-frame P4Pf background path from changing the
    # K while this experiment is collecting a fixed map-K correspondence set.
    localizer.camera_self_calibrator = _MapOnlyCalibrator(map_K)

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(args.step_seconds * fps)))
    frame_indices = list(range(0, frame_count, step))[: int(args.max_frames)]
    views = []
    frame_rows = []
    image_size = None
    for ordinal, frame_index in enumerate(frame_indices, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        image_size = (int(frame.shape[1]), int(frame.shape[0]))
        points_2d, points_3d, result = recover_accepted_correspondences(
            localizer, frame, map_K
        )
        inliers = 0 if points_2d is None else int(len(points_2d))
        accepted = bool(points_2d is not None and inliers >= int(args.min_inliers))
        frame_rows.append({
            "frame": int(frame_index),
            "time_s": round(frame_index / fps, 3),
            "accepted": accepted,
            "inliers": inliers,
            "production_success": bool(result.get("success")),
            "production_reproj_px": result.get("median_reproj_error"),
        })
        if accepted:
            views.append({
                "frame": int(frame_index),
                "points_2d": np.asarray(points_2d, dtype=np.float64),
                "points_3d": np.asarray(points_3d, dtype=np.float64),
            })
        print(
            f"[{ordinal}/{len(frame_indices)}] frame={frame_index} "
            f"accepted={accepted} inliers={inliers}",
            flush=True,
        )
    cap.release()

    if image_size is None or len(views) < 3:
        raise RuntimeError(f"Need at least 3 accepted views; got {len(views)}")

    calibration = _calibrate(views, image_size, map_K, args.distortion_model)
    if not calibration["success"]:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "summary.json").write_text(json.dumps({
            "experiment": "multi-frame full-intrinsics self-calibration",
            "video": str(args.video),
            "accepted_views": len(views),
            "frame_rows": frame_rows,
            "calibration": calibration,
        }, indent=2), encoding="utf-8")
        return

    K_est = calibration["K"]
    D_est = calibration["D"]
    plausible, plausibility_reasons = _plausibility(K_est, D_est, image_size, map_K)
    per_view_errors = calibration["per_view_errors"]
    max_per_view_error = float(np.max(per_view_errors)) if len(per_view_errors) else float("inf")
    if max_per_view_error > 12.0:
        plausibility_reasons.append(
            f"per-view reprojection error too high ({max_per_view_error:.2f}px)"
        )
        plausible = False

    position_rows = []
    for view in views:
        map_pose = _pose_from_correspondences(
            view["points_2d"], view["points_3d"], map_K, np.zeros(5)
        )
        estimated_pose = _pose_from_correspondences(
            view["points_2d"], view["points_3d"], K_est, D_est
        )
        if map_pose is None or estimated_pose is None:
            continue
        delta = float(np.linalg.norm(map_pose["position"] - estimated_pose["position"]))
        position_rows.append({
            "frame": view["frame"],
            "map_median_reproj_px": map_pose["median_reproj_px"],
            "estimated_median_reproj_px": estimated_pose["median_reproj_px"],
            "position_delta_world_units": delta,
        })

    delta_values = [row["position_delta_world_units"] for row in position_rows]
    summary = {
        "experiment": "multi-frame full-intrinsics self-calibration",
        "video": str(args.video),
        "method": (
            "OpenCV calibrateCameraExtended with CALIB_USE_INTRINSIC_GUESS; "
            "one independent pose per accepted view; estimates fx, fy, cx, cy "
            f"and distortion model '{args.distortion_model}'."
        ),
        "coordinate_system": "query features resized to map reference image resolution",
        "map_K": _jsonable_matrix(map_K),
        "map_distortion": [0.0] * 5,
        "image_size": list(image_size),
        "sampled_frames": len(frame_indices),
        "accepted_views": len(views),
        "frame_rows": frame_rows,
        "calibration": {
            "rms_reproj_px": calibration["rms_reproj_px"],
            "estimated_K": _jsonable_matrix(K_est),
            "estimated_distortion": D_est.tolist(),
            "std_K_opencv": calibration["std_K"].tolist(),
            "std_distortion_opencv": calibration["std_D"].tolist(),
            "per_view_reproj_px": per_view_errors.tolist(),
            "max_per_view_reproj_px": max_per_view_error,
            "plausible": plausible,
            "plausibility_reasons": plausibility_reasons,
        },
        "pose_comparison": {
            "views": position_rows,
            "median_position_delta_world_units": float(np.median(delta_values)) if delta_values else None,
            "p95_position_delta_world_units": float(np.percentile(delta_values, 95)) if delta_values else None,
            "median_map_reproj_px": float(np.median([r["map_median_reproj_px"] for r in position_rows])) if position_rows else None,
            "median_estimated_reproj_px": float(np.median([r["estimated_median_reproj_px"] for r in position_rows])) if position_rows else None,
        },
        "decision": {
            "use_full_intrinsics": bool(plausible and calibration["rms_reproj_px"] <= 8.0),
            "fallback": "keep map K and zero distortion when the plausibility/reprojection gate fails",
            "warning": (
                "This benchmark does not prove camera ground truth; full intrinsics can be "
                "weakly observable when the views have little parallax or image coverage."
            ),
        },
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (args.out / "pose_comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        if position_rows:
            writer = csv.DictWriter(handle, fieldnames=list(position_rows[0].keys()))
            writer.writeheader()
            writer.writerows(position_rows)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
