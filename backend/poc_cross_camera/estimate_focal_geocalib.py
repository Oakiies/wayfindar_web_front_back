"""GeoCalib (Veicht, Sarlin, Lindenberger, Pollefeys, ECCV 2024) run directly from
the authors' own code/weights -- no re-implementation. This is the one method in
this repo that runs the paper's actual algorithm rather than approximating it.

https://arxiv.org/abs/2409.06704  https://github.com/cvg/GeoCalib

Query-side only: takes a single frame, returns focal length + gravity (roll/pitch).
Does not touch the map, retrieval, matcher, or PnP gates.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for path in (BACKEND_DIR, BACKEND_DIR / "app", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_floor1_wide_production_sweep import DEFAULT_VIDEO, DEFAULT_DATA, find_reference_size  # noqa: E402

GEOCALIB_PAPER = "https://arxiv.org/abs/2409.06704"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=30)
    parser.add_argument("--out", type=Path, default=SCRIPT_DIR / "out")
    parser.add_argument("--tag", default="geocalib")
    args = parser.parse_args()

    from geocalib import GeoCalib

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = GeoCalib().to(device)

    reference_size = find_reference_size(args.data_dir)
    map_focal = 1400.0

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(args.video)
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(args.step_seconds * fps)))
    frame_indices = list(range(0, frame_count, step))[: args.max_frames]

    rows = []
    inference_times = []
    for ordinal, frame_index in enumerate(frame_indices, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image_tensor = torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0
        image_tensor = image_tensor.to(device)

        t0 = time.perf_counter()
        with torch.no_grad():
            result = model.calibrate(image_tensor)
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
        inference_times.append(elapsed)

        camera = result["camera"]
        focal_px = float(camera.f[0].mean().item())
        gravity = result.get("gravity")
        roll = float(torch.rad2deg(gravity.roll).item()) if gravity is not None else None
        pitch = float(torch.rad2deg(gravity.pitch).item()) if gravity is not None else None

        rows.append({
            "frame": frame_index, "time_s": round(frame_index / fps, 3),
            "focal_px": focal_px, "focal_ratio_query_over_map": focal_px / map_focal,
            "roll_deg": roll, "pitch_deg": pitch, "inference_s": elapsed,
        })
        print(f"[{ordinal}/{len(frame_indices)}] frame={frame_index} focal={focal_px:.0f} "
              f"ratio={focal_px/map_focal:.3f} roll={roll:.1f} pitch={pitch:.1f} "
              f"t={elapsed*1000:.1f}ms", flush=True)
    cap.release()

    args.out.mkdir(parents=True, exist_ok=True)
    ratios = [r["focal_ratio_query_over_map"] for r in rows]
    times_ms = np.array(inference_times) * 1000
    summary = {
        "experiment": "GeoCalib (paper's own model/code, ECCV 2024) query focal+gravity estimation",
        "paper": GEOCALIB_PAPER,
        "device": device,
        "map_focal_px": map_focal,
        "n_frames": len(rows),
        "median_focal_ratio_query_over_map": float(np.median(ratios)) if ratios else None,
        "mean_focal_ratio_query_over_map": float(np.mean(ratios)) if ratios else None,
        "std_focal_ratio_query_over_map": float(np.std(ratios)) if ratios else None,
        "inference_latency_ms": {
            "mean": float(times_ms.mean()), "median": float(np.median(times_ms)),
            "max": float(times_ms.max()), "min": float(times_ms.min()),
        },
        "rows": rows,
    }
    (args.out / f"floor1_wide_{args.tag}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
