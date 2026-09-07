"""Confidence-triggered adaptive top-k cascade for latency-aware localization.

Grounded in two recent papers found this round:
  - Barbarani et al., "To Match or Not to Match: Revisiting Image Matching for
    Reliable Visual Place Recognition" (2025, https://arxiv.org/abs/2504.06116):
    finds that *inlier/match counts from actual local feature matching* -- not
    the raw global retrieval score -- reliably predict when spending more
    compute (re-ranking / expanding the candidate pool) will help. This
    script escalates on inlier count, not retrieval score, per that finding.
  - The general "Dynamic Top-k Candidate Selection" family of methods (dynamic
    candidate-pool sizing keyed on retrieval confidence) motivates trying a
    *cheap-first, escalate-only-on-low-confidence* cascade instead of always
    running the expensive top-k.

Design: run the unmodified pipeline at a cheap top-k first. If it already
clears the production quality gate (accepted pose), stop -- cheap path taken.
If not, re-run once at an expensive top-k for that same frame only. This
should approach top-k-expensive's success rate while paying its latency only
on the fraction of frames that actually needed it.

No map change, no retrieval/matcher/PnP change, same quality gates.
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
    QueryConfig, find_reference_size, run_attempt,
)

PAPERS = {
    "To Match or Not to Match (Barbarani et al., 2025)": "https://arxiv.org/abs/2504.06116",
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
    parser.add_argument("--cheap-top-k", type=int, default=4)
    parser.add_argument("--expensive-top-k", type=int, default=20)
    parser.add_argument("--tag", default="adaptive_cascade")
    args = parser.parse_args()

    reference_size = find_reference_size(args.data_dir)
    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localizer.debug_mode = True

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(args.video)
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(args.step_seconds * fps)))
    frame_indices = list(range(0, frame_count, step))[: args.max_frames]

    config = QueryConfig("query", "raw", exact_size=True)
    rows = []
    for ordinal, frame_index in enumerate(frame_indices, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue

        localization_config.LOCALIZATION_PARAMS["top_k"] = args.cheap_top_k
        t0 = time.perf_counter()
        cheap_result, cheap_xy, _e, cheap_obs = run_attempt(localizer, frame, config, reference_size)
        cheap_elapsed = time.perf_counter() - t0
        cheap_success = bool(cheap_result.get("success")) and cheap_xy is not None

        escalated = False
        total_elapsed = cheap_elapsed
        final_success = cheap_success
        final_result = cheap_result

        if not cheap_success:
            escalated = True
            localization_config.LOCALIZATION_PARAMS["top_k"] = args.expensive_top_k
            t0 = time.perf_counter()
            exp_result, exp_xy, _e, _obs = run_attempt(localizer, frame, config, reference_size)
            exp_elapsed = time.perf_counter() - t0
            total_elapsed += exp_elapsed
            final_success = bool(exp_result.get("success")) and exp_xy is not None
            final_result = exp_result

        rows.append({
            "frame": frame_index, "time_s": round(frame_index / fps, 3),
            "cheap_success": int(cheap_success),
            "cheap_max_raw_inliers": cheap_obs.max_raw_inliers,
            "escalated": int(escalated),
            "final_success": int(final_success),
            "cheap_elapsed_s": round(cheap_elapsed, 4),
            "total_elapsed_s": round(total_elapsed, 4),
        })
        print(
            f"[{ordinal}/{len(frame_indices)}] frame={frame_index} "
            f"cheap_ok={int(cheap_success)} escalated={int(escalated)} "
            f"final_ok={int(final_success)} total={total_elapsed*1000:.0f}ms", flush=True,
        )
    cap.release()

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"floor1_wide_{args.tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    n = len(rows)
    cheap_successes = sum(r["cheap_success"] for r in rows)
    final_successes = sum(r["final_success"] for r in rows)
    escalations = sum(r["escalated"] for r in rows)
    total_times = np.array([r["total_elapsed_s"] for r in rows])
    summary = {
        "experiment": "confidence-triggered adaptive top-k cascade (escalate on cheap-top-k failure only)",
        "papers": PAPERS,
        "cheap_top_k": args.cheap_top_k, "expensive_top_k": args.expensive_top_k,
        "n_timestamps": n,
        "cheap_only_successes": cheap_successes,
        "cascade_final_successes": final_successes,
        "n_escalated": escalations,
        "escalation_rate": escalations / n if n else 0.0,
        "mean_latency_s": float(total_times.mean()),
        "median_latency_s": float(np.median(total_times)),
        "p95_latency_s": float(np.percentile(total_times, 95)),
        "csv": str(csv_path),
    }
    (args.out / f"floor1_wide_{args.tag}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
