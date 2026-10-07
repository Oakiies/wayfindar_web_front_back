"""Compare raw buffered world poses with turn-preserving pose stabilization."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from render_fullrate_non_imu_ar import DEFAULT_VIDEO, draw_label, open_writer, payload_screen_polygons
from render_graph_exhaustive_poc import load_graph, map_panel, point
from render_registration_replay import interpolate_camera
from render_stale_free_ar import draw_overlay, strip_carets
from render_world_approach_graph_poc import load_jsonl, polygon_bounds
from poc_ar_arrow.ar_arrow_v2 import route_guidance_mode
from video_naming import next_video_path


PANEL = (640, 360)
TURN_PROTECT_DEG = 8.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--world-updates", type=Path, required=True)
    parser.add_argument("--graph-json", type=Path, required=True)
    parser.add_argument("--map-image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=float, default=24.0)
    parser.add_argument("--end", type=float, default=50.0)
    parser.add_argument("--tag", default="stabilized_world_graph_24_50")
    return parser.parse_args()


def camera_pose(payload: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    rotation = np.asarray(payload["R"], dtype=np.float64).reshape(3, 3)
    translation = np.asarray(payload["t"], dtype=np.float64).reshape(3)
    return rotation, -rotation.T @ translation


def rotation_delta_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(float(np.linalg.norm(cv2.Rodrigues(b @ a.T)[0])))


def weighted_rotation(items: list[np.ndarray], weights: list[float]) -> np.ndarray:
    matrix = sum(weight * rotation for rotation, weight in zip(items, weights))
    u, _, vt = np.linalg.svd(matrix)
    result = u @ vt
    if np.linalg.det(result) < 0:
        u[:, -1] *= -1.0
        result = u @ vt
    return result


def valid_pose_row(row: dict[str, Any]) -> bool:
    return isinstance(row.get("ar_world"), dict) and row.get("method") != "HOLD_LAST_FIX"


def pose_bracket(rows: list[dict[str, Any]], timestamp: float):
    left = None
    right = None
    for row in rows:
        if not valid_pose_row(row):
            continue
        if float(row.get("timestamp", 0.0)) <= timestamp:
            left = row
        else:
            right = row
            break
    return left, right


def stabilize_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Smooth straight-run anchors without averaging across turns or gaps."""
    output = copy.deepcopy(rows)
    smoothed_centres = 0
    smoothed_rotations = 0
    protected_turns = 0
    for index in range(1, len(rows) - 1):
        previous, current, following = rows[index - 1:index + 2]
        if not all(valid_pose_row(row) for row in (previous, current, following)):
            continue
        if (float(current["timestamp"]) - float(previous["timestamp"]) > 1.65 or
                float(following["timestamp"]) - float(current["timestamp"]) > 1.65 or
                len({previous.get("current_floor"), current.get("current_floor"), following.get("current_floor")}) != 1):
            continue

        rp, cp = camera_pose(previous["ar_world"])
        rc, cc = camera_pose(current["ar_world"])
        rn, cn = camera_pose(following["ar_world"])
        filtered_centre = 0.20 * cp + 0.60 * cc + 0.20 * cn
        incoming = rotation_delta_deg(rp, rc)
        outgoing = rotation_delta_deg(rc, rn)
        if max(incoming, outgoing) >= TURN_PROTECT_DEG:
            filtered_rotation = rc
            protected_turns += 1
        else:
            filtered_rotation = weighted_rotation([rp, rc, rn], [0.20, 0.60, 0.20])
            smoothed_rotations += 1
        payload = output[index]["ar_world"]
        payload["R"] = filtered_rotation.tolist()
        payload["t"] = (-filtered_rotation @ filtered_centre).tolist()
        smoothed_centres += 1
    return output, {
        "centre_anchors_smoothed": smoothed_centres,
        "rotation_anchors_smoothed": smoothed_rotations,
        "turn_anchors_protected": protected_turns,
        "turn_protect_deg": TURN_PROTECT_DEG,
        "weights": [0.20, 0.60, 0.20],
    }


def semantic_polygons(payload: dict[str, Any] | None, row: dict[str, Any] | None, shape: tuple[int, ...]):
    polygons = payload_screen_polygons(payload, shape)
    position = point((row or {}).get("position"))
    mode, bend = "unknown", 0.0
    if position is not None:
        mode, bend = route_guidance_mode(position[0], position[1], (row or {}).get("path") or [])
        if mode == "gentle_corridor":
            polygons = strip_carets(polygons)
    return polygons, mode, bend


def motion_jerk(records: list[dict[str, Any]], key: str) -> dict[str, float | int]:
    values = []
    previous_velocity = None
    previous_centre = None
    previous_frame = None
    for record in records:
        bounds = record.get(key)
        if bounds is None:
            previous_velocity = previous_centre = previous_frame = None
            continue
        centre = np.asarray([(bounds["x0"] + bounds["x1"]) / 2.0,
                             (bounds["y0"] + bounds["y1"]) / 2.0])
        frame = int(record["frame"])
        if previous_centre is not None and frame == previous_frame + 1:
            velocity = centre - previous_centre
            if previous_velocity is not None:
                values.append(float(np.linalg.norm(velocity - previous_velocity)))
            previous_velocity = velocity
        else:
            previous_velocity = None
        previous_centre, previous_frame = centre, frame
    if not values:
        return {"samples": 0, "median_px_per_frame2": 0.0, "p95_px_per_frame2": 0.0}
    return {
        "samples": len(values),
        "median_px_per_frame2": float(np.median(values)),
        "p95_px_per_frame2": float(np.percentile(values, 95)),
    }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_rows = load_jsonl(args.world_updates)
    stable_rows, filter_stats = stabilize_rows(raw_rows)
    positions, edges, labels = load_graph(args.graph_json)
    map_image = cv2.imread(str(args.map_image), cv2.IMREAD_COLOR)
    if map_image is None:
        raise RuntimeError(f"cannot read map image: {args.map_image}")

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {args.video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_seconds = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0) / fps
    start = max(0.0, min(float(args.start), total_seconds))
    end = max(start + 0.1, min(float(args.end), total_seconds))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
    safe_tag = "".join(char if char.isalnum() or char in "-_" else "_" for char in args.tag)
    comparison_path = next_video_path(args.output_dir, f"{safe_tag}_comparison")
    candidate_path = next_video_path(args.output_dir, safe_tag)
    writer = open_writer(comparison_path, (PANEL[0] * 3, PANEL[1]), fps)
    candidate_writer = open_writer(candidate_path, PANEL, fps)
    records = []
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
            frame_index = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            frame = cv2.resize(source_frame, PANEL, interpolation=cv2.INTER_AREA)
            raw_left, raw_right = pose_bracket(raw_rows, timestamp)
            stable_left, stable_right = pose_bracket(stable_rows, timestamp)
            raw_payload = interpolate_camera(raw_left, raw_right, timestamp)
            stable_payload = interpolate_camera(stable_left, stable_right, timestamp)
            raw_polygons, mode, bend = semantic_polygons(raw_payload, raw_left, frame.shape)
            stable_polygons, _, _ = semantic_polygons(stable_payload, stable_left, frame.shape)
            age = None if raw_left is None else max(0.0, timestamp - float(raw_left["timestamp"]))
            raw_frame = draw_label(draw_overlay(frame, raw_polygons), "RAW WORLD POSE", timestamp, f"mode={mode}")
            stable_frame = draw_label(draw_overlay(frame, stable_polygons), "TURN-PROTECTED STABLE POSE", timestamp, f"bend={bend:.1f}deg")
            top_frame = map_panel(map_image, positions, edges, labels, raw_left, age, frame_index, timestamp)
            writer.write(np.hstack([raw_frame, stable_frame, top_frame]))
            candidate_writer.write(stable_frame)
            records.append({
                "frame": frame_index,
                "timestamp": timestamp,
                "raw_bounds": polygon_bounds(raw_polygons),
                "stable_bounds": polygon_bounds(stable_polygons),
                "pose_available": stable_payload is not None,
                "guidance_mode": mode,
            })
    finally:
        cap.release()
        writer.release()
        candidate_writer.release()

    summary = {
        "experiment": "turn-protected world-pose stabilization",
        "video": str(args.video),
        "start_seconds": start,
        "end_seconds": end,
        "frames_reviewed": len(records),
        "filter": filter_stats,
        "raw_screen_motion_jerk": motion_jerk(records, "raw_bounds"),
        "stable_screen_motion_jerk": motion_jerk(records, "stable_bounds"),
        "comparison_output": str(comparison_path),
        "candidate_output": str(candidate_path),
        "records_output": str(args.output_dir / f"{safe_tag}_per_frame.json"),
        "constraint": "Only camera pose is filtered. Route geometry stays fixed in world coordinates; no screen-space polygon smoothing is used.",
        "replay_limit": "Centered anchor filtering and buffered interpolation are replay-only; live use requires a causal pose filter over target-frame PnP.",
    }
    (args.output_dir / f"{safe_tag}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (args.output_dir / f"{safe_tag}_per_frame.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
