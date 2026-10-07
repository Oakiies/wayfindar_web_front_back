"""Run P4Pf on the full floor5_2 clip at the production 1.5-second cadence."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import time
from pathlib import Path

import cv2

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
APP_DIR = BACKEND_DIR / "app"
for p in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

VIDEO = Path(r"D:\wayfindar\navigate_indoor\uploads\floor5_2.mp4")
DATA = APP_DIR / "data"
OUT = SCRIPT_DIR / "out" / "floor5_2_p4pf_full.jsonl"
SUMMARY = SCRIPT_DIR / "out" / "floor5_2_p4pf_full_summary.json"
ITERATIONS = 128
THRESHOLD = 8.0
SAMPLE_INTERVAL_S = 1.5


def main():
    from app.core.localizer import Localizer
    from app.core.self_calibration import _solve_p4pf

    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {VIDEO}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0

    with contextlib.redirect_stdout(io.StringIO()):
        localizer = Localizer(
            floor_id="floor5", data_dir=DATA / "map_data" / "result_floor5_6",
            floor_plan_path=DATA / "map" / "floor5.jpg",
            json_map_path=DATA / "json_map" / "floor5.json",
            matching_mode="superpoint", retrieval_mode="megaloc",
        )
    localizer.reset_camera_calibration()
    map_K = localizer.map_K.copy()
    cx, cy = float(map_K[0, 2]), float(map_K[1, 2])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    count = valid = sampled = 0
    next_sample_t = 0.0

    with OUT.open("w", encoding="utf-8") as fp:
        while True:
            ok, image = cap.read()
            if not ok:
                break
            idx = count
            t = idx / fps
            count += 1
            if t + 1e-9 < next_sample_t:
                continue
            next_sample_t += SAMPLE_INTERVAL_S
            sampled += 1
            captured = []

            def callback(points_2d, points_3d):
                p4pf = _solve_p4pf(points_2d, points_3d, cx, cy, ITERATIONS, THRESHOLD, idx)
                captured.append({
                    "num_features": int(len(points_2d)),
                    "p4pf_inliers": int(p4pf["inliers"]) if p4pf else None,
                    "p4pf_focal_px": float(p4pf["focal_px"]) if p4pf else None,
                    "p4pf_reproj_px": float(p4pf["median_reproj_error_px"]) if p4pf else None,
                })
                return False

            with contextlib.redirect_stdout(io.StringIO()):
                localizer.localize(image, camera_K=localizer.camera_self_calibrator.active_K(),
                                   calibration_callback=callback)
            if captured:
                rec = {"idx": idx, "t": t, **captured[-1]}
                fp.write(json.dumps(rec) + "\n")
                valid += 1
            if sampled % 10 == 0:
                fp.flush()
                elapsed = time.time() - start
                rate = sampled / max(elapsed, 1e-6)
                remaining = max(0, total / fps - t)
                print(f"sample {sampled}, video t={t:.1f}s/{total/fps:.1f}s, valid={valid}, "
                      f"{rate:.2f} samples/s, ETA={remaining/max(rate, 1e-6)/60:.1f} min", flush=True)

    cap.release()
    summary = {"video": str(VIDEO), "total_frames": total, "fps": fps,
               "sample_interval_s": SAMPLE_INTERVAL_S, "true_focal_px": float(map_K[0, 0]),
               "decoded_frames": count, "sampled_frames": sampled, "valid": valid,
               "elapsed_s": time.time() - start}
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"done: {summary}")


if __name__ == "__main__":
    main()
