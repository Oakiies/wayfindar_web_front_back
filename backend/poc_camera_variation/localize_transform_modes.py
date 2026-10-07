"""crop / resize / zoom-in sweeps on the normal-lens AND wide-lens photos in
backend/evidence/images_compare/<point>/{normal,wide}/*.jpg (floor5).

For every shot and every lens: take the photo (baseline, localized with that
lens's own K) and apply a series of crop / resize / zoom transforms, localize
each transformed image with that *same, unmodified* K (naive -- this is what
the system does if it doesn't know the image was cropped/resized/zoomed), and
record whether it still localizes and how far the result drifts from the
baseline position.

normal uses the map K as-is (matches the mapping camera format).
wide uses a fixed K with the focal estimated in localize_images_compare.py
(pooled self-calibration across all wide photos) -- otherwise the wide
baseline itself would already be wrong before any transform is applied, and
the crop/resize/zoom effect would be impossible to tell apart from the plain
lens-mismatch effect covered in index.html.

Writes:
  backend/evidence/images_compare_web/transforms/<mode>/<point>_<shot>_<lens>_<level>.jpg
  backend/evidence/images_compare_web/transforms_data.js

Run:
  cd backend/poc_camera_variation
  ..\.venv\Scripts\python.exe localize_images_compare.py   # first, to get wide_focal_est
  ..\.venv\Scripts\python.exe localize_transform_modes.py
"""
from __future__ import annotations

import contextlib
import io
import json
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
WEB_DIR = EVIDENCE_DIR / "images_compare_web"
TRANSFORM_DIR = WEB_DIR / "transforms"
IMAGES_COMPARE_RESULTS = SCRIPT_DIR / "out" / "images_compare" / "results.json"

FLOOR_ID = "floor5"
DATA_DIR = DATA / "map_data" / "result_floor5_6"

CROP_LEVELS = [0.9, 0.75, 0.6, 0.5, 0.4, 0.3]
RESIZE_LEVELS = [0.75, 0.5, 0.35, 0.25, 0.15]
ZOOM_LEVELS = [1.25, 1.5, 2.0, 3.0, 4.0]


def even(v: float) -> int:
    return int(round(v / 2) * 2)


def center_crop(img, keep_frac: float):
    h, w = img.shape[:2]
    cw, ch = even(w * keep_frac), even(h * keep_frac)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    return np.ascontiguousarray(img[y0:y0 + ch, x0:x0 + cw])


def whole_resize(img, scale: float):
    h, w = img.shape[:2]
    ow, oh = even(w * scale), even(h * scale)
    return cv2.resize(img, (ow, oh), interpolation=cv2.INTER_AREA)


def zoom_in(img, factor: float):
    """Crop the centre 1/factor of the frame, then upscale back to the
    original resolution -- what a digital-zoom shot looks like."""
    h, w = img.shape[:2]
    cropped = center_crop(img, 1.0 / factor)
    return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)


def collect_shots():
    """Reuse the pairing already established (and hand-verified for the
    point-4 duplicate) by localize_images_compare.py, instead of
    re-deriving normal/wide pairing here."""
    data = json.loads(IMAGES_COMPARE_RESULTS.read_text(encoding="utf-8"))
    shots = []
    for pt in data["points"]:
        for i, shot in enumerate(pt["shots"]):
            shots.append({
                "point": pt["point"], "shot": i,
                "normal": EVIDENCE_DIR / shot["normal_img"],
                "wide": EVIDENCE_DIR / shot["wide_img"],
            })
    return shots


def run_localize(localizer, img, K):
    with contextlib.redirect_stdout(io.StringIO()):
        result, xy = localizer.localize(img, camera_K=K, calibration_callback=lambda *_: False)
    return {
        "success": bool(result.get("success")) and xy is not None,
        "xy": [float(xy[0]), float(xy[1])] if xy is not None else None,
        "num_inliers": result.get("num_inliers", 0),
    }


def dist(a, b):
    if not a or not b or a.get("xy") is None or b.get("xy") is None:
        return None
    return float(np.hypot(a["xy"][0] - b["xy"][0], a["xy"][1] - b["xy"][1]))


def rel(p: Path) -> str:
    return "../images_compare/" + str(p.relative_to(COMPARE_DIR)).replace("\\", "/")


def process_lens(localizer, K, key: str, lens: str, path: Path):
    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    baseline = run_localize(localizer, img, K)
    print(f"[{key}/{lens}] baseline {w}x{h}: {baseline}", flush=True)

    modes_out = {}

    crop_levels = []
    for frac in CROP_LEVELS:
        out_img = center_crop(img, frac)
        oh, ow = out_img.shape[:2]
        fname = f"{key}_{lens}_{int(frac*100)}.jpg"
        cv2.imwrite(str(TRANSFORM_DIR / "crop" / fname), out_img)
        res = run_localize(localizer, out_img, K)
        crop_levels.append({
            "label": f"{int(frac*100)}% ({ow}x{oh})", "frac": frac,
            "img": f"transforms/crop/{fname}", "w": ow, "h": oh,
            "result": res, "drift_px": dist(baseline, res),
        })
        print(f"  crop {frac}: {ow}x{oh} {res}", flush=True)
    modes_out["crop"] = crop_levels

    resize_levels = []
    for scale in RESIZE_LEVELS:
        out_img = whole_resize(img, scale)
        oh, ow = out_img.shape[:2]
        fname = f"{key}_{lens}_{int(scale*100)}.jpg"
        cv2.imwrite(str(TRANSFORM_DIR / "resize" / fname), out_img)
        res = run_localize(localizer, out_img, K)
        resize_levels.append({
            "label": f"{int(scale*100)}% ({ow}x{oh})", "frac": scale,
            "img": f"transforms/resize/{fname}", "w": ow, "h": oh,
            "result": res, "drift_px": dist(baseline, res),
        })
        print(f"  resize {scale}: {ow}x{oh} {res}", flush=True)
    modes_out["resize"] = resize_levels

    zoom_levels = []
    for factor in ZOOM_LEVELS:
        out_img = zoom_in(img, factor)
        oh, ow = out_img.shape[:2]
        fname = f"{key}_{lens}_{str(factor).replace('.', '')}x.jpg"
        cv2.imwrite(str(TRANSFORM_DIR / "zoom" / fname), out_img)
        res = run_localize(localizer, out_img, K)
        zoom_levels.append({
            "label": f"{factor:g}x zoom ({ow}x{oh})", "frac": factor,
            "img": f"transforms/zoom/{fname}", "w": ow, "h": oh,
            "result": res, "drift_px": dist(baseline, res),
        })
        print(f"  zoom {factor}: {ow}x{oh} {res}", flush=True)
    modes_out["zoom"] = zoom_levels

    return {
        "base_img": rel(path), "base_w": w, "base_h": h,
        "baseline": baseline, "modes": modes_out,
    }


def main():
    from app.core.localizer import Localizer

    for mode in ("crop", "resize", "zoom"):
        (TRANSFORM_DIR / mode).mkdir(parents=True, exist_ok=True)

    if not IMAGES_COMPARE_RESULTS.exists():
        raise RuntimeError(
            f"{IMAGES_COMPARE_RESULTS} not found -- run localize_images_compare.py first "
            f"(it estimates the wide-lens focal used here)"
        )
    wide_focal_est = json.loads(IMAGES_COMPARE_RESULTS.read_text(encoding="utf-8"))["wide_focal_est"]

    print(f"loading Localizer({FLOOR_ID}) ...", flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        localizer = Localizer(
            floor_id=FLOOR_ID, data_dir=DATA_DIR,
            floor_plan_path=DATA / "map" / f"{FLOOR_ID}.jpg",
            json_map_path=DATA / "json_map" / f"{FLOOR_ID}.json",
            matching_mode="superpoint", retrieval_mode="megaloc",
        )
    map_K = localizer.map_K.copy()
    wide_K = map_K.copy()
    wide_K[0, 0] = wide_K[1, 1] = wide_focal_est
    print(f"map K f={map_K[0,0]:.1f} cx={map_K[0,2]:.1f} cy={map_K[1,2]:.1f}", flush=True)
    print(f"wide K f={wide_K[0,0]:.1f} (estimated)", flush=True)

    shots = collect_shots()
    print(f"{len(shots)} shots", flush=True)

    out_shots = []
    for shot in shots:
        key = f"{shot['point']}_{shot['shot']}"
        out_shots.append({
            "point": shot["point"], "shot": shot["shot"],
            "lenses": {
                "normal": process_lens(localizer, map_K, key, "normal", shot["normal"]),
                "wide": process_lens(localizer, wide_K, key, "wide", shot["wide"]),
            },
        })

    out = {
        "floor_id": FLOOR_ID,
        "map_K": {"f": float(map_K[0, 0]), "cx": float(map_K[0, 2]), "cy": float(map_K[1, 2])},
        "wide_K": {"f": float(wide_K[0, 0]), "cx": float(wide_K[0, 2]), "cy": float(wide_K[1, 2])},
        "shots": out_shots,
    }
    payload = json.dumps(out, indent=2, ensure_ascii=False)
    (WEB_DIR / "transforms_data.js").write_text(f"const TDATA = {payload};\n", encoding="utf-8")
    print(f"wrote {WEB_DIR / 'transforms_data.js'}", flush=True)


if __name__ == "__main__":
    main()
