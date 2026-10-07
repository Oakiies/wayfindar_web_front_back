"""Render a natural-speed AR comparison over the original video.

Unlike the sparse preview experiment, this script writes every source frame.
The backend localization payload is still available only every 1.5 seconds;
the methods differ in how they carry the AR pose between those anchors.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np

from run_non_imu_video_comparison import (
    DEFAULT_OUTPUT,
    DEFAULT_VIDEO,
    ema_payload,
    overlay_centroid,
    payload_screen_polygons,
    payload_pose,
    track_homography,
    warp_polygons,
)
from video_naming import next_video_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--duration", type=float, default=90.0)
    parser.add_argument("--input-updates", type=Path, default=None)
    return parser.parse_args()


def load_updates(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def fresh_anchors(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors = []
    for update in updates:
        payload = update.get("ar_world")
        timestamp = update.get("timestamp")
        if not isinstance(timestamp, (int, float)) or not isinstance(payload, dict):
            continue
        if payload_pose(payload) is None:
            continue
        if update.get("method") == "HOLD_LAST_FIX":
            continue
        anchors.append({
            "timestamp": float(timestamp),
            "payload": payload,
            "position": update.get("position"),
            "frame": update.get("frame"),
        })
    return anchors


def anchor_index_at(anchors: list[dict[str, Any]], timestamp: float) -> int:
    index = -1
    for i, anchor in enumerate(anchors):
        if float(anchor["timestamp"]) <= timestamp + 1e-6:
            index = i
        else:
            break
    return index


def interpolated_anchor_payload(anchors: list[dict[str, Any]], timestamp: float) -> dict[str, Any] | None:
    if not anchors:
        return None
    right = next((i for i, a in enumerate(anchors) if float(a["timestamp"]) >= timestamp), None)
    if right is None:
        return copy.deepcopy(anchors[-1]["payload"])
    if right == 0:
        if timestamp < float(anchors[0]["timestamp"]):
            return None
        return copy.deepcopy(anchors[0]["payload"])
    left = right - 1
    a0 = anchors[left]
    a1 = anchors[right]
    t0 = float(a0["timestamp"])
    t1 = float(a1["timestamp"])
    span = max(t1 - t0, 1e-6)
    alpha = max(0.0, min(1.0, (timestamp - t0) / span))
    # Smoothstep keeps velocity continuous at both PnP anchor boundaries.
    alpha = alpha * alpha * (3.0 - 2.0 * alpha)
    result = ema_payload(a0["payload"], a1["payload"], alpha=alpha)
    return result


def accepted_jump_anchors(anchors: list[dict[str, Any]], interval: float = 1.5) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    last_position: dict[str, Any] | None = None
    threshold = max(42.0, 18.0 * interval * 2.0)
    for anchor in anchors:
        position = anchor.get("position")
        accept = True
        if isinstance(last_position, dict) and isinstance(position, dict):
            try:
                distance = math.hypot(
                    float(position["x"]) - float(last_position["x"]),
                    float(position["y"]) - float(last_position["y"]),
                )
                accept = distance <= threshold
            except (KeyError, TypeError, ValueError):
                accept = True
        if accept:
            accepted.append(anchor)
            if isinstance(position, dict):
                last_position = position
    return accepted


def translate_polygons(
    polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]],
    delta: np.ndarray,
) -> list[tuple[np.ndarray, tuple[int, int, int], float, str]]:
    return [(poly + delta.reshape(1, 2), color, alpha, kind) for poly, color, alpha, kind in polygons]


def safe_visual_warp(
    previous_polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]],
    H: np.ndarray | None,
    frame_shape: tuple[int, ...],
) -> list[tuple[np.ndarray, tuple[int, int, int], float, str]]:
    if H is None or not previous_polygons:
        return previous_polygons
    warped = warp_polygons(previous_polygons, H)
    if not warped:
        return previous_polygons
    width = float(frame_shape[1])
    height = float(frame_shape[0])
    all_points = np.concatenate([poly for poly, _, _, _ in warped], axis=0)
    if not np.all(np.isfinite(all_points)):
        return previous_polygons
    # A valid short-term camera warp may leave the viewport, but a numerical
    # explosion should never be allowed to move the floor ribbon thousands of
    # pixels away.
    if np.max(np.abs(all_points[:, 0])) > width * 4.0 or np.max(np.abs(all_points[:, 1])) > height * 4.0:
        return previous_polygons
    return warped


def draw_label(frame: np.ndarray, label: str, timestamp: float, extra: str = "") -> np.ndarray:
    out = frame.copy()
    text = f"{label} | t={timestamp:5.1f}s"
    if extra:
        text += f" | {extra}"
    cv2.rectangle(out, (0, 0), (out.shape[1], 30), (8, 18, 32), -1)
    cv2.putText(out, text, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (240, 250, 255), 1, cv2.LINE_AA)
    return out


def draw_overlay(frame: np.ndarray, polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]]) -> np.ndarray:
    out = frame.copy()
    for poly, color, alpha, kind in polygons:
        pts = np.round(poly).astype(np.int32).reshape(-1, 1, 2)
        if kind == "edge":
            cv2.polylines(out, [pts], False, color, 2, cv2.LINE_AA)
            continue
        layer = out.copy()
        cv2.fillPoly(layer, [pts], color)
        out = cv2.addWeighted(layer, alpha, out, 1.0 - alpha, 0.0)
        cv2.polylines(out, [pts], True, (0, 255, 255), 1, cv2.LINE_AA)
    return out


def open_writer(path: Path, size: tuple[int, int], fps: float) -> cv2.VideoWriter:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise RuntimeError(f"cannot create {path}")
    return writer


def main() -> int:
    args = parse_args()
    out_dir = args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    updates_path = args.input_updates or (out_dir / "non_imu_1p5s_localization_updates.json")
    updates = load_updates(updates_path)
    anchors = fresh_anchors(updates)
    gated_anchors = accepted_jump_anchors(anchors)
    if not anchors:
        raise RuntimeError("no fresh AR anchors in localization updates")

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {args.video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    duration = min(float(args.duration), float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0) / fps)

    # Render at 640x360 to keep the comparison easy to open while preserving
    # the original video cadence. This is a natural-speed video, not a sparse
    # slideshow.
    panel_size = (640, 360)
    output_size = (panel_size[0] * 2, panel_size[1] * 2)
    output_path = next_video_path(out_dir, "non_imu_fullrate_ar_90s_comparison")
    writer = open_writer(output_path, output_size, fps)

    previous_gray: np.ndarray | None = None
    previous_flow_polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]] = []
    previous_anchor_index = -1
    frames_written = 0
    flow_ok = 0
    flow_total = 0
    stats = {"raw_pnp": 0.0, "ema_pose": 0.0, "jump_hold": 0.0, "klt_corrected": 0.0}

    try:
        while True:
            ok, source_frame = cap.read()
            if not ok:
                break
            timestamp = float(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            if timestamp > duration + 1.0 / fps:
                break
            frame = cv2.resize(source_frame, panel_size, interpolation=cv2.INTER_AREA)

            raw_index = anchor_index_at(anchors, timestamp)
            raw_payload = anchors[raw_index]["payload"] if raw_index >= 0 else None
            raw_polygons = payload_screen_polygons(raw_payload, frame.shape)

            ema = interpolated_anchor_payload(anchors, timestamp)
            ema_polygons = payload_screen_polygons(ema, frame.shape)

            jump_index = anchor_index_at(gated_anchors, timestamp)
            jump_payload = gated_anchors[jump_index]["payload"] if jump_index >= 0 else None
            jump_polygons = payload_screen_polygons(jump_payload, frame.shape)

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            current_anchor_changed = raw_index != previous_anchor_index
            if current_anchor_changed and raw_polygons:
                if not previous_flow_polygons:
                    previous_flow_polygons = raw_polygons
                else:
                    before = overlay_centroid(previous_flow_polygons)
                    after = overlay_centroid(raw_polygons)
                    if before is not None and after is not None:
                        previous_flow_polygons = translate_polygons(
                            previous_flow_polygons,
                            0.35 * np.asarray([after[0] - before[0], after[1] - before[1]], dtype=np.float32),
                        )
            H = None
            inliers = 0
            residual = None
            if previous_gray is not None:
                H, inliers, residual = track_homography(previous_gray, gray)
                flow_total += 1
                if H is not None and inliers >= 20 and residual is not None and residual <= 3.5:
                    flow_ok += 1
                else:
                    H = None
            flow_polygons = safe_visual_warp(previous_flow_polygons, H, frame.shape)
            if not flow_polygons and raw_polygons:
                flow_polygons = raw_polygons
            visual_corrected = flow_polygons
            flow_centroid = overlay_centroid(flow_polygons)
            raw_centroid = overlay_centroid(raw_polygons)
            if flow_centroid is not None and raw_centroid is not None:
                visual_corrected = translate_polygons(
                    flow_polygons,
                    0.35 * np.asarray([raw_centroid[0] - flow_centroid[0], raw_centroid[1] - flow_centroid[1]], dtype=np.float32),
                )
            previous_flow_polygons = visual_corrected
            previous_gray = gray
            previous_anchor_index = raw_index

            panels = [
                draw_label(draw_overlay(frame, raw_polygons), "RAW PnP", timestamp, f"anchor={raw_index}"),
                draw_label(draw_overlay(frame, ema_polygons), "EMA INTERPOLATED", timestamp, f"anchor={raw_index}"),
                draw_label(draw_overlay(frame, jump_polygons), "JUMP-GATED HOLD", timestamp, f"anchor={jump_index}"),
                draw_label(draw_overlay(frame, visual_corrected), "KLT + SOFT PnP", timestamp, f"inliers={inliers}"),
            ]
            montage = np.zeros((output_size[1], output_size[0], 3), dtype=np.uint8)
            montage[0:panel_size[1], 0:panel_size[0]] = panels[0]
            montage[0:panel_size[1], panel_size[0]:output_size[0]] = panels[1]
            montage[panel_size[1]:output_size[1], 0:panel_size[0]] = panels[2]
            montage[panel_size[1]:output_size[1], panel_size[0]:output_size[0]] = panels[3]
            writer.write(montage)
            frames_written += 1
            if frames_written % int(max(1, fps * 10)) == 0:
                print(f"[fullrate] {timestamp:6.1f}s / {duration:6.1f}s, frames={frames_written}, flow={flow_ok}/{flow_total}")
    finally:
        cap.release()
        writer.release()

    summary = {
        "video": str(args.video),
        "duration_seconds": duration,
        "source_fps": fps,
        "source_size": [source_width, source_height],
        "render_size": list(output_size),
        "frames_written": frames_written,
        "anchor_count": len(anchors),
        "jump_gated_anchor_count": len(gated_anchors),
        "flow_accepted": flow_ok,
        "flow_attempts": flow_total,
        "flow_accept_rate": flow_ok / max(flow_total, 1),
        "output": str(output_path),
        "note": "Natural-speed full-frame render; backend PnP anchors remain sparse at 1.5 seconds.",
    }
    (out_dir / "non_imu_fullrate_ar_90s_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
