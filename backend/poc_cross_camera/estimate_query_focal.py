"""Map-grounded query-focal-length check (no new dependency, no map change).

Motivation: PnP-only pipelines (this one included) implicitly assume the query
camera shares the map's intrinsics. Camera-with-unknown-focal-length PnP
("PnPf") is a known relaxation of this assumption, solved in closed form by
e.g. Kukelova et al., "Real-time solution to the absolute pose problem with
unknown radial distortion and focal length" (ICCV 2013, P4Pfr/P5Pfr) and
Zheng & Kneip's earlier PnPf solvers (arXiv 1903.xxxx family). This script
does not implement those Groebner-basis solvers; instead it does the cheapest
thing that answers the same question with tools already in this repo: take
the 2D-3D inlier correspondences the *unmodified* pipeline already found on
successful frames, and grid-search a single shared focal length f (fx=fy=f,
principal point fixed at the map's cx,cy) to see whether a focal far from the
map's own K=1400 fits those same correspondences better.

If the best-fit f clusters near the map's 1400, the query camera's FoV is not
actually mismatched for this clip, and HFoV-sweep / self-calibration (e.g.
GeoCalib, Veicht et al., ECCV 2024) work is not where the remaining failures
come from. If best-fit f clusters far from 1400, the FoV-mismatch hypothesis
is supported and self-calibration becomes worth the added dependency.

Nothing here changes the map, the retrieval model, the matcher, or the PnP
quality gates used in production; it only re-analyzes correspondences that
gate already accepted.
"""

from __future__ import annotations

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
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA, DEFAULT_GRAPH, DEFAULT_MAP, DEFAULT_OUT, DEFAULT_VIDEO,
    find_reference_size,
)

P4PFR_PAPER = (
    "https://openaccess.thecvf.com/content_iccv_2013/html/"
    "Kukelova_Real-Time_Solution_to_2013_ICCV_paper.html"
)
GEOCALIB_PAPER = "https://arxiv.org/abs/2409.06704"

FOCAL_GRID = np.arange(500.0, 3000.0 + 1.0, 20.0)


def recover_accepted_correspondences(localizer: Localizer, frame: np.ndarray, K: np.ndarray):
    """Return (points_2d[inliers], points_3d[inliers]) for the pose the pipeline accepted."""
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
        if (
            n_inliers == target_inliers
            and abs(record["ratio"] - target_ratio) < 1e-9
            and target_error is not None
            and abs(record["error"] - float(target_error)) < 1e-9
        ):
            idx = record["inliers"]
            return record["points_2d"][idx], record["points_3d"][idx], result
    return None, None, result


def best_focal(points_2d: np.ndarray, points_3d: np.ndarray, cx: float, cy: float) -> tuple[float, float]:
    """Grid-search a single shared focal length minimizing median reprojection error.

    R, t are re-solved (SOLVEPNP_ITERATIVE, using the existing inlier set as the
    full correspondence set) for every candidate f; this is a coarse stand-in
    for a closed-form PnPf solver, adequate for a direction-of-mismatch check.
    """
    if len(points_2d) < 4:
        return float("nan"), float("nan")
    best_f, best_err = float("nan"), float("inf")
    for f in FOCAL_GRID:
        k = np.array([[f, 0.0, cx], [0.0, f, cy], [0.0, 0.0, 1.0]], dtype=np.float64)
        ok, rvec, tvec = cv2.solvePnP(
            points_3d, points_2d, k, np.zeros(4), flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            continue
        projected, _ = cv2.projectPoints(points_3d, rvec, tvec, k, np.zeros(4))
        errors = np.linalg.norm(projected.reshape(-1, 2) - points_2d, axis=1)
        median_err = float(np.median(errors))
        if median_err < best_err:
            best_err = median_err
            best_f = float(f)
    return best_f, best_err


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=53)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--tag", default="focal_estimate_topk4")
    args = parser.parse_args()

    reference_size = find_reference_size(args.data_dir)
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

    rows = []
    for ordinal, frame_index in enumerate(frame_indices, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        pts2d, pts3d, result = recover_accepted_correspondences(localizer, frame, localizer.K)
        if pts2d is None:
            print(f"[{ordinal}/{len(frame_indices)}] frame={frame_index} no accepted pose, skip", flush=True)
            continue
        f_hat, med_err = best_focal(pts2d, pts3d, cx, cy)
        rows.append({
            "frame": frame_index,
            "time_s": round(frame_index / fps, 3),
            "num_inliers_used": int(len(pts2d)),
            "map_focal_px": map_f,
            "best_fit_focal_px": f_hat,
            "focal_ratio_query_over_map": f_hat / map_f if np.isfinite(f_hat) else None,
            "best_fit_median_reproj_error_px": med_err,
            "production_median_reproj_error_px": result.get("median_reproj_error"),
        })
        print(
            f"[{ordinal}/{len(frame_indices)}] frame={frame_index} "
            f"inliers={len(pts2d)} best_f={f_hat:.0f} (map={map_f:.0f}, "
            f"ratio={f_hat / map_f:.3f}) reproj={med_err:.2f}px",
            flush=True,
        )
    cap.release()

    if not rows:
        print("No successful frames to analyze.")
        return

    ratios = [r["focal_ratio_query_over_map"] for r in rows if r["focal_ratio_query_over_map"] is not None]
    args.out.mkdir(parents=True, exist_ok=True)
    tag = args.tag
    csv_path = args.out / f"floor1_wide_{tag}.csv"
    import csv as csv_mod

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv_mod.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "experiment": "map-grounded query focal-length check via grid search on accepted inlier correspondences",
        "method_note": (
            "Grid search over shared f (500-3000px step 20), R/t re-solved per candidate via "
            "SOLVEPNP_ITERATIVE on the already-accepted inlier set. This is a coarse stand-in for "
            "a closed-form PnPf solver, used only to test the direction/magnitude of any focal mismatch."
        ),
        "map_focal_px": map_f,
        "n_frames_analyzed": len(rows),
        "median_focal_ratio_query_over_map": float(np.median(ratios)) if ratios else None,
        "mean_focal_ratio_query_over_map": float(np.mean(ratios)) if ratios else None,
        "std_focal_ratio_query_over_map": float(np.std(ratios)) if ratios else None,
        "interpretation": (
            "ratio near 1.0 => query and map focal length agree; the clip's failures are not explained "
            "by a focal/FoV mismatch, so HFoV-sweep and single-image self-calibration should not be "
            "expected to move success rate. ratio far from 1.0 => mismatch is real and self-calibration "
            "(e.g. GeoCalib) is worth the added dependency."
        ),
        "papers": {"PnPf/P4Pfr (Kukelova et al., ICCV 2013)": P4PFR_PAPER, "GeoCalib (Veicht et al., ECCV 2024)": GEOCALIB_PAPER},
        "csv": str(csv_path),
    }
    summary_path = args.out / f"floor1_wide_{tag}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
