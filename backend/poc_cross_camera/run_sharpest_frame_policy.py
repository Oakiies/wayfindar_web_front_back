"""Sharpest-in-window as THE query for every timestamp (not just a fallback).

Round 1's temporal-recovery experiment only tried nearby frames for
timestamps where the exact frame already failed, and called the result
"coverage" rather than same-timestamp success, because that framing lets a
lucky nearby frame count as covering a failure while never being compared to
what would have happened had it been used everywhere. This script applies
the same idea uniformly and honestly: for every one of the 53 canonical
timestamps, pick the sharpest frame within +/-window_s (Laplacian variance,
as in round 1, motivated by Cho & Lee, ICCV 2011) as the query, run it
through the unmodified pipeline, and report success at that timestamp
directly. If the exact frame was already the sharpest, this reduces to the
raw baseline for that timestamp; it never gets extra tries that raw doesn't
also implicitly have available.

Baseline for comparison is the exact-frame run at the same top-k, computed
in the same process so there is no cross-run harness drift.
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
for path in (BACKEND_DIR, BACKEND_DIR / "app", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app.localization_config as localization_config  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA, DEFAULT_GRAPH, DEFAULT_MAP, DEFAULT_OUT, DEFAULT_VIDEO,
    QueryConfig, find_reference_size, run_attempt,
)

BLUR_PAPER = "https://doi.org/10.1109/ICCV.2011.6126370"


def sharpness(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--max-timestamps", type=int, default=53)
    parser.add_argument("--window-s", type=float, default=0.5)
    parser.add_argument("--candidates-in-window", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--tag", default="sharpest_policy")
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

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(args.video)
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(args.step_seconds * fps)))
    target_frames = list(range(0, frame_count, step))[: args.max_timestamps]
    window_frames = max(1, int(round(args.window_s * fps)))

    config = QueryConfig("query", "raw", exact_size=True)
    rows = []
    for ordinal, target_frame in enumerate(target_frames, start=1):
        # baseline: the exact canonical frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, exact_frame = cap.read()
        if not ok:
            continue
        baseline_result, baseline_xy, _e, _o = run_attempt(localizer, exact_frame, config, reference_size)
        baseline_success = bool(baseline_result.get("success")) and baseline_xy is not None

        # candidate pool: evenly spaced offsets within +/-window_frames, ranked by sharpness
        offsets = np.linspace(-window_frames, window_frames, args.candidates_in_window * 2 + 1).astype(int)
        offsets = sorted(set(int(o) for o in offsets))
        candidates = []
        for offset in offsets:
            frame_idx = max(0, min(frame_count - 1, target_frame + offset))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok:
                continue
            candidates.append((frame_idx, offset, sharpness(frame), frame))
        candidates.sort(key=lambda c: c[2], reverse=True)
        sharpest_idx, sharpest_offset, sharpest_val, sharpest_frame = candidates[0]

        sharpest_result, sharpest_xy, _e, _o = run_attempt(localizer, sharpest_frame, config, reference_size)
        sharpest_success = bool(sharpest_result.get("success")) and sharpest_xy is not None

        rows.append({
            "target_frame": target_frame, "target_time_s": round(target_frame / fps, 3),
            "baseline_success": int(baseline_success),
            "sharpest_offset_frames": sharpest_offset, "sharpest_used_exact_frame": int(sharpest_offset == 0),
            "sharpest_value": round(sharpest_val, 2),
            "sharpest_policy_success": int(sharpest_success),
        })
        print(
            f"[{ordinal}/{len(target_frames)}] t={target_frame/fps:6.1f}s "
            f"baseline={int(baseline_success)} sharpest_offset={sharpest_offset:+d} "
            f"policy_success={int(sharpest_success)}", flush=True,
        )
    cap.release()

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"floor1_wide_{args.tag}_topk{args.top_k}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    baseline_n = sum(r["baseline_success"] for r in rows)
    policy_n = sum(r["sharpest_policy_success"] for r in rows)
    gains = sum(1 for r in rows if r["baseline_success"] == 0 and r["sharpest_policy_success"] == 1)
    losses = sum(1 for r in rows if r["baseline_success"] == 1 and r["sharpest_policy_success"] == 0)
    summary = {
        "experiment": "sharpest-frame-in-window as the query for every timestamp (not just failures)",
        "paper": {"Cho & Lee, Simultaneous Localization Mapping and Deblurring (ICCV 2011)": BLUR_PAPER},
        "top_k": args.top_k, "window_s": args.window_s,
        "total_timestamps": len(rows),
        "baseline_same_frame_successes": baseline_n,
        "sharpest_policy_successes": policy_n,
        "per_timestamp_gains": gains, "per_timestamp_losses": losses,
        "net_delta": policy_n - baseline_n,
        "csv": str(csv_path),
    }
    (args.out / f"floor1_wide_{args.tag}_topk{args.top_k}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
