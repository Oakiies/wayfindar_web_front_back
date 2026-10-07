"""Run the frozen Round 0 AR reasonableness baseline audit.

This orchestrator is intentionally experiment-only. It does not touch the
production frontend/backend and does not create or modify the existing map.
It reuses the already-generated localization updates and the two existing
renderers so all baseline views use identical inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
POC_DIR = BACKEND / "poc_cross_camera"
OUT_ROOT = POC_DIR / "out" / "ar_reasonableness_poc"
ROUND_DIR = OUT_ROOT / "round_00_baseline"
VIDEO = Path(r"D:\video\video_from_iphone_oak_wide\IMG_6955.MOV")
UPDATES = POC_DIR / "out" / "non_imu_1p5s_localization_updates.json"
MAP_DIR = BACKEND / "app" / "data" / "map_data" / "result_floor1_4"
FLOOR_MAP = BACKEND / "app" / "data" / "map" / "floor1.jpg"
GRAPH = BACKEND / "app" / "data" / "json_map" / "floor1.json"
PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"

PRIMARY_TIMES = [7.5, 10.0, 15.0, 19.5, 25.0, 30.0, 32.2, 35.0,
                 40.0, 44.2, 49.5, 54.0, 55.5, 58.5]
STRESS_TIMES = [90.0, 96.0, 108.0, 112.0, 116.0, 130.0, 147.0, 155.0,
                169.9]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def digest_directory(path: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        # Global descriptor arrays are large. Hashing them is useful for
        # identity but is deliberately kept in the manifest as size+mtime;
        # the map path and the smaller geometry/config hashes identify the
        # experiment without spending minutes duplicating a map backup.
        stat = item.stat()
        record: dict[str, Any] = {
            "relative": str(item.relative_to(path)),
            "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        if stat.st_size <= 20_000_000:
            record["sha256"] = sha256_file(item)
        entries.append(record)
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "path": str(path),
        "file_count": len(entries),
        "entries": entries,
        "directory_fingerprint": hashlib.sha256(canonical).hexdigest(),
    }


def run_command(command: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        process = subprocess.run(
            command,
            cwd=str(POC_DIR),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        log.write(f"\n[exit_code={process.returncode}]\n")
    if process.returncode != 0:
        raise RuntimeError(f"command failed ({process.returncode}); see {log_path}")


def route_state(update: dict[str, Any] | None) -> str:
    if not isinstance(update, dict):
        return "unknown"
    turn = update.get("next_turn")
    if isinstance(turn, dict):
        direction = int(turn.get("dir", 0))
        at = turn.get("at") or []
        if isinstance(at, (list, tuple)) and len(at) >= 2:
            try:
                return f"turn:{direction}:{round(float(at[0]), 1)}:{round(float(at[1]), 1)}"
            except (TypeError, ValueError):
                pass
        return f"turn:{direction}"
    if "ARRIVED" in str(update.get("nav_text") or "").upper():
        return "arrived"
    return "straight"


def load_updates() -> list[dict[str, Any]]:
    payload = json.loads(UPDATES.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def selected_update(updates: list[dict[str, Any]], timestamp: float) -> dict[str, Any] | None:
    selected = None
    for update in updates:
        value = update.get("timestamp")
        if isinstance(value, (int, float)) and float(value) <= timestamp:
            selected = update
        elif isinstance(value, (int, float)) and float(value) > timestamp:
            break
    return selected


def read_video_frame(path: Path, timestamp: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, round(timestamp * fps)))
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def make_contact_sheet(video_path: Path, times: list[float], output: Path, columns: int = 2) -> None:
    frames: list[np.ndarray] = []
    for timestamp in times:
        frame = read_video_frame(video_path, timestamp)
        if frame is None:
            continue
        frame = cv2.resize(frame, (960, 270), interpolation=cv2.INTER_AREA)
        cv2.rectangle(frame, (0, 0), (960, 31), (24, 14, 6), -1)
        cv2.putText(
            frame,
            f"t={timestamp:.2f}s",
            (12, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        frames.append(frame)
    if not frames:
        raise RuntimeError(f"no frames available for {video_path}")
    rows = (len(frames) + columns - 1) // columns
    blank = np.zeros_like(frames[0])
    canvas = np.zeros((rows * frames[0].shape[0], columns * frames[0].shape[1], 3), dtype=np.uint8)
    for index, frame in enumerate(frames):
        row, column = divmod(index, columns)
        canvas[
            row * frame.shape[0]:(row + 1) * frame.shape[0],
            column * frame.shape[1]:(column + 1) * frame.shape[1],
        ] = frame
    for index in range(len(frames), rows * columns):
        row, column = divmod(index, columns)
        canvas[
            row * blank.shape[0]:(row + 1) * blank.shape[0],
            column * blank.shape[1]:(column + 1) * blank.shape[1],
        ] = blank
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), canvas)


def write_review_manifest(updates: list[dict[str, Any]]) -> None:
    records = []
    for timestamp in PRIMARY_TIMES + STRESS_TIMES:
        update = selected_update(updates, timestamp)
        records.append({
            "timestamp": timestamp,
            "scope": "primary" if timestamp <= 60 else "stress_only",
            "route_state": route_state(update),
            "nav_text": update.get("nav_text") if update else None,
            "method": update.get("method") if update else None,
            "hold_age": update.get("hold_age") if update else None,
            "expected_review": "Check walkable direction, wall crossing, stale turn and registration",
            "human_label": None,
        })
    (ROUND_DIR / "review_manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def git_status() -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--short"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def main() -> int:
    for required in (VIDEO, UPDATES, MAP_DIR, FLOOR_MAP, GRAPH, PYTHON):
        if not required.exists():
            raise FileNotFoundError(required)

    ROUND_DIR.mkdir(parents=True, exist_ok=True)
    v0_dir = ROUND_DIR / "v0_current_hold"
    v2_dir = ROUND_DIR / "v2_klt_homography"

    commands = [
        [str(PYTHON), str(POC_DIR / "render_fullrate_non_imu_ar.py"),
         "--video", str(VIDEO), "--duration", "60", "--input-updates", str(UPDATES),
         "--output", str(v0_dir)],
        [str(PYTHON), str(POC_DIR / "render_stale_free_ar.py"),
         "--video", str(VIDEO), "--input-updates", str(UPDATES),
         "--output-dir", str(v2_dir), "--start", "0", "--duration", "60",
         "--caret-suppress", "0.75", "--tag", "primary_0_60"],
        [str(PYTHON), str(POC_DIR / "render_stale_free_ar.py"),
         "--video", str(VIDEO), "--input-updates", str(UPDATES),
         "--output-dir", str(v2_dir), "--start", "80", "--duration", "100",
         "--caret-suppress", "0.75", "--tag", "stress_80_180"],
    ]
    log_paths = [
        ROUND_DIR / "v0_current_hold.log",
        ROUND_DIR / "v2_klt_primary.log",
        ROUND_DIR / "v2_klt_stress.log",
    ]
    for command, log_path in zip(commands, log_paths):
        run_command(command, log_path)

    updates = load_updates()
    write_review_manifest(updates)
    primary_comparison = v2_dir / "non_imu_stale_free_ar_primary_0_60_comparison.mp4"
    stress_comparison = v2_dir / "non_imu_stale_free_ar_stress_80_180_comparison.mp4"
    make_contact_sheet(primary_comparison, PRIMARY_TIMES, ROUND_DIR / "primary_critical_contact_sheet.png")
    make_contact_sheet(
        primary_comparison,
        [30.0, 31.5, 32.2, 33.0, 35.0, 37.5, 44.2, 49.5, 54.0, 55.5],
        ROUND_DIR / "turn_transition_contact_sheet.png",
    )
    make_contact_sheet(stress_comparison, STRESS_TIMES, ROUND_DIR / "stress_contact_sheet.png")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "round": "round_00_baseline",
        "purpose": "Freeze identical inputs and render baseline evidence; no accuracy verdict yet.",
        "video": {"path": str(VIDEO), "sha256": sha256_file(VIDEO),
                  "bytes": VIDEO.stat().st_size},
        "updates": {"path": str(UPDATES), "sha256": sha256_file(UPDATES),
                    "bytes": UPDATES.stat().st_size},
        "fixed_map": digest_directory(MAP_DIR),
        "floor_map": {"path": str(FLOOR_MAP), "sha256": sha256_file(FLOOR_MAP)},
        "graph": {"path": str(GRAPH), "sha256": sha256_file(GRAPH)},
        "python": str(PYTHON),
        "git_status": git_status(),
        "primary_window_seconds": [0, 60],
        "stress_window_seconds": [80, 180],
        "commands": commands,
        "outputs": {
            "v0_current_hold_dir": str(v0_dir),
            "v2_klt_homography_dir": str(v2_dir),
            "primary_critical_contact_sheet": str(ROUND_DIR / "primary_critical_contact_sheet.png"),
            "turn_transition_contact_sheet": str(ROUND_DIR / "turn_transition_contact_sheet.png"),
            "stress_contact_sheet": str(ROUND_DIR / "stress_contact_sheet.png"),
            "review_manifest": str(ROUND_DIR / "review_manifest.json"),
        },
    }
    (ROUND_DIR / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    result = {
        "round": "round_00_baseline",
        "status": "READY_FOR_CODEX_REVIEW",
        "scope": {
            "primary": "0-60s route-to-M21 review",
            "stress_only": "80-180s tracking/turn stress; not route correctness after arrival",
        },
        "variants": {
            "V0_CURRENT_HOLD": "render_fullrate_non_imu_ar: raw/EMA/jump/KLT comparison",
            "V1_BUFFERED_REPLAY": "represented by EMA interpolation panel; offline-only and uses future anchor",
            "V2_KLT_HOMOGRAPHY": "render_stale_free_ar: full-rate KLT propagation + route-state reset",
        },
        "important_caveat": "This round measures continuity/evidence availability only. It does not prove that AR is on the real walkable floor.",
        "required_human_review": "Fill human_label in review_manifest.json or annotate RESULT.md after inspecting contact sheets.",
        "outputs": manifest["outputs"],
    }
    (ROUND_DIR / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = f"""# Round 0 — AR reasonableness baseline audit

สถานะ: `READY_FOR_CODEX_REVIEW`

รอบนี้ freeze input และ render baseline เท่านั้น ยังไม่มี accuracy verdict และยังไม่เริ่ม tracked-landmark PnP

## Input

- Video: `{VIDEO}`
- Cached localization: `{UPDATES}`
- Fixed map: `{MAP_DIR}`
- Primary window: `0–60 s`
- Stress-only window: `80–180 s` (ไม่ใช้ตัดสิน route ไป M21 หลัง arrival)

รายละเอียด hash และ git status อยู่ใน `input_manifest.json`

## Variants

- `V0_CURRENT_HOLD`: raw/EMA/jump-gated/KLT comparison จาก `render_fullrate_non_imu_ar.py`
- `V1_BUFFERED_REPLAY`: EMA/interpolation panel — offline-only เพราะใช้ future anchor
- `V2_KLT_HOMOGRAPHY`: full-rate KLT propagation + fresh anchor + route-state reset จาก `render_stale_free_ar.py`

## Evidence

- `primary_critical_contact_sheet.png`: frames ที่ต้องตรวจในช่วง route หลัก
- `turn_transition_contact_sheet.png`: frames รอบจุดเลี้ยวและ hand-off
- `stress_contact_sheet.png`: stress-only frames
- `review_manifest.json`: timestamp, route state และช่อง human label
- `summary.json`: รายละเอียดรอบและ output paths

## ข้อควรระวังในการตีความ

ค่า flow acceptance สูงไม่ได้พิสูจน์ว่า AR ลงบนพื้นหรือชี้ทางเดินถูกต้อง เพราะ homography เป็นเพียง image-motion model และฉากมี parallax

โปรดตรวจอย่างน้อย:

1. caret เก่าหายภายใน 250 ms หลัง route state เปลี่ยนหรือไม่
2. ribbon/caret เบนเข้าผนังหรือพื้นที่เดินไม่ได้หรือไม่
3. มี jump/re-anchor ที่ทำให้เส้นส่ายหรือไม่
4. หลัง arrival ยังมี turn/ribbon เก่าค้างหรือไม่
5. ช่วงที่ไม่มี pose ถูกแสดงเป็น stale world AR หรือไม่

## Next action

หยุดที่ Round 0 และส่งไฟล์นี้ให้ Codex อ่านก่อนเริ่ม Round 1
"""
    (ROUND_DIR / "RESULT.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
