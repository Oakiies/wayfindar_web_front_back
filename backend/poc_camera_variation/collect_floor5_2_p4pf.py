"""Collect per-frame P4Pf statistics for the floor5_2 video samples."""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import cv2

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
APP_DIR = BACKEND_DIR / "app"
for p in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

DATA = APP_DIR / "data"
WEB_DIR = BACKEND_DIR / "evidence" / "floor5_2_web"
INPUT = WEB_DIR / "floor5_2_data.js"
OUTPUT = SCRIPT_DIR / "out" / "floor5_2_p4pf_stats.json"
P4PF_ITERATIONS = 128
P4PF_THRESHOLD_PX = 8.0


def load_js(path: Path):
    text = path.read_text(encoding="utf-8").split("=", 1)[1].strip()
    return json.loads(text[:-1] if text.endswith(";") else text)


def main():
    from app.core.localizer import Localizer
    from app.core.self_calibration import _solve_p4pf

    source = load_js(INPUT)
    frames = sorted(source["frames"], key=lambda x: x["t"])
    with contextlib.redirect_stdout(io.StringIO()):
        localizer = Localizer(
            floor_id="floor5",
            data_dir=DATA / "map_data" / "result_floor5_6",
            floor_plan_path=DATA / "map" / "floor5.jpg",
            json_map_path=DATA / "json_map" / "floor5.json",
            matching_mode="superpoint", retrieval_mode="megaloc",
        )
    localizer.reset_camera_calibration()
    K = localizer.map_K.copy()
    cx, cy = float(K[0, 2]), float(K[1, 2])
    records = []

    for i, item in enumerate(frames, 1):
        image = cv2.imread(str(WEB_DIR / item["img"]))
        if image is None:
            continue
        captured = []

        def callback(points_2d, points_3d):
            p4pf = _solve_p4pf(
                points_2d, points_3d, cx, cy,
                P4PF_ITERATIONS, P4PF_THRESHOLD_PX, seed=int(item["idx"]),
            )
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
            records.append({"idx": item["idx"], "t": item["t"], **captured[-1]})
        print(f"[{i}/{len(frames)}] frame={item['idx']} stats={captured[-1] if captured else None}", flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"true_focal_px": float(K[0, 0]), "records": records}, indent=2), encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(records)} records)")


if __name__ == "__main__":
    main()
