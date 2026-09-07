"""Manhattan-world vanishing-point self-calibration for the query camera.

Motivation: corridors are a textbook Manhattan-world scene (floor/ceiling/wall
edges run along two orthogonal horizontal-ish directions, door/wall edges run
vertical). Classical self-calibration from orthogonal vanishing points --
e.g. Antone & Teller-style Manhattan calibration, and more recent formulations
such as Simon et al., "Vanishing Point Estimation and Line Classification in a
Manhattan World with a Unifying Camera Model" (IJCV 2015,
https://link.springer.com/article/10.1007/s11263-015-0854-5) -- estimates the
focal length from a single image using only line geometry, no learned model,
no map, no change to retrieval/matching/PnP. This is a pure query-side
preprocessing step: it only produces a focal-length estimate to sanity-check
against (or eventually seed) the pipeline's fixed K.

Method (simplified, single image, assumes principal point at image center
which the pipeline already assumes for its own K):
  1. Detect line segments (cv2.createLineSegmentDetector).
  2. Split into a "vertical" group (near +/-90 deg from horizontal) and a
     "horizontal-ish" group (everything else -- candidate corridor-axis
     receding lines).
  3. Fit one vanishing point per group by least-squares line intersection
     (each line contributes ax+by+c=0; solve the homogeneous system).
  4. For two orthogonal directions, (v1-p0).(v2-p0) + f^2 = 0 for a
     zero-skew, square-pixel camera with principal point p0 -- solve for f.

This does not touch the map, retrieval, matcher, or PnP gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for path in (BACKEND_DIR, BACKEND_DIR / "app", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_floor1_wide_production_sweep import DEFAULT_VIDEO, DEFAULT_DATA, find_reference_size  # noqa: E402

MANHATTAN_PAPER = "https://link.springer.com/article/10.1007/s11263-015-0854-5"


def detect_lines(gray: np.ndarray) -> np.ndarray:
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    lines = lsd.detect(gray)[0]
    if lines is None:
        return np.zeros((0, 4), dtype=np.float64)
    return lines.reshape(-1, 4)


def line_coeffs(segments: np.ndarray) -> np.ndarray:
    """ax+by+c=0 for each segment, normalized so (a,b) is unit length."""
    x1, y1, x2, y2 = segments[:, 0], segments[:, 1], segments[:, 2], segments[:, 3]
    a = y2 - y1
    b = x1 - x2
    c = -(a * x1 + b * y1)
    norm = np.hypot(a, b)
    norm = np.where(norm < 1e-9, 1.0, norm)
    return np.stack([a / norm, b / norm, c / norm], axis=1)


def fit_vanishing_point(coeffs: np.ndarray) -> np.ndarray | None:
    """Least-squares intersection of a set of lines ax+by+c=0 -> homogeneous (x,y,1)."""
    if len(coeffs) < 2:
        return None
    A = coeffs[:, :2]
    b = -coeffs[:, 2]
    solution, *_ = np.linalg.lstsq(A, b, rcond=None)
    return np.array([solution[0], solution[1], 1.0])


def ransac_vanishing_point(
    coeffs: np.ndarray, image_diag: float, n_iters: int = 300, inlier_px: float = 3.0,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Find the dominant convergent line cluster instead of pooling every line together.

    A blind least-squares fit over *all* non-vertical lines mixes lines that
    do not actually share a common vanishing point (clutter, text, unrelated
    edges) and produces a meaningless intersection. RANSAC finds the largest
    subset of lines that agree on one vanishing point first, then refits on
    that subset only.
    """
    if len(coeffs) < 2:
        return None
    rng = rng or np.random.default_rng(0)
    best_inliers = None
    best_count = -1
    n = len(coeffs)
    for _ in range(n_iters):
        i, j = rng.choice(n, size=2, replace=False)
        A = coeffs[[i, j], :2]
        b = -coeffs[[i, j], 2]
        if np.linalg.matrix_rank(A) < 2:
            continue
        vp = np.linalg.solve(A, b)
        # distance of candidate VP from every line (a,b unit normal => |a*x+b*y+c| = perpendicular distance)
        dist = np.abs(coeffs[:, 0] * vp[0] + coeffs[:, 1] * vp[1] + coeffs[:, 2])
        inliers = dist < inlier_px
        count = int(inliers.sum())
        if count > best_count:
            best_count = count
            best_inliers = inliers
    if best_inliers is None or best_count < 3:
        return None
    refined = fit_vanishing_point(coeffs[best_inliers])
    if refined is None:
        return None
    return refined, best_inliers


def estimate_focal_from_image(frame: np.ndarray, cx: float, cy: float,
                               min_length: float = 40.0, vertical_band_deg: float = 25.0):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    segments = detect_lines(gray)
    if len(segments) == 0:
        return None

    lengths = np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1])
    segments = segments[lengths >= min_length]
    if len(segments) < 6:
        return None

    angles = np.degrees(np.arctan2(
        segments[:, 3] - segments[:, 1], segments[:, 2] - segments[:, 0]
    ))
    angles = np.abs(((angles + 90.0) % 180.0) - 90.0)  # fold to [0,90), 90=vertical
    vertical_mask = angles > (90.0 - vertical_band_deg)
    horizontal_mask = ~vertical_mask

    diag = float(np.hypot(2 * cx, 2 * cy))
    coeffs = line_coeffs(segments)
    vertical_fit = ransac_vanishing_point(coeffs[vertical_mask], diag)
    horizontal_fit = ransac_vanishing_point(coeffs[horizontal_mask], diag)
    if vertical_fit is None or horizontal_fit is None:
        return None
    vp_vertical, vertical_inliers = vertical_fit
    vp_horizontal, horizontal_inliers = horizontal_fit
    if vertical_inliers.sum() < 6 or horizontal_inliers.sum() < 6:
        return None  # too few agreeing lines to trust either vanishing point

    v1 = np.array([vp_vertical[0] - cx, vp_vertical[1] - cy])
    v2 = np.array([vp_horizontal[0] - cx, vp_horizontal[1] - cy])
    dot = float(np.dot(v1, v2))
    if dot >= 0:
        return None  # orthogonal-VP formula needs a negative dot product
    f = float(np.sqrt(-dot))
    return {
        "focal_px": f,
        "vp_vertical": vp_vertical[:2].tolist(),
        "vp_horizontal": vp_horizontal[:2].tolist(),
        "n_vertical_lines": int(vertical_mask.sum()),
        "n_horizontal_lines": int(horizontal_mask.sum()),
        "n_vertical_inliers": int(vertical_inliers.sum()),
        "n_horizontal_inliers": int(horizontal_inliers.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=53)
    parser.add_argument("--out", type=Path, default=SCRIPT_DIR / "out")
    parser.add_argument("--tag", default="vanishing_point_focal")
    args = parser.parse_args()

    reference_size = find_reference_size(args.data_dir)
    cx, cy = (reference_size[0] - 1.0) / 2.0, (reference_size[1] - 1.0) / 2.0
    map_focal = 1400.0  # from camera.K in existing summaries; kept explicit, not re-derived here

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
        estimate = estimate_focal_from_image(frame, cx, cy)
        if estimate is None:
            print(f"[{ordinal}/{len(frame_indices)}] frame={frame_index} no valid VP pair", flush=True)
            continue
        ratio = estimate["focal_px"] / map_focal
        rows.append({"frame": frame_index, "time_s": round(frame_index / fps, 3),
                      "focal_ratio_query_over_map": ratio, **estimate})
        print(f"[{ordinal}/{len(frame_indices)}] frame={frame_index} "
              f"focal={estimate['focal_px']:.0f} ratio={ratio:.3f} "
              f"(v_lines={estimate['n_vertical_lines']}, h_lines={estimate['n_horizontal_lines']})", flush=True)
    cap.release()

    args.out.mkdir(parents=True, exist_ok=True)
    ratios = [r["focal_ratio_query_over_map"] for r in rows]
    summary = {
        "experiment": "Manhattan vanishing-point focal self-calibration (query-side only)",
        "paper": {"Manhattan self-calibration (Simon et al., IJCV 2015)": MANHATTAN_PAPER},
        "map_focal_px": map_focal,
        "n_frames_with_valid_estimate": len(rows),
        "n_frames_attempted": len(frame_indices),
        "median_focal_ratio_query_over_map": float(np.median(ratios)) if ratios else None,
        "mean_focal_ratio_query_over_map": float(np.mean(ratios)) if ratios else None,
        "std_focal_ratio_query_over_map": float(np.std(ratios)) if ratios else None,
        "rows": rows,
    }
    (args.out / f"floor1_wide_{args.tag}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
