"""Render shallow corridor changes as a continuous path, not a turn cue.

The M21 route contains a diagonal/chamfered corridor transition. This PoC
keeps the existing map, poses, and KLT propagation, but removes the repeated
left/right carets when the route deflection is shallow. The floor ribbon stays
visible as a continuous corridor guide.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from render_fullrate_non_imu_ar import (
    DEFAULT_VIDEO,
    anchor_index_at,
    draw_label,
    load_updates,
    open_writer,
    payload_screen_polygons,
    track_homography,
)
from render_stale_free_ar import bounded_visual_warp, draw_overlay, enrich_anchors, strip_carets
from video_naming import next_video_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--input-updates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=float, default=28.0)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--gentle-angle", type=float, default=40.0)
    parser.add_argument("--tag", type=str, default="continuous_corridor")
    return parser.parse_args()


def as_point(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        value = [value.get("x"), value.get("y")]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        result = (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(item) for item in result) else None


def route_deflections(path_value: Any) -> list[float]:
    path = [item for item in (as_point(value) for value in (path_value or [])) if item is not None]
    values: list[float] = []
    for a, b, c in zip(path, path[1:], path[2:]):
        v0 = np.asarray(b, dtype=np.float32) - np.asarray(a, dtype=np.float32)
        v1 = np.asarray(c, dtype=np.float32) - np.asarray(b, dtype=np.float32)
        n0, n1 = float(np.linalg.norm(v0)), float(np.linalg.norm(v1))
        if n0 < 4.0 or n1 < 4.0:
            continue
        cosine = float(np.dot(v0, v1) / (n0 * n1))
        # v0 and v1 both point in the direction of travel, so the direct angle
        # is the actual heading deflection: 0° is straight and 23° is the
        # shallow chamfer in the M21 corridor.
        values.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    return values


def gentle_corridor(update: dict[str, Any] | None, threshold: float) -> tuple[bool, float]:
    if not isinstance(update, dict):
        return False, 0.0
    deflections = route_deflections(update.get("path"))
    maximum = max(deflections, default=0.0)
    return maximum <= threshold, maximum


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    updates = load_updates(args.input_updates)
    anchors = enrich_anchors(updates)
    if not anchors:
        raise RuntimeError("no fresh AR anchors in localization updates")

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {args.video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_seconds = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0) / fps
    start = max(0.0, min(float(args.start), total_seconds))
    end = min(total_seconds, start + max(0.1, float(args.duration)))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)

    panel_size = (640, 360)
    safe_tag = "".join(char if char.isalnum() or char in "-_" else "_" for char in args.tag)
    comparison_path = next_video_path(args.output_dir, f"{safe_tag}_comparison")
    candidate_path = next_video_path(args.output_dir, safe_tag)
    writer = open_writer(comparison_path, (panel_size[0] * 2, panel_size[1]), fps)
    candidate_writer = open_writer(candidate_path, panel_size, fps)

    previous_gray: np.ndarray | None = None
    visual_polygons = []
    previous_anchor_index = -1
    last_anchor_time: float | None = None
    frames_written = 0
    gentle_frames = 0
    try:
        while True:
            ok, source_frame = cap.read()
            if not ok:
                break
            timestamp = float(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            if timestamp < start - 1.0 / fps:
                continue
            if timestamp > end + 1.0 / fps:
                break
            frame = cv2.resize(source_frame, panel_size, interpolation=cv2.INTER_AREA)
            anchor_index = anchor_index_at(anchors, timestamp)
            anchor = anchors[anchor_index] if anchor_index >= 0 else None
            baseline = payload_screen_polygons(anchor["payload"], frame.shape) if anchor else []
            update = anchor.get("update") if anchor else None
            is_gentle, max_deflection = gentle_corridor(update, float(args.gentle_angle))
            if anchor_index != previous_anchor_index and anchor is not None:
                visual_polygons = baseline
                previous_anchor_index = anchor_index
                last_anchor_time = float(anchor["timestamp"])
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            H = None
            inliers = 0
            residual = None
            if previous_gray is not None:
                H, inliers, residual = track_homography(previous_gray, gray)
                if not (H is not None and inliers >= 20 and residual is not None and residual <= 3.5):
                    H = None
            visual_polygons = bounded_visual_warp(visual_polygons, H, frame.shape)
            if not visual_polygons and baseline:
                visual_polygons = baseline

            display_polygons = strip_carets(visual_polygons) if is_gentle else visual_polygons
            if is_gentle:
                gentle_frames += 1
            age = None if last_anchor_time is None else max(0.0, timestamp - last_anchor_time)
            extra = f"mode={'gentle_corridor' if is_gentle else 'turn_cue'} max_defl={max_deflection:.1f}deg"
            if age is not None:
                extra += f" age={age:.2f}s"
            baseline_frame = draw_label(draw_overlay(frame, baseline), "BASELINE: REPEATED CARETS", timestamp, f"anchor={anchor_index}")
            candidate_frame = draw_label(draw_overlay(frame, display_polygons), "CONTINUOUS CORRIDOR: NO FAKE TURN", timestamp, extra)
            writer.write(np.hstack([baseline_frame, candidate_frame]))
            candidate_writer.write(candidate_frame)
            previous_gray = gray
            frames_written += 1
    finally:
        cap.release()
        writer.release()
        candidate_writer.release()

    summary = {
        "experiment": "continuous corridor rendering for shallow route deflection",
        "video": str(args.video),
        "input_updates": str(args.input_updates),
        "start_seconds": start,
        "end_seconds": end,
        "frames_written": frames_written,
        "fps": fps,
        "gentle_corridor_frames": gentle_frames,
        "gentle_corridor_seconds": gentle_frames / fps if fps else 0.0,
        "gentle_angle_threshold_deg": float(args.gentle_angle),
        "comparison_output": str(comparison_path),
        "candidate_output": str(candidate_path),
        "policy": "keep continuous floor ribbon; suppress repeated directional carets for shallow bends",
        "limitations": [
            "This fixes the semantic rendering of a shallow bend, not the underlying pose lag.",
            "The route is still projected from the existing cached pose stream.",
        ],
    }
    summary_path = args.output_dir / f"{safe_tag}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
