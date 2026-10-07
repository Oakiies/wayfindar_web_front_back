"""Sample frames from the floor5_2 phone video and localize them on floor5
two ways: with the map K left unmodified (naive -- no idea this phone's lens
differs from the mapping camera) and with production self-calibration (map K
to start, adapts as frames come in, fed in time order like real playback).

Port of localize_iphone11_random_frames.py for the floor5_2 video (this is
the video used elsewhere in backend/new_ar/ for live camera navigation, not
part of the P4Pf offline-stats pipeline -- this script is the first thing
that runs it through self-calibration).

Video: D:\\wayfindar\\navigate_indoor\\uploads\\floor5_2.mp4
       (1920x1080, ~59.94 fps, ~19881 frames, ~332 s)

Writes:
  backend/evidence/floor5_2_web/frames/f<idx>.jpg
  backend/evidence/floor5_2_web/floor5_2_data.js

Run:
  cd backend/poc_camera_variation
  ..\.venv\Scripts\python.exe localize_floor5_2_random_frames.py
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import random
import sys
from pathlib import Path

import cv2

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
APP_DIR = BACKEND_DIR / "app"
for path in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DATA = APP_DIR / "data"
EVIDENCE_DIR = BACKEND_DIR / "evidence"
WEB_DIR = EVIDENCE_DIR / "floor5_2_web"
FRAMES_DIR = WEB_DIR / "frames"

VIDEO = Path(r"D:\wayfindar\navigate_indoor\uploads\floor5_2.mp4")
FLOOR_ID = "floor5"
DATA_DIR = DATA / "map_data" / "result_floor5_6"
N_SAMPLES = 60
SEED = 42


def run_localize(localizer, img, K, calibration_callback=None):
    with contextlib.redirect_stdout(io.StringIO()):
        result, xy = localizer.localize(img, camera_K=K, calibration_callback=calibration_callback)
    return {
        "success": bool(result.get("success")) and xy is not None,
        "xy": [float(xy[0]), float(xy[1])] if xy is not None else None,
        "num_inliers": result.get("num_inliers", 0),
    }, result


def dist(a, b):
    if not a or not b or a.get("xy") is None or b.get("xy") is None:
        return None
    return math.hypot(a["xy"][0] - b["xy"][0], a["xy"][1] - b["xy"][1])


def main():
    from app.core.localizer import Localizer

    FRAMES_DIR.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {VIDEO}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    print(f"{VIDEO.name}: {total} frames @ {fps:.2f} fps", flush=True)

    rng = random.Random(SEED)
    indices = sorted(rng.sample(range(total), N_SAMPLES))

    print(f"loading Localizer({FLOOR_ID}) ...", flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        localizer = Localizer(
            floor_id=FLOOR_ID, data_dir=DATA_DIR,
            floor_plan_path=DATA / "map" / f"{FLOOR_ID}.jpg",
            json_map_path=DATA / "json_map" / f"{FLOOR_ID}.json",
            matching_mode="superpoint", retrieval_mode="megaloc",
        )
    map_K = localizer.map_K.copy()
    print(f"map K f={map_K[0,0]:.1f} cx={map_K[0,2]:.1f} cy={map_K[1,2]:.1f}", flush=True)

    localizer.reset_camera_calibration()

    frames_out = []
    for n, idx in enumerate(indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            print(f"  [{n+1}/{N_SAMPLES}] frame {idx}: read failed, skipping", flush=True)
            continue
        t = idx / fps

        # naive: map K unmodified, must not feed the self-calibration session.
        res_naive, _ = run_localize(localizer, frame, map_K, calibration_callback=lambda *_: False)

        # production: current self-cal K, then let it learn from this frame.
        K_used = localizer.camera_self_calibrator.active_K()
        res_selfcal, full_result = run_localize(localizer, frame, K_used)

        fname = f"f{idx:05d}.jpg"
        cv2.imwrite(str(FRAMES_DIR / fname), frame)
        calib = full_result.get("camera_calibration") or {}
        frames_out.append({
            "idx": idx, "t": round(t, 2),
            "img": f"frames/{fname}",
            "naive": res_naive,
            "selfcal": res_selfcal,
            "drift_px": dist(res_naive, res_selfcal),
            "focal_used": float(K_used[0, 0]),
            "calib_status": calib.get("status", ""),
        })
        print(
            f"  [{n+1}/{N_SAMPLES}] frame {idx} (t={t:.1f}s) f={K_used[0,0]:.0f} "
            f"naive={res_naive} selfcal={res_selfcal}", flush=True,
        )

    cap.release()

    out = {
        "floor_id": FLOOR_ID,
        "video": VIDEO.name,
        "total_frames": total,
        "fps": fps,
        "map_K": {"f": float(map_K[0, 0]), "cx": float(map_K[0, 2]), "cy": float(map_K[1, 2])},
        "frames": frames_out,
    }
    payload = json.dumps(out, indent=2, ensure_ascii=False)
    (WEB_DIR / "floor5_2_data.js").write_text(f"const FLOOR5_2_DATA = {payload};\n", encoding="utf-8")
    print(f"wrote {WEB_DIR / 'floor5_2_data.js'}", flush=True)
    naive_ok = sum(1 for f in frames_out if f["naive"]["success"])
    selfcal_ok = sum(1 for f in frames_out if f["selfcal"]["success"])
    print(f"localized naive={naive_ok}/{len(frames_out)} selfcal={selfcal_ok}/{len(frames_out)}", flush=True)


if __name__ == "__main__":
    main()
