"""Run every image we already generated in this investigation through the
production feature-matching pipeline and capture, per image, the raw P4Pf
single-frame estimate: number of matched 2D-3D correspondences ("features"),
P4Pf's inlier count, its reprojection error, and its estimated focal length.

This intercepts the same (points_2d, points_3d) that CameraSelfCalibrator
would receive in production, via Localizer.localize(calibration_callback=...),
and calls the same _solve_p4pf() the production code uses -- but synchronously
and without touching any self-calibration session state, so many images can
be measured independently.

Image sources reused (already on disk from earlier scripts, ~370 images
spanning a wide range of match counts -- heavily cropped/zoomed frames give
few matches, full-resolution frames give many):
  evidence/images_compare/*/{normal,wide}/*.jpg        (floor5, 14 images)
  evidence/images_compare_web/transforms/{crop,resize,zoom}/*.jpg  (floor5, 224)
  evidence/images_compare_web/iphone11/frames/*.jpg    (floor1, 60)

Writes:
  backend/poc_camera_variation/out/p4pf_stats.json

Run:
  cd backend/poc_camera_variation
  ..\.venv\Scripts\python.exe collect_p4pf_stats.py
"""
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
for path in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DATA = APP_DIR / "data"
EVIDENCE_DIR = BACKEND_DIR / "evidence"
WEB_DIR = EVIDENCE_DIR / "images_compare_web"
OUT_DIR = SCRIPT_DIR / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

P4PF_ITERATIONS = 128
P4PF_THRESHOLD_PX = 8.0


def collect_images():
    """(floor_id, data_dir, list of image paths) groups."""
    floor5_images = []
    floor5_images += sorted((EVIDENCE_DIR / "images_compare").glob("*/normal/*.jpg"))
    floor5_images += sorted((EVIDENCE_DIR / "images_compare").glob("*/wide/*.jpg"))
    floor5_images += sorted((WEB_DIR / "transforms").glob("*/*.jpg"))

    floor1_images = sorted((WEB_DIR / "iphone11" / "frames").glob("*.jpg"))

    return [
        ("floor5", DATA / "map_data" / "result_floor5_6", floor5_images),
        ("floor1", DATA / "map_data" / "result_floor1_4", floor1_images),
    ]


def make_capture_callback(records: list, floor_id: str, image_name: str, cx: float, cy: float, seed: int):
    from app.core.self_calibration import _solve_p4pf

    def cb(points_2d, points_3d):
        n_features = len(points_2d)
        p4pf = _solve_p4pf(points_2d, points_3d, cx, cy, P4PF_ITERATIONS, P4PF_THRESHOLD_PX, seed)
        records.append({
            "floor": floor_id, "image": image_name, "num_features": n_features,
            "p4pf_inliers": p4pf["inliers"] if p4pf else None,
            "p4pf_focal_px": p4pf["focal_px"] if p4pf else None,
            "p4pf_reproj_px": p4pf["median_reproj_error_px"] if p4pf else None,
        })
        return False  # never touch self-calibration session state

    return cb


def main():
    from app.core.localizer import Localizer

    groups = collect_images()
    records: list = []

    for floor_id, data_dir, images in groups:
        if not images:
            continue
        print(f"loading Localizer({floor_id}) for {len(images)} images ...", flush=True)
        with contextlib.redirect_stdout(io.StringIO()):
            localizer = Localizer(
                floor_id=floor_id, data_dir=data_dir,
                floor_plan_path=DATA / "map" / f"{floor_id}.jpg",
                json_map_path=DATA / "json_map" / f"{floor_id}.json",
                matching_mode="superpoint", retrieval_mode="megaloc",
            )
        map_K = localizer.map_K.copy()
        cx, cy = float(map_K[0, 2]), float(map_K[1, 2])

        for n, img_path in enumerate(images):
            img = cv2.imread(str(img_path))
            if img is None:
                print(f"  skip unreadable {img_path}", flush=True)
                continue
            before = len(records)
            cb = make_capture_callback(records, floor_id, str(img_path.relative_to(BACKEND_DIR)), cx, cy, seed=n + 1)
            with contextlib.redirect_stdout(io.StringIO()):
                localizer.localize(img, camera_K=map_K, calibration_callback=cb)
            if len(records) == before:
                records.append({
                    "floor": floor_id, "image": str(img_path.relative_to(BACKEND_DIR)),
                    "num_features": 0, "p4pf_inliers": None, "p4pf_focal_px": None, "p4pf_reproj_px": None,
                })
            if (n + 1) % 20 == 0 or n + 1 == len(images):
                print(f"  [{floor_id}] {n+1}/{len(images)}", flush=True)

    out_path = OUT_DIR / "p4pf_stats.json"
    out_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(records)} images)", flush=True)
    have_p4pf = sum(1 for r in records if r["p4pf_focal_px"] is not None)
    print(f"P4Pf produced an estimate for {have_p4pf}/{len(records)} images", flush=True)


if __name__ == "__main__":
    main()
