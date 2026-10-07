"""Render a conservative no-IMU turn hand-off experiment.

This PoC addresses the observed 34s failure in two stages:

* route geometry identifies the next corner from the existing path;
* visual motion starts a hand-off, during which old AR geometry is hidden;
* the hand-off ends only after the fresh pose has passed the corner.

It intentionally prefers a short AR blank over showing a stale turn. It does
not create a map and it does not modify the production frontend/backend.
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
    fresh_anchors,
    load_updates,
    open_writer,
    payload_screen_polygons,
    safe_visual_warp,
    track_homography,
)
from render_stale_free_ar import (
    bounded_visual_warp,
    draw_overlay,
    enrich_anchors,
    strip_carets,
)
from video_naming import next_video_path


Point = tuple[float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--input-updates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=float, default=28.0)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--tag", type=str, default="turn_handoff")
    parser.add_argument("--turn-trigger-distance", type=float, default=34.0)
    parser.add_argument("--turn-complete-margin", type=float, default=7.0)
    parser.add_argument("--motion-dx-threshold", type=float, default=0.35)
    parser.add_argument("--settle-seconds", type=float, default=0.25)
    return parser.parse_args()


def point(value: Any) -> Point | None:
    if isinstance(value, dict):
        value = [value.get("x"), value.get("y")]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return x, y


def route_corners(path_value: Any) -> list[dict[str, Any]]:
    path = [item for item in (point(value) for value in (path_value or [])) if item is not None]
    corners: list[dict[str, Any]] = []
    cumulative = 0.0
    for index in range(1, len(path)):
        cumulative += math.dist(path[index - 1], path[index])
        if index >= len(path) - 1:
            continue
        a = np.asarray(path[index - 1], dtype=np.float32)
        b = np.asarray(path[index], dtype=np.float32)
        c = np.asarray(path[index + 1], dtype=np.float32)
        v0 = a - b
        v1 = c - b
        n0, n1 = float(np.linalg.norm(v0)), float(np.linalg.norm(v1))
        if n0 < 4.0 or n1 < 4.0:
            continue
        cosine = float(np.dot(v0, v1) / (n0 * n1))
        turn_angle = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
        if turn_angle < 18.0:
            continue
        incoming = b - a
        outgoing = c - b
        cross = float(incoming[0] * outgoing[1] - incoming[1] * outgoing[0])
        corners.append({
            "index": index,
            "point": path[index],
            "progress": cumulative,
            "angle_deg": turn_angle,
            "direction": "left" if cross > 0 else "right",
        })
    # A mapped diagonal corner often appears as two small deflections at its
    # entry and exit. Treat that short cluster as one manoeuvre and use its
    # exit point for completion; otherwise the gate can report "completed"
    # while the user is still inside the diagonal transition.
    clustered: list[dict[str, Any]] = []
    for corner in corners:
        if clustered and corner["progress"] - clustered[-1]["progress"] <= 75.0:
            clustered[-1] = corner
        else:
            clustered.append(corner)
    return clustered


def route_progress(path_value: Any, position_value: Any) -> tuple[float, list[dict[str, Any]]] | None:
    path = [item for item in (point(value) for value in (path_value or [])) if item is not None]
    position = point(position_value)
    if len(path) < 2 or position is None:
        return None
    p = np.asarray(position, dtype=np.float32)
    best_distance = float("inf")
    best_progress = 0.0
    cumulative = 0.0
    for start, end in zip(path, path[1:]):
        a, b = np.asarray(start, dtype=np.float32), np.asarray(end, dtype=np.float32)
        vector = b - a
        length_sq = float(np.dot(vector, vector))
        ratio = 0.0 if length_sq <= 1e-9 else float(np.dot(p - a, vector) / length_sq)
        ratio = max(0.0, min(1.0, ratio))
        projection = a + ratio * vector
        distance = float(np.linalg.norm(p - projection))
        if distance < best_distance:
            best_distance = distance
            best_progress = cumulative + ratio * math.sqrt(length_sq)
        cumulative += math.sqrt(length_sq)
    return best_progress, route_corners(path_value)


def homography_center_dx(H: np.ndarray | None, frame_shape: tuple[int, ...]) -> float:
    if H is None:
        return 0.0
    width, height = float(frame_shape[1]), float(frame_shape[0])
    center = np.asarray([[[width / 2.0, height / 2.0]]], dtype=np.float32)
    try:
        projected = cv2.perspectiveTransform(center, H).reshape(2)
        dx = float(projected[0] - center.reshape(2)[0])
        return dx if math.isfinite(dx) else 0.0
    except cv2.error:
        return 0.0


def corner_status(update: dict[str, Any] | None, trigger: float, margin: float) -> dict[str, Any]:
    if not isinstance(update, dict):
        return {"stage": "unknown", "corner": None, "distance_ahead": None, "progress": None}
    result = route_progress(update.get("path"), update.get("position"))
    if result is None:
        return {"stage": "unknown", "corner": None, "distance_ahead": None, "progress": None}
    progress, corners = result
    previous_corner = next((corner for corner in reversed(corners) if corner["progress"] < progress), None)
    next_corner = next((corner for corner in corners if corner["progress"] >= progress), None)
    if previous_corner is not None and progress - previous_corner["progress"] > margin:
        # Keep the most recent corner as the completed event. This is the
        # signal that prevents a pre-turn overlay from being restored.
        distance_ahead = float(previous_corner["progress"] - progress)
        return {
            "stage": "turn_completed",
            "corner": previous_corner,
            "distance_ahead": distance_ahead,
            "progress": progress,
        }
    if next_corner is None:
        if previous_corner is not None:
            distance_ahead = float(previous_corner["progress"] - progress)
            return {
                "stage": "approaching_turn",
                "corner": previous_corner,
                "distance_ahead": distance_ahead,
                "progress": progress,
            }
        return {"stage": "straight", "corner": None, "distance_ahead": None, "progress": progress}
    distance_ahead = float(next_corner["progress"] - progress)
    if distance_ahead <= trigger:
        stage = "approaching_turn"
    else:
        stage = "straight"
    return {
        "stage": stage,
        "corner": next_corner,
        "distance_ahead": distance_ahead,
        "progress": progress,
    }


def format_extra(status: dict[str, Any], dx: float, handoff: str, age: float | None) -> str:
    parts = [f"handoff={handoff}", f"route={status['stage']}", f"dx={dx:.2f}"]
    if status.get("distance_ahead") is not None:
        parts.append(f"corner_d={status['distance_ahead']:.1f}")
    if age is not None:
        parts.append(f"age={age:.2f}s")
    return " ".join(parts)


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
    start = max(0.0, min(args.start, total_seconds))
    end = min(total_seconds, start + max(0.1, args.duration))
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
    previous_status = "unknown"
    handoff = "normal"
    handoff_started: float | None = None
    settle_started: float | None = None
    last_anchor_time: float | None = None
    frames_written = 0
    hidden_frames = 0
    completed = False
    max_corner_distance = None
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
            status = corner_status(update, args.turn_trigger_distance, args.turn_complete_margin)
            route_stage = status["stage"]
            if status.get("distance_ahead") is not None:
                max_corner_distance = status["distance_ahead"]

            anchor_changed = anchor_index != previous_anchor_index and anchor is not None
            if anchor_changed:
                last_anchor_time = float(anchor["timestamp"])
                previous_anchor_index = anchor_index
                if route_stage == "turn_completed" and handoff != "normal":
                    # Rebuild from the first fresh post-corner anchor; never
                    # blend the pre-turn geometry across this boundary.
                    handoff = "completed"
                    completed = True
                    visual_polygons = baseline
                    settle_started = timestamp
                elif previous_status != route_stage and route_stage == "approaching_turn":
                    # The route has a corner ahead. Keep a fresh base, but do
                    # not carry an older turn caret through the visual handoff.
                    visual_polygons = baseline
                elif not visual_polygons:
                    visual_polygons = baseline
                previous_status = route_stage

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            H = None
            inliers = 0
            residual = None
            dx = 0.0
            if previous_gray is not None:
                H, inliers, residual = track_homography(previous_gray, gray)
                if H is not None and inliers >= 20 and residual is not None and residual <= 3.5:
                    dx = homography_center_dx(H, frame.shape)
                else:
                    H = None
            visual_polygons = bounded_visual_warp(visual_polygons, H, frame.shape)
            if not visual_polygons and baseline and handoff == "normal":
                visual_polygons = baseline

            # A signed center shift is only a trigger. Route geometry decides
            # which corner may be handed off, so ordinary forward walking does
            # not blank the AR view everywhere.
            near_corner = route_stage in {"approaching_turn", "turn_completed"}
            if handoff == "normal" and near_corner and abs(dx) >= args.motion_dx_threshold:
                handoff = "turning"
                handoff_started = timestamp
                settle_started = None
            elif handoff == "turning":
                if abs(dx) < args.motion_dx_threshold:
                    settle_started = settle_started or timestamp
                else:
                    settle_started = None
                # Do not end on visual settling alone. The fresh map pose must
                # also pass the route corner, otherwise old geometry can return.
                if route_stage == "turn_completed" and settle_started is not None and timestamp - settle_started >= args.settle_seconds:
                    handoff = "completed"
                    completed = True
                    visual_polygons = baseline
            if handoff == "completed" and route_stage == "turn_completed":
                # Keep the visual handoff quiet briefly, then show the fresh
                # post-turn route. This is a conservative no-wrong-cue policy.
                if settle_started is not None and timestamp - settle_started < args.settle_seconds:
                    display_polygons = []
                else:
                    display_polygons = visual_polygons
            elif handoff == "turning":
                display_polygons = []
            else:
                display_polygons = visual_polygons

            if not display_polygons and handoff in {"turning", "completed"}:
                hidden_frames += 1
            age = None if last_anchor_time is None else max(0.0, timestamp - last_anchor_time)
            extra = format_extra(status, dx, handoff, age)
            baseline_frame = draw_label(draw_overlay(frame, baseline), "BASELINE: HOLD PAYLOAD", timestamp, f"anchor={anchor_index}")
            candidate_frame = draw_label(draw_overlay(frame, display_polygons), "TURN HANDOFF: VISUAL-ONLY SAFE GATE", timestamp, extra)
            writer.write(np.hstack([baseline_frame, candidate_frame]))
            candidate_writer.write(candidate_frame)
            previous_gray = gray
            frames_written += 1
    finally:
        cap.release()
        writer.release()
        candidate_writer.release()

    summary = {
        "experiment": "visual-only turn handoff with route-corner completion gate",
        "video": str(args.video),
        "input_updates": str(args.input_updates),
        "start_seconds": start,
        "end_seconds": end,
        "frames_written": frames_written,
        "fps": fps,
        "hidden_frames": hidden_frames,
        "hidden_seconds": hidden_frames / fps if fps else 0.0,
        "turn_completed_seen": completed,
        "last_corner_distance": max_corner_distance,
        "thresholds": {
            "turn_trigger_distance": args.turn_trigger_distance,
            "turn_complete_margin": args.turn_complete_margin,
            "motion_dx_threshold": args.motion_dx_threshold,
            "settle_seconds": args.settle_seconds,
        },
        "comparison_output": str(comparison_path),
        "candidate_output": str(candidate_path),
        "policy": "hide old AR during visual turn handoff; restore only after fresh pose passes route corner",
    }
    summary_path = args.output_dir / f"{safe_tag}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
