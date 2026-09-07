"""Measure whether image-only focal calibration can finish in a 3-second window.

The model/localizer initialization is reported separately. Three consecutive
video frames are localized after the models are ready; P4Pf calibration is
submitted by the integrated non-blocking callback.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from run_floor1_wide_production_sweep import DEFAULT_DATA, DEFAULT_GRAPH, DEFAULT_MAP, DEFAULT_VIDEO
from run_temporal_landmark_propagation import accelerate_localizer

from app.core.localizer import Localizer
import app.localization_config as localization_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--start-frame", type=int, default=300)
    parser.add_argument("--frame-count", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--out", type=Path, default=Path("out/self_calibration_3frame_window.json"))
    args = parser.parse_args()

    t0 = time.perf_counter()
    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    localizer.debug_mode = False
    model_ready = time.perf_counter()

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(args.video)
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_times = []
    results = []
    window_start = None
    for offset in range(args.frame_count):
        frame_index = args.start_frame + offset
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        if window_start is None:
            window_start = time.perf_counter()
        t_frame = time.perf_counter()
        result, _xy = localizer.localize(frame)
        elapsed = time.perf_counter() - t_frame
        frame_times.append(elapsed)
        results.append({
            "frame": frame_index,
            "success": bool(result.get("success")),
            "inliers": result.get("num_inliers"),
            "elapsed_seconds": elapsed,
            "calibration_snapshot": result.get("camera_calibration"),
        })
    cap.release()

    # The solver is background work. Give it a short scheduling allowance so
    # the benchmark records the commit event, without hiding request latency.
    commit_deadline = (window_start or time.perf_counter()) + 3.0
    while time.perf_counter() < commit_deadline:
        snapshot = localizer.camera_self_calibrator.snapshot()
        if snapshot["committed"] or snapshot["status"] == "unavailable":
            break
        time.sleep(0.01)
    commit_elapsed = time.perf_counter() - (window_start or time.perf_counter())
    summary = {
        "experiment": "three-consecutive-frame image-only self-calibration window",
        "video": str(args.video),
        "start_frame": args.start_frame,
        "frame_count": len(results),
        "model_ready_seconds": model_ready - t0,
        "frame_processing_seconds": frame_times,
        "mean_frame_seconds": sum(frame_times) / len(frame_times) if frame_times else None,
        "window_processing_seconds": sum(frame_times),
        "calibration_commit_elapsed_from_first_frame_seconds": commit_elapsed,
        "final_calibration": localizer.camera_self_calibrator.snapshot(),
        "frames": results,
        "decision": {
            "calibration_after_model_ready_under_3s": bool(commit_elapsed <= 3.0 and localizer.camera_self_calibrator.snapshot()["committed"]),
            "cold_process_under_3s": bool(model_ready - t0 <= 3.0),
            "note": "The model-ready timer is separate because model loading is not calibration work.",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
