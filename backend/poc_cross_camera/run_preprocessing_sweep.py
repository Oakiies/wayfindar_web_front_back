"""Query-side preprocessing sweep targeting the blur / low-texture bottleneck.

Rounds 2-3 (see EXPERIMENT-REPORT.md) established that FoV/intrinsics
mismatch is NOT the dominant cause of failures on floor1_wide.MOV: a
controlled A/B at matched top-k showed no reliable gain from virtual-camera
reprojection, while failing frames have much lower Laplacian sharpness than
succeeding ones (round 1, finding #7) and the scene is a repetitive,
texture-poor corridor. This script attacks that bottleneck directly with
cheap, established query-side preprocessing -- no map change, no retrieval/
matcher/PnP change, same quality gates:

  - CLAHE (Contrast-Limited Adaptive Histogram Equalization): used inside
    ORB-SLAM2 and other visual-SLAM front ends specifically to recover more
    keypoints in low-texture / low-contrast scenes without the noise blow-up
    of plain histogram equalization.
  - Unsharp masking: a classical, cheap counter to mild motion blur. Flagged
    here as a gamble, not an established win -- deblur-then-detect pipelines
    are known to sometimes introduce restoration artifacts that hurt more
    than help (see EXPERIMENT-REPORT round 4 notes), so it is tested and
    measured, not assumed.

Every config is run at multiple top-k values because round 2 showed a gain
at top-k4 can vanish at top-k20 (headroom saturates), and every full run is
compared against the noise floor already measured from repeated identical
runs (~2/27, i.e. do not trust deltas smaller than that without a repeat).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for path in (BACKEND_DIR, BACKEND_DIR / "app", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app.localization_config as localization_config  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA, DEFAULT_GRAPH, DEFAULT_MAP, DEFAULT_OUT, DEFAULT_VIDEO,
    find_reference_size, run_attempt, QueryConfig as _BaseConfig,
)

CLAHE_PAPER = "ORB-SLAM2 / common visual-SLAM front-end practice for low-texture scenes"


def apply_clahe(frame: np.ndarray, clip_limit: float = 2.0, tile: int = 8) -> np.ndarray:
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l_channel, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile, tile))
    l_eq = clahe.apply(l_channel)
    return cv2.cvtColor(cv2.merge((l_eq, a, b)), cv2.COLOR_LAB2BGR)


def apply_unsharp(frame: np.ndarray, sigma: float = 1.5, amount: float = 1.0) -> np.ndarray:
    blurred = cv2.GaussianBlur(frame, (0, 0), sigma)
    return cv2.addWeighted(frame, 1.0 + amount, blurred, -amount, 0)


PREPROCESSORS = {
    "raw": lambda f: f,
    "clahe": apply_clahe,
    "unsharp": apply_unsharp,
    "clahe_unsharp": lambda f: apply_unsharp(apply_clahe(f)),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=53)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--configs", default="raw,clahe,unsharp,clahe_unsharp")
    parser.add_argument("--tag", default="preprocessing_sweep")
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

    names = [c.strip() for c in args.configs.split(",") if c.strip()]
    dummy_config = _BaseConfig("query", "raw", exact_size=True)  # exact_size=True: use 1920x1080, matches round-1/2 best config

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
        for name in names:
            processed = PREPROCESSORS[name](frame)
            result, xy, elapsed, observer = run_attempt(localizer, processed, dummy_config, reference_size)
            success = bool(result.get("success")) and xy is not None
            rows.append({
                "frame": frame_index, "time_s": round(frame_index / fps, 3), "config": name,
                "success": int(success),
                "num_matches": int(result.get("num_matches", 0)),
                "num_inliers": int(result.get("num_inliers", 0)),
                "inlier_ratio": float(result.get("inlier_ratio", 0.0)),
                "median_reproj_error": result.get("median_reproj_error") if result.get("median_reproj_error") is not None else "",
                "max_candidate_matches": observer.max_matches,
                "elapsed_s": round(elapsed, 3),
            })
        print(
            f"[{ordinal}/{len(frame_indices)}] frame={frame_index} " +
            " ".join(f"{name}={rows[-len(names) + i]['success']}" for i, name in enumerate(names)),
            flush=True,
        )
    cap.release()

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"floor1_wide_{args.tag}_topk{args.top_k}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    per_config = {}
    for name in names:
        selected = [r for r in rows if r["config"] == name]
        successes = sum(r["success"] for r in selected)
        per_config[name] = {
            "attempts": len(selected), "successes": successes,
            "success_rate": successes / len(selected) if selected else 0.0,
        }
    summary = {
        "experiment": "query-side preprocessing sweep (CLAHE / unsharp) targeting blur+low-texture bottleneck",
        "top_k": args.top_k, "configs": names, "per_config": per_config,
        "papers": {"CLAHE in visual SLAM front-ends": CLAHE_PAPER},
        "csv": str(csv_path),
    }
    summary_path = args.out / f"floor1_wide_{args.tag}_topk{args.top_k}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
