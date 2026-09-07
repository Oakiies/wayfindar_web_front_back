"""Diagnostic only -- does NOT modify production PnP. Tests whether constraining
camera roll/pitch from GeoCalib's gravity estimate (Veicht et al., ECCV 2024)
gives a more stable per-frame heading than the current 6-DoF PnP-RANSAC pose.

Axis convention verified empirically against the map's own known keyframe
poses (10 samples, cos-sim -0.996 to -0.999): GeoCalib's `gravity.vec3d`
equals `-R[:, 1]`, i.e. the world "down" direction (world Y-axis, negated)
expressed in the camera frame. So `R[:, 1] = -gravity.vec3d` fixes 2 of the
3 rotational degrees of freedom (roll, pitch); the remaining 1 DoF is a
rotation about that axis in the world frame, i.e. yaw.

Given R[:, 1] fixed, R(yaw) = R0 @ Ry(yaw) for any valid R0 with
R0[:, 1] == R[:, 1] (constructed once via Gram-Schmidt), and Ry(yaw) is a
rotation about the world Y-axis. For each candidate yaw, translation t is
solved linearly (R, K fixed -> classic "known-rotation" PnP sub-problem via
cross-product/DLT), then reprojection error picks the best yaw.

This uses the SAME already-accepted 2D-3D correspondences the unmodified
pipeline found (via the same wrapper technique as estimate_query_focal.py),
so it changes nothing about retrieval, matching, or the production PnP gate
-- it only asks: on frames the pipeline already succeeded on, would a
gravity-constrained solve give a heading that jumps around less?
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

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

GEOCALIB_PAPER = "https://arxiv.org/abs/2409.06704"


def recover_accepted_correspondences(localizer: Localizer, frame: np.ndarray):
    captured: list[dict] = []
    original_quality = loc.compute_pnp_quality

    def quality_wrapper(points_2d, points_3d, inliers, R, t, k):
        ratio, error = original_quality(points_2d, points_3d, inliers, R, t, k)
        captured.append({
            "points_2d": np.asarray(points_2d, dtype=np.float64).copy(),
            "points_3d": np.asarray(points_3d, dtype=np.float64).copy(),
            "inliers": None if inliers is None else np.asarray(inliers).reshape(-1).copy(),
            "ratio": float(ratio), "error": float(error),
        })
        return ratio, error

    loc.compute_pnp_quality = quality_wrapper
    try:
        result, xy = localizer.localize(frame)
    finally:
        loc.compute_pnp_quality = original_quality

    if not result.get("success") or xy is None:
        return None, None, result

    target_ratio = float(result.get("inlier_ratio", 0.0) or 0.0)
    target_error = result.get("median_reproj_error")
    target_inliers = int(result.get("num_inliers", 0))
    for record in captured:
        n_inliers = 0 if record["inliers"] is None else len(record["inliers"])
        if (n_inliers == target_inliers and abs(record["ratio"] - target_ratio) < 1e-9
                and target_error is not None and abs(record["error"] - float(target_error)) < 1e-9):
            idx = record["inliers"]
            return record["points_2d"][idx], record["points_3d"][idx], result
    return None, None, result


def basis_from_up(up: np.ndarray) -> np.ndarray:
    """Return R0 (3x3, det=+1) with R0[:, 1] == up."""
    up = up / np.linalg.norm(up)
    tmp = np.array([1.0, 0.0, 0.0]) if abs(up[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    v0 = np.cross(tmp, up)
    v0 /= np.linalg.norm(v0)
    v2 = np.cross(up, v0)
    R0 = np.column_stack([v0, up, v2])
    if np.linalg.det(R0) < 0:
        v2 = -v2
        R0 = np.column_stack([v0, up, v2])
    return R0


def yaw_matrix(yaw: float) -> np.ndarray:
    c, s = np.cos(yaw), np.sin(yaw)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def solve_translation_linear(points_2d: np.ndarray, points_3d: np.ndarray, R: np.ndarray, K: np.ndarray) -> np.ndarray:
    """Classic known-rotation PnP sub-problem: solve t linearly via cross-product/DLT."""
    KR = K @ R
    rows_A, rows_b = [], []
    for (u, v), X in zip(points_2d, points_3d):
        y = KR @ X
        # ([u,v,1] x) (K t + y) = 0 -> linear in t
        px = np.array([[0.0, -1.0, v], [1.0, 0.0, -u], [-v, u, 0.0]])
        A = px @ K
        b = -(px @ y)
        rows_A.append(A)
        rows_b.append(b)
    A = np.vstack(rows_A)
    b = np.concatenate(rows_b)
    t, *_ = np.linalg.lstsq(A, b, rcond=None)
    return t


def reproj_error(points_2d, points_3d, R, t, K) -> float:
    rvec, _ = cv2.Rodrigues(R)
    projected, _ = cv2.projectPoints(points_3d, rvec, t.reshape(3, 1), K, np.zeros(4))
    return float(np.median(np.linalg.norm(projected.reshape(-1, 2) - points_2d, axis=1)))


def solve_gravity_constrained_yaw(points_2d, points_3d, K, up_cam, coarse_step_deg=2.0, refine_step_deg=0.1):
    R0 = basis_from_up(up_cam)
    best_yaw, best_err, best_R, best_t = None, float("inf"), None, None
    for yaw_deg in np.arange(-180.0, 180.0, coarse_step_deg):
        yaw = np.radians(yaw_deg)
        R = R0 @ yaw_matrix(yaw)
        t = solve_translation_linear(points_2d, points_3d, R, K)
        err = reproj_error(points_2d, points_3d, R, t, K)
        if err < best_err:
            best_err, best_yaw, best_R, best_t = err, yaw_deg, R, t
    for yaw_deg in np.arange(best_yaw - coarse_step_deg, best_yaw + coarse_step_deg, refine_step_deg):
        yaw = np.radians(yaw_deg)
        R = R0 @ yaw_matrix(yaw)
        t = solve_translation_linear(points_2d, points_3d, R, K)
        err = reproj_error(points_2d, points_3d, R, t, K)
        if err < best_err:
            best_err, best_yaw, best_R, best_t = err, yaw_deg, R, t
    return best_yaw, best_err, best_R, best_t


def get_yaw_from_R(R: np.ndarray) -> float:
    return float(np.degrees(np.arctan2(R[2, 0], R[2, 2])))  # corrected formula, round 2/3


def wrap(a: np.ndarray) -> np.ndarray:
    return (a + 180.0) % 360.0 - 180.0


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
    parser.add_argument("--tag", default="gravity_constrained_heading")
    args = parser.parse_args()

    from geocalib import GeoCalib
    device = "cuda" if torch.cuda.is_available() else "cpu"
    gc_model = GeoCalib().to(device)

    reference_size = find_reference_size(args.data_dir)
    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    localizer.debug_mode = True
    K = localizer.K

    cap = cv2.VideoCapture(str(args.video))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(args.step_seconds * fps)))
    frame_indices = list(range(0, frame_count, step))[: args.max_frames]

    rows = []
    for ordinal, frame_index in enumerate(frame_indices, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        pts2d, pts3d, result = recover_accepted_correspondences(localizer, frame)
        if pts2d is None or len(pts2d) < 6:
            continue

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        t_img = torch.from_numpy(rgb).permute(2, 0, 1).float().to(device) / 255.0
        with torch.no_grad():
            gc_result = gc_model.calibrate(t_img)
        gravity_vec = gc_result["gravity"].vec3d[0].cpu().numpy()
        up_cam = -gravity_vec  # verified: world-up in camera frame = -gravity.vec3d

        yaw_deg, err, R_constrained, t_constrained = solve_gravity_constrained_yaw(pts2d, pts3d, K, up_cam)
        heading_constrained = get_yaw_from_R(R_constrained)

        pose = result.get("pose") or {}
        R_original = np.asarray(pose.get("R"))
        heading_original = get_yaw_from_R(R_original) if R_original is not None else None

        rows.append({
            "frame": frame_index, "time_s": round(frame_index / fps, 3),
            "n_correspondences": len(pts2d),
            "heading_original_deg": heading_original,
            "heading_constrained_deg": heading_constrained,
            "constrained_reproj_error_px": round(err, 3),
            "original_reproj_error_px": result.get("median_reproj_error"),
        })
        print(f"[{ordinal}/{len(frame_indices)}] t={frame_index/fps:6.1f}s "
              f"orig_heading={heading_original:.1f} constrained_heading={heading_constrained:.1f} "
              f"constrained_reproj={err:.2f}px orig_reproj={result.get('median_reproj_error'):.2f}px", flush=True)
    cap.release()

    def step_stats(key):
        vals = [r[key] for r in rows if r[key] is not None]
        if len(vals) < 2:
            return None
        vals = np.array(vals)
        diffs = np.abs(wrap(np.diff(vals)))
        return {"median_step_deg": float(np.median(diffs)), "mean_step_deg": float(np.mean(diffs)), "n": len(vals)}

    args.out.mkdir(parents=True, exist_ok=True)
    import csv
    csv_path = args.out / f"floor1_wide_{args.tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "experiment": "gravity-constrained (GeoCalib) yaw-only PnP vs original 6-DoF PnP heading -- diagnostic, production unchanged",
        "paper": {"GeoCalib (Veicht et al., ECCV 2024)": GEOCALIB_PAPER},
        "axis_convention_check": "validated on 10 map keyframes: gravity.vec3d cos-sim with -R[:,1] = -0.996 to -0.999",
        "n_frames": len(rows),
        "original_heading_step_stats": step_stats("heading_original_deg"),
        "constrained_heading_step_stats": step_stats("heading_constrained_deg"),
        "mean_reproj_error_original_px": float(np.mean([r["original_reproj_error_px"] for r in rows])),
        "mean_reproj_error_constrained_px": float(np.mean([r["constrained_reproj_error_px"] for r in rows])),
        "csv": str(csv_path),
    }
    (args.out / f"floor1_wide_{args.tag}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
