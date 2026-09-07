"""Render a visual-only stale-free AR experiment over the original video.

This is an experiment renderer, not a production code path. It compares the
old sparse-payload behaviour with a visual-tracking policy:

* KLT/homography propagates the last accepted visual overlay every frame.
* A fresh localization anchor corrects drift instead of replacing the overlay
  on every frame.
* A route-state change resets the visual track and suppresses old carets for a
  short hand-off window, so a passed turn cannot remain visible indefinitely.
* The stale policy is applied to turn carets only; the route ribbon remains
  available during the hand-off.
"""

from __future__ import annotations

import argparse
import copy
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
    fresh_anchors,
    load_updates,
    open_writer,
    payload_screen_polygons,
    safe_visual_warp,
    track_homography,
    translate_polygons,
)
from run_non_imu_video_comparison import overlay_centroid


Polygon = tuple[np.ndarray, tuple[int, int, int], float, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--input-updates", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "out")
    parser.add_argument("--start", type=float, default=80.0)
    parser.add_argument("--duration", type=float, default=100.0)
    parser.add_argument("--caret-suppress", type=float, default=0.75)
    return parser.parse_args()


def route_state(update: dict[str, Any] | None) -> str:
    """Return a stable state key instead of using changing turn distance."""
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
    nav_text = str(update.get("nav_text") or "").upper()
    if "ARRIVED" in nav_text:
        return "arrived"
    return "straight"


def strip_carets(polygons: list[Polygon]) -> list[Polygon]:
    return [item for item in polygons if item[3] != "caret"]


def blend_polygons(previous: list[Polygon], current: list[Polygon], alpha: float = 0.65) -> list[Polygon]:
    """Blend only matching polygons; otherwise trust the fresh anchor."""
    if len(previous) != len(current):
        return current
    blended: list[Polygon] = []
    for old, new in zip(previous, current):
        old_poly, old_color, old_alpha, old_kind = old
        new_poly, new_color, new_alpha, new_kind = new
        if old_kind != new_kind or old_poly.shape != new_poly.shape:
            return current
        blended.append(
            (
                (1.0 - alpha) * old_poly + alpha * new_poly,
                new_color,
                new_alpha,
                new_kind,
            )
        )
    return blended


def bounded_visual_warp(
    polygons: list[Polygon],
    H: np.ndarray | None,
    frame_shape: tuple[int, ...],
) -> list[Polygon]:
    """Reject optical-flow warps that move the overlay implausibly in one frame."""
    warped = safe_visual_warp(polygons, H, frame_shape)
    if H is None or not polygons or not warped:
        return warped
    old_centroid = overlay_centroid(polygons)
    new_centroid = overlay_centroid(warped)
    if old_centroid is None or new_centroid is None:
        return warped
    displacement = math.hypot(new_centroid[0] - old_centroid[0], new_centroid[1] - old_centroid[1])
    max_displacement = max(45.0, 0.18 * min(frame_shape[0], frame_shape[1]))
    if displacement > max_displacement:
        return polygons
    return warped


def draw_overlay(frame: np.ndarray, polygons: list[Polygon]) -> np.ndarray:
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


def update_lookup(anchors: list[dict[str, Any]], timestamp: float) -> dict[str, Any] | None:
    index = anchor_index_at(anchors, timestamp)
    if index < 0:
        return None
    return anchors[index].get("update")


def enrich_anchors(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors = fresh_anchors(updates)
    by_timestamp = {
        round(float(item.get("timestamp", 0.0)), 6): item
        for item in updates
        if isinstance(item.get("timestamp"), (int, float))
    }
    for anchor in anchors:
        anchor["update"] = by_timestamp.get(round(float(anchor["timestamp"]), 6))
        anchor["route_state"] = route_state(anchor.get("update"))
    return anchors


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    updates_path = args.input_updates or (args.output_dir / "non_imu_1p5s_localization_updates.json")
    updates = load_updates(updates_path)
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
    comparison_path = args.output_dir / "non_imu_stale_free_ar_turns_80_180_comparison.mp4"
    improved_path = args.output_dir / "non_imu_stale_free_ar_turns_80_180.mp4"
    writer = open_writer(comparison_path, (panel_size[0] * 2, panel_size[1]), fps)
    improved_writer = open_writer(improved_path, panel_size, fps)

    previous_gray: np.ndarray | None = None
    visual_polygons: list[Polygon] = []
    previous_anchor_index = -1
    previous_state = "unknown"
    caret_suppress_until = -1.0
    frames_written = 0
    flow_ok = 0
    flow_total = 0
    state_changes = 0
    caret_suppressed_frames = 0
    last_anchor_time: float | None = None

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
            current_state = anchor.get("route_state", "unknown") if anchor else previous_state
            anchor_changed = anchor_index != previous_anchor_index and anchor is not None

            if anchor_changed:
                last_anchor_time = float(anchor["timestamp"])
                if current_state != previous_state:
                    state_changes += 1
                    # Do not carry the previous turn across a route-state
                    # boundary. The fresh anchor becomes the new base; the
                    # short suppression window hides any caret during handoff.
                    visual_polygons = baseline
                    caret_suppress_until = timestamp + float(args.caret_suppress)
                else:
                    # Re-anchor every fresh localization. This prevents KLT
                    # drift from accumulating across many 1.5s intervals and
                    # also restores the current caret set after handoff.
                    visual_polygons = blend_polygons(visual_polygons, baseline)
                previous_state = current_state
                previous_anchor_index = anchor_index

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
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
            visual_polygons = bounded_visual_warp(visual_polygons, H, frame.shape)
            if not visual_polygons and baseline:
                visual_polygons = baseline

            display_polygons = visual_polygons
            if timestamp < caret_suppress_until:
                display_polygons = strip_carets(display_polygons)
                caret_suppressed_frames += 1

            age = None if last_anchor_time is None else max(0.0, timestamp - last_anchor_time)
            extra = f"state={current_state}"
            if age is not None:
                extra += f" age={age:.2f}s"
            extra += f" inliers={inliers}"
            baseline_frame = draw_label(draw_overlay(frame, baseline), "BASELINE: HOLD PAYLOAD", timestamp, f"anchor={anchor_index}")
            improved_frame = draw_label(draw_overlay(frame, display_polygons), "STALE-FREE: KLT + TURN GATING", timestamp, extra)
            writer.write(np.hstack([baseline_frame, improved_frame]))
            improved_writer.write(improved_frame)
            previous_gray = gray
            frames_written += 1
            if frames_written % int(max(1, fps * 10)) == 0:
                print(f"[stale-free] {timestamp:6.1f}s / {end:6.1f}s, frames={frames_written}, flow={flow_ok}/{flow_total}, state_changes={state_changes}")
    finally:
        cap.release()
        writer.release()
        improved_writer.release()

    summary = {
        "video": str(args.video),
        "input_updates": str(updates_path),
        "start_seconds": start,
        "end_seconds": end,
        "duration_seconds": end - start,
        "source_fps": fps,
        "frames_written": frames_written,
        "anchor_count": len(anchors),
        "flow_accepted": flow_ok,
        "flow_attempts": flow_total,
        "flow_accept_rate": flow_ok / max(flow_total, 1),
        "route_state_changes": state_changes,
        "caret_suppress_seconds": float(args.caret_suppress),
        "caret_suppressed_frames": caret_suppressed_frames,
        "comparison_output": str(comparison_path),
        "improved_output": str(improved_path),
        "policy": "full-rate KLT propagation + fresh-anchor correction + route-state reset + short caret hand-off",
    }
    summary_path = args.output_dir / "non_imu_stale_free_ar_turns_80_180_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
