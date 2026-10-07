"""Export results for the standalone viewer (open backend/evidence/web/index.html directly).

Writes backend/evidence/web/:
  data.js              positions per (case, K mode) + focal used, per sample
                       (a script, not JSON, so the page works from file://)
  map/floorN.jpg       floor plans
  frames5/NNNN.jpg     floor5_2.mp4 frame at each localized sample (1 fps)
  frames1/NNNN.jpg     floor1 wide clip frame at each sample
The page applies crop / zoom / resolution transforms to these frames in a
canvas, the same way transform_spec() does, so only the original is stored.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import cv2

from analyze_camera_variation import load
from run_camera_variation import APP_DIR, EVIDENCE_DIR, EXPERIMENTS, sample_frames

OUT = EVIDENCE_DIR / "web"
FRAME_W, FRAME_H, JPEG_Q = 512, 288, 68


def xy_list(rs):
    return [[round(float(r["x_px"]), 1), round(float(r["y_px"]), 1)] if r["success"] == "1" else None for r in rs]


def f_list(rs):
    return [round(float(r["fx_used"])) for r in rs]


def export_frames(exp: str, sub: str, step: float) -> int:
    folder = OUT / sub
    folder.mkdir(parents=True, exist_ok=True)
    samples, _ = sample_frames(EXPERIMENTS[exp]["video"], step, None)
    for n, (_, _, frame) in enumerate(samples):
        small = cv2.resize(frame, (FRAME_W, FRAME_H), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(folder / f"{n:04d}.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    return len(samples)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows5, meta5 = load("floor5")
    rows1, meta1 = load("floor1")
    map_f = meta5["map_K"][0][0]
    n5 = len(rows5[("base", "map")])
    zoom = {v: [float(r["zoom"]) for r in rows5[(v, "map")]] for v in
            ("px540", "crop75", "crop50", "crop43", "zoom2x", "zoomout75", "zoomdyn")}

    def case5(v):
        true_f = [round(map_f * 1920 / 1440)] * n5 if v == "crop43" else [round(map_f * z) for z in zoom[v]]
        return {"map": xy_list(rows5[(v, "map")]), "selfcal": xy_list(rows5[(v, "selfcal")]),
                "f_selfcal": f_list(rows5[(v, "selfcal")]), "f_true": true_f,
                "zoom": [round(z, 3) for z in zoom[v]]}

    data = {
        "floors": {
            "floor5": {
                "map_image": "map/floor5.jpg", "map_size": [500, 500],
                "video": Path(meta5["video"]).name, "step_s": meta5["step_s"], "n": n5,
                "frames": "frames5", "map_f": map_f,
                # "Normal" reference = original image with calibration on (production).
                "reference": xy_list(rows5[("base", "selfcal")]),
                "reference_mapk": xy_list(rows5[("base", "map")]),
                "cases": {v: case5(v) for v in zoom},
            },
            "floor1": {
                "map_image": "map/floor1.jpg", "map_size": [500, 500],
                "video": Path(meta1["video"]).name, "step_s": meta1["step_s"],
                "n": len(rows1[("wide", "map")]), "frames": "frames1", "map_f": meta1["map_K"][0][0],
                "focal_est": round(meta1["focal_est"], 1), "fov_crop": round(meta1["fov_crop"], 4),
                "reference": None,
                "cases": {"wide": {
                    "map": xy_list(rows1[("wide", "map")]), "selfcal": xy_list(rows1[("wide", "selfcal")]),
                    "estK": xy_list(rows1[("wide", "estK")]), "wide_fov": xy_list(rows1[("wide_fov", "map")]),
                    "f_selfcal": f_list(rows1[("wide", "selfcal")]),
                }},
            },
        },
    }
    data["floors"]["floor5"]["frame_count"] = export_frames("floor5", "frames5", meta5["step_s"])
    data["floors"]["floor1"]["frame_count"] = export_frames("floor1", "frames1", meta1["step_s"])
    (OUT / "map").mkdir(exist_ok=True)
    for floor in ("floor5", "floor1"):
        shutil.copy2(APP_DIR / "data" / "map" / f"{floor}.jpg", OUT / "map" / f"{floor}.jpg")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (OUT / "data.js").write_text(f"window.CAMERA_VARIATION_DATA = {payload};\n", encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"wrote {OUT} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
