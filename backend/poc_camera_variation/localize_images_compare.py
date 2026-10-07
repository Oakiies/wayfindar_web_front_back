"""Localize the normal-lens vs. wide(ultrawide)-lens photo pairs in
backend/evidence/images_compare/<point>/{normal,wide}/ on the floor5 map.

Each point folder has 2 shots. Shots are paired within a folder by EXIF
capture time (ascending) on the wide side vs. numeric filename (ascending) on
the normal side -- filenames are not reliable on their own (point 4 has two
wide files both numbered "004").

For every shot this script localizes:
  - normal photo, with the map's own K (matches the app's own capture format:
    1920x1080, no EXIF -- same lens model as the mapping camera)
  - wide photo, with the map's K unmodified ("naive") -- this is what happens
    if the system does not know the lens changed
  - wide photo, with K corrected to a focal estimated by the production
    self-calibrator, pooling P4Pf estimates across all 8 wide photos (they
    are the same physical lens, so one focal estimate applies to all of them)

Converts the source .HEIC files to .jpg next to themselves for the browser
(no HEIC support in browsers) and writes out/images_compare/results.json for
the web viewer.

Run:
  cd backend/poc_camera_variation
  ..\.venv\Scripts\python.exe localize_images_compare.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
APP_DIR = BACKEND_DIR / "app"
for path in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DATA = APP_DIR / "data"
EVIDENCE_DIR = BACKEND_DIR / "evidence"
COMPARE_DIR = EVIDENCE_DIR / "images_compare"
OUT_DIR = SCRIPT_DIR / "out" / "images_compare"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FLOOR_ID = "floor5"
DATA_DIR = DATA / "map_data" / "result_floor5_6"

NUM_RE = re.compile(r"(\d+)")


def heic_datetime(p: Path):
    im = Image.open(p)
    exif = im.getexif()
    return exif.get(306, "")


def convert_heic(p: Path) -> Path:
    """HEIC -> jpg next to the source file, for the browser."""
    out = p.with_suffix(".jpg")
    if not out.exists():
        im = Image.open(p).convert("RGB")
        im.save(out, quality=92)
    return out


def file_md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def wide_sort_key(p: Path):
    # HEIC carries EXIF capture time; a wide/*.jpg dropped in directly (no
    # sibling .HEIC) has none -- fall back to its numeric filename.
    if p.suffix.lower() == ".heic":
        return (0, heic_datetime(p))
    return (1, NUM_RE.search(p.stem).group(1).zfill(6))


def collect_points():
    # Some point folders were assembled by hand and ended up with a shot
    # copied from another point's folder (same photo, byte-for-byte). Detect
    # those across all folders first and drop the later occurrence, so a
    # mislabeled duplicate never gets localized as if it were a real photo of
    # that point.
    seen_hashes: dict[str, Path] = {}

    def dedup(paths):
        kept = []
        for p in paths:
            h = file_md5(p)
            prior = seen_hashes.get(h)
            if prior is not None and prior != p:
                print(f"  skip duplicate: {p} is byte-identical to {prior}", flush=True)
                continue
            seen_hashes[h] = p
            kept.append(p)
        return kept

    points = []
    for folder in sorted(COMPARE_DIR.iterdir(), key=lambda p: int(p.name)):
        if not folder.is_dir():
            continue
        normals = sorted(
            folder.glob("normal/*.jpg"),
            key=lambda p: int(NUM_RE.search(p.stem).group(1)),
        )
        all_wide = list(folder.glob("wide/*"))
        heic_stems = {p.stem.lower() for p in all_wide if p.suffix.lower() == ".heic"}
        wide_files = sorted(
            [
                p for p in all_wide
                if p.suffix.lower() == ".heic"
                or (p.suffix.lower() == ".jpg" and p.stem.lower() not in heic_stems)
            ],
            key=wide_sort_key,
        )
        normals = dedup(normals)
        wide_files = dedup(wide_files)
        if len(normals) != len(wide_files):
            raise RuntimeError(
                f"point {folder.name}: {len(normals)} normal vs {len(wide_files)} wide "
                f"after dedup -- fix the folder before re-running"
            )
        shots = []
        for normal_path, wide_src in zip(normals, wide_files):
            wide_jpg = convert_heic(wide_src) if wide_src.suffix.lower() == ".heic" else wide_src
            shots.append({"normal": normal_path, "wide": wide_jpg})
        points.append({"point": folder.name, "shots": shots})
    return points


def run_localize(localizer, img_path: Path, K):
    img = cv2.imread(str(img_path))
    if img is None:
        raise RuntimeError(f"cv2 failed to read {img_path}")
    with contextlib.redirect_stdout(io.StringIO()):
        result, xy = localizer.localize(img, camera_K=K, calibration_callback=lambda *_: False)
    return result, xy


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

    points = collect_points()
    total_shots = sum(len(p["shots"]) for p in points)
    print(f"{len(points)} points, {total_shots} shots each side", flush=True)

    # 1) normal photos: map K as-is (same capture format as the mapping camera)
    for p in points:
        for shot in p["shots"]:
            result, xy = run_localize(localizer, shot["normal"], map_K)
            shot["normal_result"] = {
                "success": bool(result.get("success")) and xy is not None,
                "xy": [float(xy[0]), float(xy[1])] if xy is not None else None,
                "num_inliers": result.get("num_inliers", 0),
            }
            print(f"  normal {shot['normal'].name}: {shot['normal_result']}", flush=True)

    # 2) wide photos, naive: map K unmodified (lens mismatch not accounted for)
    for p in points:
        for shot in p["shots"]:
            result, xy = run_localize(localizer, shot["wide"], map_K)
            shot["wide_naive_result"] = {
                "success": bool(result.get("success")) and xy is not None,
                "xy": [float(xy[0]), float(xy[1])] if xy is not None else None,
                "num_inliers": result.get("num_inliers", 0),
            }
            print(f"  wide/naive {shot['wide'].name}: {shot['wide_naive_result']}", flush=True)

    # 3) wide photos, self-calibrated: one pooled session across all 8 wide
    #    shots (same physical lens), pass in capture order.
    localizer.reset_camera_calibration()
    ordered_wide_shots = [
        shot for p in points for shot in p["shots"]
    ]
    for shot in ordered_wide_shots:
        img = cv2.imread(str(shot["wide"]))
        active_K = localizer.camera_self_calibrator.active_K()
        with contextlib.redirect_stdout(io.StringIO()):
            result, xy = localizer.localize(img, camera_K=active_K)
        shot["_selfcal_K_used"] = [float(active_K[0, 0]), float(active_K[1, 1])]

    estimates = [e["focal_px"] for e in localizer.camera_self_calibrator._estimates]
    focal_est = float(np.median(estimates)) if estimates else float(map_K[0, 0])
    print(f"wide self-cal estimates: {estimates}", flush=True)
    print(f"wide focal_est (median) = {focal_est:.1f} px (map focal = {map_K[0,0]:.1f} px)", flush=True)

    estK = map_K.copy()
    estK[0, 0] = estK[1, 1] = focal_est
    for shot in ordered_wide_shots:
        result, xy = run_localize(localizer, shot["wide"], estK)
        shot["wide_corrected_result"] = {
            "success": bool(result.get("success")) and xy is not None,
            "xy": [float(xy[0]), float(xy[1])] if xy is not None else None,
            "num_inliers": result.get("num_inliers", 0),
        }
        print(f"  wide/corrected {shot['wide'].name}: {shot['wide_corrected_result']}", flush=True)

    def rel(path: Path) -> str:
        return str(path.relative_to(EVIDENCE_DIR)).replace("\\", "/")

    out = {
        "floor_id": FLOOR_ID,
        "map_K": {"f": float(map_K[0, 0]), "cx": float(map_K[0, 2]), "cy": float(map_K[1, 2])},
        "wide_focal_est": focal_est,
        "wide_selfcal_estimates": estimates,
        "points": [
            {
                "point": p["point"],
                "shots": [
                    {
                        "normal_img": rel(shot["normal"]),
                        "wide_img": rel(shot["wide"]),
                        "normal": shot["normal_result"],
                        "wide_naive": shot["wide_naive_result"],
                        "wide_corrected": shot["wide_corrected_result"],
                    }
                    for shot in p["shots"]
                ],
            }
            for p in points
        ],
    }
    out_path = OUT_DIR / "results.json"
    payload = json.dumps(out, indent=2, ensure_ascii=False)
    out_path.write_text(payload, encoding="utf-8")
    print(f"wrote {out_path}", flush=True)

    web_dir = EVIDENCE_DIR / "images_compare_web"
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "data.js").write_text(f"const DATA = {payload};\n", encoding="utf-8")
    print(f"wrote {web_dir / 'data.js'}", flush=True)


if __name__ == "__main__":
    main()
