"""Run P4Pf on every labeled query image available for floors 1-6."""
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
PROJECT_DIR = BACKEND_DIR.parent.parent
LABEL_ROOT = PROJECT_DIR / "visualize" / "data" / "test-queries"
OUT = SCRIPT_DIR / "out" / "p4pf_labeled_all_floors.json"
ITERATIONS = 128
THRESHOLD = 8.0

for p in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def main():
    from app.core.localizer import Localizer
    from app.core.self_calibration import _solve_p4pf

    data = APP_DIR / "data"
    records = []
    floor_counts = {}
    for floor_id in [f"floor{i}" for i in range(1, 7)]:
        image_paths = sorted((LABEL_ROOT / f"label_{floor_id}").glob("*"))
        image_paths = [p for p in image_paths if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        floor_counts[floor_id] = len(image_paths)
        if not image_paths:
            continue
        data_dir = data / "map_data" / {
            "floor1": "result_floor1_4", "floor2": "result_floor2_6",
            "floor3": "result_floor3_6", "floor4": "result_floor4_5",
            "floor5": "result_floor5_6", "floor6": "result_floor6_2",
        }[floor_id]
        print(f"loading {floor_id}: {len(image_paths)} labeled images", flush=True)
        with contextlib.redirect_stdout(io.StringIO()):
            localizer = Localizer(
                floor_id=floor_id, data_dir=data_dir,
                floor_plan_path=data / "map" / f"{floor_id}.jpg",
                json_map_path=data / "json_map" / f"{floor_id}.json",
                matching_mode="superpoint", retrieval_mode="megaloc",
            )
        K = localizer.map_K.copy()
        cx, cy = float(K[0, 2]), float(K[1, 2])
        true_focal = float(K[0, 0])
        for n, path in enumerate(image_paths, 1):
            image = cv2.imread(str(path))
            capture = []

            def callback(points_2d, points_3d):
                estimate = _solve_p4pf(
                    points_2d, points_3d, cx, cy, ITERATIONS, THRESHOLD,
                    seed=(n * 1009 + int(floor_id[-1])),
                )
                capture.append({
                    "num_features": int(len(points_2d)),
                    "p4pf_inliers": int(estimate["inliers"]) if estimate else None,
                    "p4pf_focal_px": float(estimate["focal_px"]) if estimate else None,
                    "p4pf_reproj_px": float(estimate["median_reproj_error_px"]) if estimate else None,
                })
                return False

            if image is not None:
                with contextlib.redirect_stdout(io.StringIO()):
                    localizer.localize(image, camera_K=K, calibration_callback=callback)
            row = capture[-1] if capture else {
                "num_features": 0, "p4pf_inliers": None,
                "p4pf_focal_px": None, "p4pf_reproj_px": None,
            }
            records.append({
                "floor": floor_id, "image": str(path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                "true_focal_px": true_focal, **row,
            })
            if n % 10 == 0 or n == len(image_paths):
                print(f"  {floor_id}: {n}/{len(image_paths)}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"floor_counts": floor_counts, "records": records}, indent=2), encoding="utf-8")
    valid = [r for r in records if r["p4pf_focal_px"] is not None]
    print(f"wrote {OUT}: {len(records)} labeled images, {len(valid)} valid P4Pf estimates", flush=True)
    print(f"floor counts: {floor_counts}", flush=True)


if __name__ == "__main__":
    main()
