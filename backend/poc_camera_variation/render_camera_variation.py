"""Render side-by-side videos from run_camera_variation.py results.

Left : the image each camera variant hands to the localizer (live video).
Right: floor plan with each variant's localized position, a short trail, and
       the running error against the unmodified baseline.

Output is H.264/yuv420p through the ffmpeg bundled with imageio-ffmpeg so it
plays in any browser or phone.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from run_camera_variation import APP_DIR, EVIDENCE_DIR, OUT_DIR, apply_transform, transform_spec

W, H = 1920, 1080
FONT = r"C:\Windows\Fonts\LeelawUI.ttf"
FONT_BOLD = r"C:\Windows\Fonts\LeelaUIb.ttf"
_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (FONT_BOLD if bold else FONT, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(key[0], size)
    return _fonts[key]


# BGR
COLORS = {
    "base": (40, 40, 40), "px540": (180, 119, 31), "crop75": (14, 127, 255),
    "crop50": (40, 39, 214), "crop43": (189, 103, 148), "zoom2x": (40, 39, 214),
    "zoomout75": (44, 160, 44), "zoomdyn": (194, 20, 227),
    "wide/map": (40, 39, 214), "wide/selfcal": (14, 127, 255), "wide/estK": (44, 160, 44),
    "wide_fov/map": (180, 119, 31),
}

LABELS = {
    "base": "ต้นฉบับ 1920×1080",
    "px540": "ย่อทั้งภาพ 960×540 (พิกเซลน้อยลง มุมเท่าเดิม)",
    "crop75": "ครอป 75% = 1440×810",
    "crop50": "ครอป 50% = 960×540",
    "crop43": "ครอป 4:3 = 1440×1080",
    "zoom2x": "ซูมอิน 2x (ครอป 50% แล้วขยายกลับ 1920×1080)",
    "zoomout75": "ซูมเอาต์ 0.75x (ย่อภาพ + ขอบดำ)",
    "zoomdyn": "ซูมเปลี่ยนตลอด 1x > 2x > 1x ทุก 120 วิ",
    "wide": "กล้องมุมกว้าง (iPhone) ตามที่ถ่ายมา",
    "wide_fov": "กล้องมุมกว้าง ครอปให้มุมเท่ากล้องแผนที่",
}

KMODE_TEXT = {
    "map": "ใช้ K ของแผนที่ตรง ๆ (f=1400) ไม่ปรับ",
    "selfcal": "ระบบจริง: self-calibration ประมาณ focal เองระหว่างเดิน",
    "oracle": "บอกระบบด้วย K ที่ถูกต้องตามการครอป/ซูม (กรณีอุดมคติ)",
    "estK": "K คงที่ จาก focal ที่ self-calibration ประมาณได้",
}

GROUPS = {
    ("floor5", "crop"): ["base", "px540", "crop75", "crop50", "crop43"],
    ("floor5", "zoom"): ["base", "zoom2x", "zoomout75", "zoomdyn"],
}


def load_rows(exp: str) -> tuple[dict, dict]:
    out = OUT_DIR / exp
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    rows: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with (out / "results.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows[(row["variant"], row["kmode"])].append(row)
    return rows, meta


def entries_for(exp: str, group: str, kmode: str, rows) -> list[dict]:
    """One entry per (variant, kmode) drawn on the map."""
    if exp == "floor1":
        pairs = [("wide", "map"), ("wide", "selfcal"), ("wide", "estK"), ("wide_fov", "map")]
        names = {("wide", "map"): "มุมกว้าง + K แผนที่",
                 ("wide", "selfcal"): "มุมกว้าง + self-calibration (ระบบจริง)",
                 ("wide", "estK"): "มุมกว้าง + K ที่ประมาณได้",
                 ("wide_fov", "map"): "ครอปให้มุมเท่าแผนที่ + K แผนที่"}
        out = []
        for v, m in pairs:
            if (v, m) in rows:
                out.append({"variant": v, "kmode": m, "key": f"{v}/{m}", "name": names[(v, m)],
                            "color": COLORS[f"{v}/{m}"], "rows": rows[(v, m)]})
        return out
    out = []
    for v in GROUPS[(exp, group)]:
        m = kmode
        if (v, m) not in rows and m == "oracle":
            m = "map"  # base / px540: oracle K is the map K
        if (v, m) not in rows:
            continue
        out.append({"variant": v, "kmode": m, "key": v, "name": LABELS[v],
                    "color": COLORS[v], "rows": rows[(v, m)]})
    return out


def fnum(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


class Stats:
    """Running success rate and error against the baseline."""

    def __init__(self, entries, ref_rows):
        self.ref = {int(r["sample"]): (fnum(r["x_px"]), fnum(r["y_px"])) for r in ref_rows} if ref_rows else {}

    def error(self, row) -> float | None:
        if not self.ref:
            return None
        ref = self.ref.get(int(row["sample"]))
        x, y = fnum(row["x_px"]), fnum(row["y_px"])
        if ref is None or ref[0] is None or x is None:
            return None
        return float(np.hypot(x - ref[0], y - ref[1]))


def letterbox(img: np.ndarray, w: int, h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    scale = min(w / iw, h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    canvas = np.full((h, w, 3), 18, dtype=np.uint8)
    x0, y0 = (w - nw) // 2, (h - nh) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    return canvas


def tile_layout(n_tiles: int, exp: str) -> list[tuple[int, int, int, int]]:
    """Rects (x, y, w, h) of the image part of each tile inside the left area."""
    top = 72
    if exp == "floor1":
        return [(20, top, 1060, 596), (20, top + 596 + 60, 480, 270)]
    tw, th, cap = 512, 288, 48
    rects = []
    for i in range(n_tiles):
        col, row = i % 2, i // 2
        rects.append((20 + col * (tw + 20), top + row * (th + cap), tw, th))
    return rects


def draw_map(floor: np.ndarray, entries, sample_idx: dict, trail: int = 25) -> np.ndarray:
    scale = 800 / floor.shape[1]
    canvas = cv2.resize(floor, (800, int(floor.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
    canvas = cv2.addWeighted(canvas, 0.75, np.full_like(canvas, 255), 0.25, 0)
    overlay = canvas.copy()
    markers = []
    for e in entries:
        k = sample_idx[e["key"]]
        if k < 0:
            continue
        pts = []
        for r in e["rows"][max(0, k - trail):k + 1]:
            if r["success"] == "1":
                pts.append((float(r["x_px"]) * scale, float(r["y_px"]) * scale))
        if len(pts) >= 2:
            cv2.polylines(overlay, [np.int32(np.round(pts))], False, e["color"], 3, cv2.LINE_AA)
        last_ok = pts[-1] if pts else None
        live = e["rows"][k]["success"] == "1"
        if last_ok is not None:
            markers.append((e, last_ok, live))
    canvas = cv2.addWeighted(overlay, 0.55, canvas, 0.45, 0)
    for e, (x, y), live in markers:
        c = (int(round(x)), int(round(y)))
        radius = 13 if e["key"] in ("base", "wide/selfcal") else 10
        if live:
            cv2.circle(canvas, c, radius + 3, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(canvas, c, radius, e["color"], -1, cv2.LINE_AA)
        else:
            cv2.circle(canvas, c, radius, e["color"], 3, cv2.LINE_AA)  # hollow = lost, last known
    return canvas


def render(exp: str, group: str, kmode: str, fps_out: float, start: float, duration: float | None,
           out_path: Path) -> None:
    rows, meta = load_rows(exp)
    entries = entries_for(exp, group, kmode, rows)
    if not entries:
        raise RuntimeError("no results for this selection yet")
    ref_key = ("base", "map") if exp == "floor5" else None  # same reference as the summary tables
    stats = Stats(entries, rows.get(ref_key) if ref_key else None)
    step = float(meta["step_s"])
    floor = cv2.imread(str(APP_DIR / "data" / "map" / f"{'floor5' if exp == 'floor5' else 'floor1'}.jpg"))

    tiles = []  # distinct variants shown on the left
    for e in entries:
        if e["variant"] not in [t["variant"] for t in tiles]:
            tiles.append(e)
    rects = tile_layout(len(tiles), exp)

    cap = cv2.VideoCapture(meta["video"])
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    n_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    n_samples = min(len(e["rows"]) for e in entries)
    t_end = min(n_src / src_fps, n_samples * step)
    if duration:
        t_end = min(t_end, start + duration)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(start * src_fps)))
    src_pos = int(round(start * src_fps))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps_out), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(out_path)],
        stdin=subprocess.PIPE,
    )
    title = {
        "floor5": f"ชั้น 5 · floor5_2.mp4 · {'ครอป / จำนวนพิกเซล' if group == 'crop' else 'ซูมอิน / ซูมเอาต์'}",
        "floor1": "ชั้น 1 · กล้องคนละตัว (iPhone มุมกว้าง) · floor1_pare_wide_mp4.mp4",
    }[exp]
    subtitle = KMODE_TEXT[kmode] if exp == "floor5" else (
        f"self-cal ประมาณ focal ≈ {meta.get('focal_est', 0):.0f}px (แผนที่ 1400px)  ·  "
        f"ครอป {meta.get('fov_crop', 1) * 100:.0f}% = มุมเท่ากล้องแผนที่")

    frame = None
    t = start
    n_out = 0
    while t < t_end:
        target = int(round(t * src_fps))
        while src_pos <= target:
            ok, f = cap.read()
            if not ok:
                break
            frame, src_pos = f, src_pos + 1
        if frame is None:
            break
        k = min(int(t // step), n_samples - 1)
        sample_idx = {e["key"]: k for e in entries}

        img = np.full((H, W, 3), 245, dtype=np.uint8)
        img[:, :1100] = (30, 30, 30)
        # tiles
        for tile, (x, y, w, h) in zip(tiles, rects):
            spec = transform_spec(tile["variant"], frame.shape[1], frame.shape[0], t, meta.get("fov_crop"))
            view = letterbox(apply_transform(frame, spec), w, h)
            if tile["variant"] in ("base", "wide"):
                # Outline what every cropped variant keeps of the full view.
                sx, sy = w / frame.shape[1], h / frame.shape[0]
                for other in tiles:
                    o_spec = transform_spec(other["variant"], frame.shape[1], frame.shape[0], t,
                                            meta.get("fov_crop"))
                    if other is tile or o_spec["crop"] is None:
                        continue
                    ox, oy, ow, oh = o_spec["crop"]
                    if (ow, oh) == (frame.shape[1], frame.shape[0]):
                        continue
                    cv2.rectangle(view, (int(ox * sx), int(oy * sy)),
                                  (int((ox + ow) * sx) - 1, int((oy + oh) * sy) - 1), other["color"], 2)
            img[y:y + h, x:x + w] = view
            cv2.rectangle(img, (x - 3, y - 3), (x + w + 2, y + h + 2), tile["color"], 4)
        img[70:870, 1110:1910] = draw_map(floor, entries, sample_idx)[:800, :800]

        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil)
        d.text((20, 14), title, font=font(30, True), fill=(255, 255, 255))
        d.text((1110, 14), subtitle, font=font(20), fill=(60, 60, 60))
        d.text((1110, 40), f"t = {t:6.1f} s   ·   localize ทุก {step:g} s   ·   วงกลวง = หาตำแหน่งไม่ได้ (โชว์ตำแหน่งล่าสุด)",
               font=font(17), fill=(90, 90, 90))
        # tile captions
        for tile, (x, y, w, h) in zip(tiles, rects):
            r = tile["rows"][k]
            spec_zoom = float(r["zoom"])
            cap_text = LABELS[tile["variant"]]
            if tile["variant"] == "zoomdyn":
                cap_text = f"ซูมตอนนี้ {spec_zoom:.2f}x (1x > 2x > 1x)"
            d.text((x, y + h + 4), cap_text, font=font(18, True), fill=(255, 255, 255))
            if exp == "floor5":
                err = stats.error(r)
                live = (f"f={float(r['fx_used']):.0f}" +
                        (f"/{float(r['fy_used']):.0f}" if r["fx_used"] != r["fy_used"] else "") +
                        f"  ถูกต้อง≈{1400 * spec_zoom:.0f}" if tile["variant"] != "crop43" else
                        f"fx/fy={float(r['fx_used']):.0f}/{float(r['fy_used']):.0f}  ถูกต้อง≈1867/1400")
                live += "   " + (f"คลาด {err:.0f}px" if err is not None else
                                 ("LOST" if r["success"] != "1" else ""))
                d.text((x, y + h + 24), live, font=font(15), fill=(200, 200, 200))
            elif tile["variant"] == "wide_fov":
                d.text((x, y + h + 26), f"ครอป {meta.get('fov_crop', 1) * 100:.0f}% ของภาพ",
                       font=font(15), fill=(200, 200, 200))

        # legend / running stats under the map
        ly = 880
        d.text((1110, ly), "สี · ตัวแปร · หาตำแหน่งได้ · คลาดจากต้นฉบับ (median px, แผนที่กว้าง 500px)"
               if exp == "floor5" else "สี · วิธี · หาตำแหน่งได้ · ตำแหน่งกระโดด >40px",
               font=font(16, True), fill=(40, 40, 40))
        for i, e in enumerate(entries):
            sub = e["rows"][:k + 1]
            ok = sum(r["success"] == "1" for r in sub)
            if exp == "floor5":
                errs = [v for v in (stats.error(r) for r in sub) if v is not None]
                metric = f"{np.median(errs):5.1f}px" if errs and e["key"] != "base" else ("อ้างอิง" if e["key"] == "base" else "-")
            else:
                pts = [(float(r["x_px"]), float(r["y_px"])) for r in sub if r["success"] == "1"]
                jumps = sum(np.hypot(b[0] - a[0], b[1] - a[1]) > 40 for a, b in zip(pts, pts[1:]))
                metric = f"{jumps} ครั้ง"
            yy = ly + 28 + i * 30
            col = tuple(int(c) for c in e["color"][::-1])
            d.ellipse((1112, yy + 3, 1130, yy + 21), fill=col, outline=(255, 255, 255))
            name = e["name"] if exp == "floor1" else e["name"].split(" (")[0]
            d.text((1140, yy), f"{name}", font=font(16), fill=(30, 30, 30))
            d.text((1640, yy), f"{ok}/{len(sub)}", font=font(16), fill=(30, 30, 30))
            d.text((1760, yy), metric, font=font(16, True), fill=(30, 30, 30))

        ffmpeg.stdin.write(cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR).tobytes())
        n_out += 1
        t = start + n_out / fps_out
    cap.release()
    ffmpeg.stdin.close()
    ffmpeg.wait()
    print(f"wrote {out_path} ({n_out} frames)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exp", choices=["floor5", "floor1"], required=True)
    parser.add_argument("--group", default="crop", choices=["crop", "zoom", "wide"])
    parser.add_argument("--kmode", default="selfcal", choices=["map", "selfcal", "oracle"])
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    name = f"{args.exp}_{args.group}_{args.kmode}.mp4" if args.exp == "floor5" else "floor1_wide_camera.mp4"
    render(args.exp, args.group, args.kmode, args.fps, args.start, args.duration,
           args.out or EVIDENCE_DIR / "videos" / name)


if __name__ == "__main__":
    main()
