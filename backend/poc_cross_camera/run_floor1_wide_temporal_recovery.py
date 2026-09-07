"""Recover failed video timestamps with nearby query frames.

This evaluates *temporal coverage*, not single-frame localization accuracy.
The idea follows sequence-based visual localization (e.g. SeqSLAM): a video
provides adjacent observations, so a failed timestamp can be covered by a
nearby frame while keeping the fixed map and visual front-end unchanged.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
START_CWD = Path.cwd()
for path in (BACKEND_DIR, BACKEND_DIR / "app", BACKEND_DIR / "core", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app.localization_config as localization_config  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
from run_floor1_wide_production_sweep import (  # noqa: E402
    DEFAULT_DATA, DEFAULT_GRAPH, DEFAULT_MAP, DEFAULT_OUT, DEFAULT_VIDEO,
    QueryConfig, find_reference_size, run_attempt,
)


SEQUENCE_PAPER = "https://doi.org/10.1109/ICRA.2012.6224623"
BLUR_PAPER = "https://doi.org/10.1109/ICCV.2011.6126370"


def sharpness(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-csv", type=Path, required=True)
    parser.add_argument("--baseline-config", default="raw_production")
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--offsets", default="-0.25,0.25")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--rank-by-sharpness", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=0)
    parser.add_argument("--tag", default="temporal_recovery")
    args = parser.parse_args()

    if not args.baseline_csv.is_absolute():
        args.baseline_csv = (START_CWD / args.baseline_csv).resolve()

    offsets = [float(v.strip()) for v in args.offsets.split(",") if v.strip()]
    with args.baseline_csv.open("r", newline="", encoding="utf-8") as handle:
        source_rows = list(csv.DictReader(handle))
    baseline = [r for r in source_rows if r["config"] == args.baseline_config]
    failed = [r for r in baseline if int(r["success"]) == 0]
    baseline_successes = len(baseline) - len(failed)

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(args.video)
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    reference_size = find_reference_size(args.data_dir)

    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = args.top_k

    config = QueryConfig("raw_temporal", "raw", exact_size=False)
    attempts: list[dict] = []
    recovered_targets: set[int] = set()
    for ordinal, row in enumerate(failed, start=1):
        target_frame = int(row["frame"])
        print(f"[{ordinal}/{len(failed)}] target={target_frame}", flush=True)
        candidates = []
        for offset_s in offsets:
            query_frame = max(0, min(frame_count - 1, target_frame + round(offset_s * fps)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, query_frame)
            ok, frame = cap.read()
            if not ok:
                continue
            candidates.append((offset_s, query_frame, frame, sharpness(frame)))
        if args.rank_by_sharpness:
            candidates.sort(key=lambda item: item[3], reverse=True)
        if args.max_attempts > 0:
            candidates = candidates[:args.max_attempts]
        for offset_s, query_frame, frame, frame_sharpness in candidates:
            result, xy, elapsed, observer = run_attempt(localizer, frame, config, reference_size)
            success = bool(result.get("success")) and xy is not None
            attempts.append({
                "target_frame": target_frame,
                "target_time_s": round(target_frame / fps, 3),
                "query_frame": query_frame,
                "query_offset_s": offset_s,
                "query_sharpness": round(frame_sharpness, 3),
                "success": int(success),
                "x_px": round(float(xy[0]), 3) if success else "",
                "y_px": round(float(xy[1]), 3) if success else "",
                "matched_keyframe": result.get("matched_keyframe") or "",
                "num_matches": int(result.get("num_matches", 0)),
                "num_inliers": int(result.get("num_inliers", 0)),
                "inlier_ratio": float(result.get("inlier_ratio", 0.0)),
                "median_reproj_error": result.get("median_reproj_error") if result.get("median_reproj_error") is not None else "",
                "max_candidate_matches": observer.max_matches,
                "max_raw_pnp_inliers": observer.max_raw_inliers,
                "elapsed_s": round(elapsed, 3),
            })
            print(
                f"  offset={offset_s:+.2f}s ok={int(success)} "
                f"raw_inliers={observer.max_raw_inliers}", flush=True,
            )
            if success:
                recovered_targets.add(target_frame)
                break
    cap.release()

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"floor1_wide_{args.tag}.csv"
    fields = list(attempts[0].keys()) if attempts else []
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(attempts)

    covered = baseline_successes + len(recovered_targets)
    summary = {
        "metric": "timestamp coverage using a nearby frame; not same-frame success",
        "baseline_csv": str(args.baseline_csv),
        "baseline_config": args.baseline_config,
        "baseline_successes": baseline_successes,
        "total_timestamps": len(baseline),
        "failed_timestamps_tested": len(failed),
        "offsets_seconds": offsets,
        "rank_by_sharpness": args.rank_by_sharpness,
        "max_attempts_per_timestamp": args.max_attempts or len(offsets),
        "recovered_timestamps": len(recovered_targets),
        "covered_timestamps": covered,
        "coverage_rate": covered / len(baseline) if baseline else 0.0,
        "top_k": args.top_k,
        "pipeline": "MegaLoc + SuperPoint/LightGlue + PnP, fixed existing map",
        "papers": {
            "SeqSLAM": SEQUENCE_PAPER,
            "Simultaneous Localization Mapping and Deblurring": BLUR_PAPER,
        },
        "output_csv": str(csv_path),
    }
    summary_path = args.out / f"floor1_wide_{args.tag}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
