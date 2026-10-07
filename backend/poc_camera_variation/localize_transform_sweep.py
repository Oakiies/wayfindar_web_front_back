"""Crop / resize / zoom-in sweep over the normal-lens photos in
backend/evidence/images_compare/<point>/normal/ (floor5 map).

Three independent, digital transforms are applied to each of the 8 photos at
several levels, then localized with the map's own K frozen (no
self-calibration submitted) so the numbers isolate the transform's effect,
the same way the crop/zoom section of REPORT.md does for the floor5_2.mp4
sweep -- this script just reuses real still photos instead of video frames:

  - crop:   center-crop to N% of the original frame, keep native resolution
            (so 90%..25% of width/height, no resize back up)
  - resize: shrink the whole frame to a smaller resolution, same FoV
  - zoomin: center-crop then resize back up to 1920x1080 (crop + zoom, the
            "what a pinch-zoom photo looks like" case)

Each shot's full/original photo is localized once as the baseline; every
transformed variant is compared against that baseline's map position.

Writes out/transform_sweep/results.json and copies transformed jpgs into
out/transform_sweep/images/ for the web viewer, then also drops a data.js
into backend/evidence/transform_sweep/.

Run:
  cd backend/poc_camera_variation
  ..\.venv\Scripts\python.exe localize_transform_sweep.py
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import re
import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
APP_DIR = BACKEND_DIR / "app"
for path in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DATA = APP_DIR / "data"
EVIDENCE_DIR = BACKEND_DIR / "evidence"
COMPARE_DIR = EVIDENCE_DIR / "images_compare"
OUT_DIR = SCRIPT_DIR / "out" / "transform_sweep"
OUT_IMG_DIR = OUT_DIR / "images"
OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

FLOOR_ID = "floor5"
DATA_DIR = DATA / "map_data" / "result_floor5_6"

NUM_RE = re.compile(r"(\d+)")

CROP_LEVELS = [90, 75, 60, 50, 35, 25]       # % of original width/height kept
RESIZE_LEVELS = [1280, 960, 640, 480, 320, 240]  # target long edge, px
ZOOM_LEVELS = [1.2, 1.5, 2.0, 3.0, 4.0]      # crop-then-upscale factor


def collect_normal_shots():
    shots = []
    for folder in sorted(COMPARE_DIR.iterdir(), key=lambda p: int(p.name)):
        if not folder.is_dir():
            continue
        for img_path in sorted(
            folder.glob("normal/*.jpg"),
            key=lambda p: int(NUM_RE.search(p.stem).group(1)),
        ):
            shots.append({"point": folder.name, "path": img_path})
    return shots


def transform_crop(img: np.ndarray, pct: int) -> np.ndarray:
    h, w = img.shape[:2]
    cw, ch = int(round(w * pct / 100)), int(round(h * pct / 100))
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    return img[y0:y0 + ch, x0:x0 + cw]


def transform_resize(img: np.ndarray, long_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = long_edge / max(w, h)
    tw, th = max(1, round(w * scale)), max(1, round(h * scale))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    return cv2.resize(img, (tw, th), interpolation=interp)


def transform_zoomin(img: np.ndarray, factor: float) -> np.ndarray:
    h, w = img.shape[:2]
    cw, ch = int(round(w / factor)), int(round(h / factor))
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    cropped = img[y0:y0 + ch, x0:x0 + cw]
    return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)


def run_localize(localizer, img: np.ndarray, K):
    with contextlib.redirect_stdout(io.StringIO()):
        result, xy = localizer.localize(img, camera_K=K, calibration_callback=lambda *_: False)
    return result, xy


def to_result(result, xy, baseline_xy):
    success = bool(result.get("success")) and xy is not None
    entry = {
        "success": success,
        "xy": [float(xy[0]), float(xy[1])] if xy is not None else None,
        "num_inliers": result.get("num_inliers", 0),
        "num_matches": result.get("num_matches", 0),
    }
    if success and baseline_xy is not None:
        entry["delta_px"] = float(math.hypot(xy[0] - baseline_xy[0], xy[1] - baseline_xy[1]))
    else:
        entry["delta_px"] = None
    return entry


def main():
    from app.core.localizer import Localizer

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

    shots = collect_normal_shots()
    print(f"{len(shots)} normal shots", flush=True)

    MODES = {
        "crop": (CROP_LEVELS, transform_crop, "%"),
        "resize": (RESIZE_LEVELS, transform_resize, "px long edge"),
        "zoomin": (ZOOM_LEVELS, transform_zoomin, "x"),
    }

    shot_results = []
    for shot in shots:
        point, path = shot["point"], shot["path"]
        img = cv2.imread(str(path))
        if img is None:
            raise RuntimeError(f"cv2 failed to read {path}")
        orig_h, orig_w = img.shape[:2]

        base_result, base_xy = run_localize(localizer, img, map_K)
        baseline = to_result(base_result, base_xy, None)
        print(f"  [{point}] {path.name} baseline: {baseline}", flush=True)

        base_out_name = f"{point}_{path.stem}_baseline.jpg"
        cv2.imwrite(str(OUT_IMG_DIR / base_out_name), img)

        entry = {
            "point": point,
            "shot": path.stem,
            "orig_size": [orig_w, orig_h],
            "baseline": baseline,
            "baseline_img": f"images/{base_out_name}",
            "modes": {},
        }

        for mode_name, (levels, transform_fn, unit) in MODES.items():
            variants = []
            for level in levels:
                variant_img = transform_fn(img, level)
                vh, vw = variant_img.shape[:2]
                result, xy = run_localize(localizer, variant_img, map_K)
                r = to_result(result, xy, baseline["xy"])
                out_name = f"{point}_{path.stem}_{mode_name}_{level}.jpg"
                cv2.imwrite(str(OUT_IMG_DIR / out_name), variant_img)
                variants.append({
                    "level": level,
                    "unit": unit,
                    "size": [vw, vh],
                    "img": f"images/{out_name}",
                    **r,
                })
                print(f"    {mode_name} {level}{unit}: {r}", flush=True)
            entry["modes"][mode_name] = variants

        shot_results.append(entry)

    out = {
        "floor_id": FLOOR_ID,
        "map_K": {"f": float(map_K[0, 0]), "cx": float(map_K[0, 2]), "cy": float(map_K[1, 2])},
        "modes_meta": {
            "crop": {"levels": CROP_LEVELS, "unit": "%", "label": "ครอปกลางภาพเหลือ N% ของเฟรม (ไม่ resize กลับ)"},
            "resize": {"levels": RESIZE_LEVELS, "unit": "px", "label": "ย่อทั้งเฟรมให้ด้านยาวเหลือ N px (มุมมองเท่าเดิม)"},
            "zoomin": {"levels": ZOOM_LEVELS, "unit": "x", "label": "ครอปกลางภาพแล้วขยายกลับเป็น 1920x1080 (ซูมอิน N เท่า)"},
        },
        "shots": shot_results,
    }
    out_path = OUT_DIR / "results.json"
    payload = json.dumps(out, indent=2, ensure_ascii=False)
    out_path.write_text(payload, encoding="utf-8")
    print(f"wrote {out_path}", flush=True)

    web_dir = EVIDENCE_DIR / "transform_sweep"
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "data.js").write_text(f"const DATA = {payload};\n", encoding="utf-8")
    print(f"wrote {web_dir / 'data.js'}", flush=True)

    import shutil
    dst_img_dir = web_dir / "images"
    if dst_img_dir.exists():
        shutil.rmtree(dst_img_dir)
    shutil.copytree(OUT_IMG_DIR, dst_img_dir)
    print(f"copied images to {dst_img_dir}", flush=True)


if __name__ == "__main__":
    main()
