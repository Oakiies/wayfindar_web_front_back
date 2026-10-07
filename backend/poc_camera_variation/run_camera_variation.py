"""Offline sweep: how crop / zoom / a different camera change the localized position.

Each (variant x K-mode) is one temporal pass over the sampled frames with its
own camera self-calibration session, so the online focal estimator of one
variant never sees frames of another.

Experiments
  floor5  (D:/video/floor5_2.mp4, same camera model as the map)
    base       original 1920x1080
    px540      whole view downscaled to 960x540      -> fewer pixels, same FoV
    crop75     centre crop 1440x810                  -> same lens, smaller sensor
    crop50     centre crop 960x540                   -> same lens, smaller sensor
    crop43     centre crop 1440x1080 (4:3 phone)     -> system stretches to 16:9
    zoom2x     crop50 upscaled back to 1920x1080     -> digital zoom-in
    zoomout75  view shrunk to 75 % and padded black  -> wider virtual lens
    zoomdyn    zoom sweeps 1x -> 2x -> 1x every 120 s (output 1920x1080)
  floor1  (Downloads/floor1_pare_wide_mp4.mp4, different phone, wide lens)
    wide       as recorded
    wide_fov   centre crop to the map camera FoV (uses focal estimated below)

K modes
  map      the map K is used as-is (no adaptation)
  selfcal  production behaviour: map K first, CameraSelfCalibrator adapts focal
  oracle   (floor5) the exact K implied by the transform
  estK     (floor1) fixed K with focal = median of the selfcal P4Pf estimates

The system resizes every query to (2cx, 2cy) of K before feature extraction
(localization.resize_query_image), so the oracle K is expressed in that
reference pixel space.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import math
import sys
import time
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
OUT_DIR = SCRIPT_DIR / "out"
# Deliverables (viewer, evidence images, videos) live outside the PoC folder.
EVIDENCE_DIR = BACKEND_DIR / "evidence"

EXPERIMENTS = {
    "floor5": {
        "video": Path(r"D:\video\floor5_2.mp4"),
        "floor_id": "floor5",
        "data_dir": DATA / "map_data" / "result_floor5_6",
        "variants": ["base", "px540", "crop75", "crop50", "crop43", "zoom2x", "zoomout75", "zoomdyn"],
    },
    "floor1": {
        "video": Path.home() / "Downloads" / "floor1_pare_wide_mp4.mp4",
        "floor_id": "floor1",
        "data_dir": DATA / "map_data" / "result_floor1_4",
        "variants": ["wide", "wide_fov"],
    },
}

# Transform specs. Every transform is an axis-aligned affine from source pixel
# to output pixel: out = s * src + t, with an output canvas (w, h).
ZOOM_PERIOD_S = 120.0
ZOOM_MAX = 2.0


def dynamic_zoom(t: float) -> float:
    """1x at t=0, 2x at t=60 s, back to 1x at t=120 s."""
    phase = 0.5 - 0.5 * math.cos(2.0 * math.pi * t / ZOOM_PERIOD_S)
    return 1.0 + (ZOOM_MAX - 1.0) * phase


def _even(value: float) -> int:
    return max(2, int(round(value / 2.0)) * 2)


def transform_spec(variant: str, src_w: int, src_h: int, t: float, fov_crop: float | None = None) -> dict:
    """Return {kind, crop (x0,y0,w,h) or None, out (w,h), s (sx,sy), off (tx,ty), zoom}."""
    def centre_crop(cw: int, ch: int, out_wh: tuple[int, int] | None, zoom: float) -> dict:
        x0, y0 = (src_w - cw) // 2, (src_h - ch) // 2
        ow, oh = out_wh or (cw, ch)
        sx, sy = ow / cw, oh / ch
        return {"crop": (x0, y0, cw, ch), "out": (ow, oh), "s": (sx, sy),
                "off": (-x0 * sx, -y0 * sy), "pad": None, "zoom": zoom}

    if variant in ("base", "wide"):
        return centre_crop(src_w, src_h, None, 1.0)
    if variant == "px540":
        return centre_crop(src_w, src_h, (960, 540), 1.0)
    if variant == "crop75":
        return centre_crop(_even(src_w * 0.75), _even(src_h * 0.75), None, 1 / 0.75)
    if variant == "crop50":
        return centre_crop(src_w // 2, src_h // 2, None, 2.0)
    if variant == "crop43":
        return centre_crop(_even(src_h * 4 / 3), src_h, None, 1.0)
    if variant == "zoom2x":
        return centre_crop(src_w // 2, src_h // 2, (src_w, src_h), 2.0)
    if variant == "zoomdyn":
        z = dynamic_zoom(t)
        return centre_crop(_even(src_w / z), _even(src_h / z), (src_w, src_h), z)
    if variant == "wide_fov":
        if fov_crop is None:
            raise ValueError("wide_fov needs the estimated focal first")
        return centre_crop(_even(src_w * fov_crop), _even(src_h * fov_crop), None, 1 / fov_crop)
    if variant == "zoomout75":
        iw, ih = _even(src_w * 0.75), _even(src_h * 0.75)
        px, py = (src_w - iw) // 2, (src_h - ih) // 2
        return {"crop": None, "out": (src_w, src_h), "s": (iw / src_w, ih / src_h),
                "off": (float(px), float(py)), "pad": (px, py, iw, ih), "zoom": 0.75}
    raise ValueError(variant)


def apply_transform(frame: np.ndarray, spec: dict) -> np.ndarray:
    if spec["pad"] is not None:
        px, py, iw, ih = spec["pad"]
        canvas = np.zeros((spec["out"][1], spec["out"][0], 3), dtype=frame.dtype)
        canvas[py:py + ih, px:px + iw] = cv2.resize(frame, (iw, ih), interpolation=cv2.INTER_AREA)
        return canvas
    x0, y0, cw, ch = spec["crop"]
    img = frame[y0:y0 + ch, x0:x0 + cw]
    ow, oh = spec["out"]
    if (ow, oh) != (cw, ch):
        interp = cv2.INTER_AREA if ow < cw else cv2.INTER_LINEAR
        img = cv2.resize(img, (ow, oh), interpolation=interp)
    return np.ascontiguousarray(img)


def oracle_K(src_K: np.ndarray, spec: dict, ref_wh: tuple[int, int]) -> np.ndarray:
    """K of the transformed image after the system's resize to ref_wh."""
    ow, oh = spec["out"]
    rx, ry = ref_wh[0] / ow, ref_wh[1] / oh
    sx, sy = spec["s"]
    tx, ty = spec["off"]
    K = np.eye(3)
    K[0, 0] = src_K[0, 0] * sx * rx
    K[1, 1] = src_K[1, 1] * sy * ry
    K[0, 2] = (src_K[0, 2] * sx + tx) * rx
    K[1, 2] = (src_K[1, 2] * sy + ty) * ry
    return K


def sample_frames(video: Path, step_s: float, max_samples: int | None):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    wanted = [int(round(i * step_s * fps)) for i in range(int(count / fps / step_s) + 1)]
    wanted = [w for w in wanted if w < count]
    if max_samples:
        wanted = wanted[:max_samples]
    wanted_set = set(wanted)
    frames = {}
    idx = 0
    last = wanted[-1]
    while idx <= last:
        if idx in wanted_set:
            ok, frame = cap.read()
            if not ok:
                break
            frames[idx] = frame
        else:
            if not cap.grab():
                break
        idx += 1
    cap.release()
    samples = [(i, i / fps, frames[i]) for i in wanted if i in frames]
    print(f"decoded {len(samples)} samples from {video.name} (fps={fps:.2f})", flush=True)
    return samples, fps


FIELDS = [
    "exp", "variant", "kmode", "sample", "frame", "time_s", "zoom", "in_w", "in_h",
    "success", "x_px", "y_px", "num_inliers", "num_matches", "reproj_px",
    "fx_used", "fy_used", "calib_status", "calib_focal", "calib_estimates", "elapsed_s",
]


def load_done(csv_path: Path) -> set[tuple[str, str]]:
    if not csv_path.exists():
        return set()
    counts: dict[tuple[str, str], int] = {}
    with csv_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["variant"], row["kmode"])
            counts[key] = counts.get(key, 0) + 1
    return {k for k, v in counts.items() if v > 0}


def run_pass(localizer, samples, exp, variant, kmode, fixed_K, src_K, ref_wh, fov_crop, writer, fh):
    from app.core import localization as loc_mod  # noqa: F401  (import side effects already done)

    if kmode == "selfcal":
        localizer.reset_camera_calibration()
    ok_count = 0
    started = time.perf_counter()
    for n, (frame_idx, t, frame) in enumerate(samples):
        h, w = frame.shape[:2]
        spec = transform_spec(variant, w, h, t, fov_crop)
        img = apply_transform(frame, spec)
        if kmode == "selfcal":
            K = localizer.camera_self_calibrator.active_K()
            cb = None
        elif kmode == "oracle":
            K = oracle_K(src_K, spec, ref_wh)
            cb = lambda *_: False  # noqa: E731
        else:
            K = fixed_K
            cb = lambda *_: False  # noqa: E731
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            result, xy = localizer.localize(img, camera_K=K, calibration_callback=cb)
        elapsed = time.perf_counter() - t0
        success = bool(result.get("success")) and xy is not None
        ok_count += int(success)
        calib = result.get("camera_calibration") or {}
        reproj = result.get("median_reproj_error")
        writer.writerow({
            "exp": exp, "variant": variant, "kmode": kmode, "sample": n, "frame": frame_idx,
            "time_s": round(t, 3), "zoom": round(spec["zoom"], 4),
            "in_w": img.shape[1], "in_h": img.shape[0], "success": int(success),
            "x_px": round(float(xy[0]), 2) if success else "",
            "y_px": round(float(xy[1]), 2) if success else "",
            "num_inliers": result.get("num_inliers", 0), "num_matches": result.get("num_matches", 0),
            "reproj_px": round(float(reproj), 3) if reproj is not None and np.isfinite(reproj) else "",
            "fx_used": round(float(K[0, 0]), 1), "fy_used": round(float(K[1, 1]), 1),
            "calib_status": calib.get("status", "") if kmode == "selfcal" else "",
            "calib_focal": round(float(calib.get("focal_px", 0.0)), 1) if kmode == "selfcal" else "",
            "calib_estimates": calib.get("estimates", "") if kmode == "selfcal" else "",
            "elapsed_s": round(elapsed, 3),
        })
        if n % 25 == 0:
            fh.flush()
            print(f"  [{exp}/{variant}/{kmode}] {n + 1}/{len(samples)} ok={ok_count} "
                  f"f={K[0, 0]:.0f}/{K[1, 1]:.0f} {time.perf_counter() - started:.0f}s", flush=True)
    fh.flush()
    print(f"== {exp}/{variant}/{kmode}: {ok_count}/{len(samples)} localized "
          f"in {time.perf_counter() - started:.0f}s", flush=True)
    if kmode == "selfcal":
        estimates = [e["focal_px"] for e in localizer.camera_self_calibrator._estimates]
        return estimates
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exp", choices=sorted(EXPERIMENTS), required=True)
    parser.add_argument("--step", type=float, default=1.0, help="seconds between localized frames")
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--variants", nargs="*", default=None)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    cfg = EXPERIMENTS[args.exp]
    out = args.out / args.exp
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "results.csv"
    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    from app.core.localizer import Localizer
    with contextlib.redirect_stdout(io.StringIO()):
        localizer = Localizer(
            floor_id=cfg["floor_id"], data_dir=cfg["data_dir"],
            floor_plan_path=DATA / "map" / f"{cfg['floor_id']}.jpg",
            json_map_path=DATA / "json_map" / f"{cfg['floor_id']}.json",
            matching_mode="superpoint", retrieval_mode="megaloc",
        )
    map_K = localizer.map_K.copy()
    ref_wh = (int(round(map_K[0, 2] * 2)), int(round(map_K[1, 2] * 2)))
    print(f"map K f={map_K[0, 0]} cx={map_K[0, 2]} cy={map_K[1, 2]} -> reference size {ref_wh}", flush=True)

    samples, fps = sample_frames(cfg["video"], args.step, args.max_samples)
    src_h, src_w = samples[0][2].shape[:2]
    # floor5_2 is recorded with the mapping camera model: source K = map K
    # expressed at the video's own resolution.
    src_K = map_K.copy()
    src_K[0, 0] *= src_w / ref_wh[0]; src_K[0, 2] *= src_w / ref_wh[0]
    src_K[1, 1] *= src_h / ref_wh[1]; src_K[1, 2] *= src_h / ref_wh[1]

    if args.exp == "floor5":
        passes = []
        for v in (args.variants or cfg["variants"]):
            modes = ["map", "selfcal"] if v in ("base", "px540") else ["map", "selfcal", "oracle"]
            passes += [(v, m) for m in modes]
    else:
        passes = [("wide", "map"), ("wide", "selfcal"), ("wide", "estK"), ("wide_fov", "map")]
        if args.variants:
            passes = [p for p in passes if p[0] in args.variants]

    done = load_done(csv_path)
    new_file = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for variant, kmode in passes:
            if (variant, kmode) in done:
                print(f"skip {variant}/{kmode} (already in csv)", flush=True)
                continue
            fixed_K = map_K
            fov_crop = meta.get("fov_crop")
            if kmode == "estK" or variant == "wide_fov":
                if "focal_est" not in meta:
                    raise RuntimeError("run wide/selfcal first to estimate the focal")
                if kmode == "estK":
                    fixed_K = map_K.copy()
                    fixed_K[0, 0] = fixed_K[1, 1] = meta["focal_est"]
            estimates = run_pass(localizer, samples, args.exp, variant, kmode, fixed_K,
                                 src_K, ref_wh, fov_crop, writer, fh)
            if estimates is not None:
                meta.setdefault("selfcal_estimates", {})[variant] = estimates
                if args.exp == "floor1" and variant == "wide" and estimates:
                    f_est = float(np.median(estimates))
                    meta["focal_est"] = f_est
                    # Crop fraction that gives the query the map camera's FoV.
                    meta["fov_crop"] = min(1.0, f_est / float(map_K[0, 0]))
                    print(f"floor1 wide focal estimate = {f_est:.1f}px "
                          f"(map {map_K[0, 0]:.0f}px) -> fov crop {meta['fov_crop']:.3f}", flush=True)
            meta.update({"video": str(cfg["video"]), "fps": fps, "step_s": args.step,
                         "map_K": map_K.tolist(), "ref_wh": ref_wh, "src_wh": [src_w, src_h]})
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
