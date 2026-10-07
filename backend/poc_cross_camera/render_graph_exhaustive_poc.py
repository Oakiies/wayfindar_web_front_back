"""Exhaustive per-frame AR review with the floor graph and top-down route.

This is an inspection PoC. It does not rebuild the map or run new localization.
It replays every source video frame in the selected interval, carries the
existing cached AR anchor with KLT between anchors, and places the graph/map
panel beside the camera views so route semantics can be checked visually.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
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

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from app.core.navigation import path_turn_angle
from poc_ar_arrow.ar_arrow_v2 import route_guidance_mode


PANEL = (640, 360)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--input-updates", type=Path, required=True)
    parser.add_argument("--graph-json", type=Path, required=True)
    parser.add_argument("--map-image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=float, default=24.0)
    parser.add_argument("--end", type=float, default=50.0)
    parser.add_argument("--gentle-angle", type=float, default=40.0)
    parser.add_argument("--tag", type=str, default="graph_exhaustive_24_50")
    return parser.parse_args()


def point(value: Any) -> tuple[float, float] | None:
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
    path = [item for item in (point(value) for value in (path_value or [])) if item is not None]
    values: list[float] = []
    for a, b, c in zip(path, path[1:], path[2:]):
        v0 = np.asarray(b) - np.asarray(a)
        v1 = np.asarray(c) - np.asarray(b)
        n0, n1 = float(np.linalg.norm(v0)), float(np.linalg.norm(v1))
        if n0 < 4.0 or n1 < 4.0:
            continue
        cosine = float(np.dot(v0, v1) / (n0 * n1))
        values.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    return values


def route_is_gentle(update: dict[str, Any] | None, threshold: float) -> tuple[bool, float]:
    if not isinstance(update, dict):
        return False, 0.0
    values = route_deflections(update.get("path"))
    maximum = max(values, default=0.0)
    position = point(update.get("position"))
    if position is None:
        return False, maximum
    # Use the production candidate's position-aware semantic classifier. The
    # earlier inspection-only rule looked only at the maximum angle anywhere
    # in the route, so it could not prove that the shipped logic avoided
    # flickering before, inside, and after a two-node chamfer.
    mode, _ = route_guidance_mode(position[0], position[1], update.get("path") or [])
    return mode == "gentle_corridor", maximum


def load_graph(path: Path) -> tuple[dict[str, tuple[float, float]], list[tuple[str, str]], dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))["graph"]
    positions: dict[str, tuple[float, float]] = {}
    labels: dict[str, str] = {}
    for node_id, node in data.get("nodes", {}).items():
        metadata = node.get("metadata", {})
        item = point(metadata.get("position"))
        if item is None:
            continue
        positions[node_id] = item
        labels[node_id] = str(node.get("label") or node_id)
    edges = [
        (str(edge.get("source")), str(edge.get("target")))
        for edge in data.get("edges", [])
        if str(edge.get("source")) in positions and str(edge.get("target")) in positions
    ]
    return positions, edges, labels


def nearest_node(value: Any, positions: dict[str, tuple[float, float]]) -> str | None:
    item = point(value)
    if item is None or not positions:
        return None
    return min(positions, key=lambda key: math.hypot(item[0] - positions[key][0], item[1] - positions[key][1]))


def route_node_labels(path_value: Any, positions: dict[str, tuple[float, float]], labels: dict[str, str]) -> list[str]:
    result: list[str] = []
    for item in path_value or []:
        node_id = nearest_node(item, positions)
        if node_id is None:
            continue
        label = labels.get(node_id, node_id)
        if not result or result[-1] != label:
            result.append(label)
    return result


def fit_map(map_image: np.ndarray, panel_size: tuple[int, int]) -> tuple[np.ndarray, float, int, int]:
    panel_w, panel_h = panel_size
    canvas = np.full((panel_h, panel_w, 3), (28, 32, 38), dtype=np.uint8)
    height, width = map_image.shape[:2]
    scale = min((panel_w - 24) / width, (panel_h - 48) / height)
    resized = cv2.resize(map_image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    left = (panel_w - resized.shape[1]) // 2
    top = 42
    canvas[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
    return canvas, scale, left, top


def map_panel(
    map_image: np.ndarray,
    positions: dict[str, tuple[float, float]],
    edges: list[tuple[str, str]],
    labels: dict[str, str],
    update: dict[str, Any] | None,
    anchor_age: float | None,
    frame_index: int,
    timestamp: float,
) -> np.ndarray:
    panel, scale, left, top = fit_map(map_image, PANEL)

    def xy(item: tuple[float, float]) -> tuple[int, int]:
        return round(left + item[0] * scale), round(top + item[1] * scale)

    # Draw the complete graph so branch topology is visible even where the
    # selected route overlaps another corridor.
    for source, target in edges:
        cv2.line(panel, xy(positions[source]), xy(positions[target]), (110, 115, 125), 1, cv2.LINE_AA)
    for node_id, item in positions.items():
        label = labels.get(node_id, node_id)
        color = (80, 120, 210) if "Intersection" in label else (90, 90, 90)
        cv2.circle(panel, xy(item), 3 if "Intersection" in label else 2, color, -1, cv2.LINE_AA)
        if "Intersection" in label or label in {"M21_A", "M23_A", "M23_B", "M22_A"}:
            px, py = xy(item)
            cv2.putText(panel, label.replace("Intersection ", "I"), (px + 5, py - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (35, 35, 35), 1, cv2.LINE_AA)

    route = [item for item in (point(value) for value in ((update or {}).get("path") or [])) if item is not None]
    if len(route) >= 2:
        route_points = np.asarray([xy(item) for item in route], dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(panel, [route_points], False, (255, 80, 30), 4, cv2.LINE_AA)

    position = point((update or {}).get("position"))
    if position is not None:
        px, py = xy(position)
        cv2.circle(panel, (px, py), 8, (255, 0, 180), 2, cv2.LINE_AA)
        cv2.circle(panel, (px, py), 3, (255, 0, 180), -1, cv2.LINE_AA)

    destination = point((update or {}).get("destination_coords"))
    if destination is not None:
        cv2.drawMarker(panel, xy(destination), (0, 80, 255), cv2.MARKER_STAR, 14, 2, cv2.LINE_AA)

    cv2.rectangle(panel, (0, 0), (PANEL[0], 38), (28, 32, 38), -1)
    cv2.putText(panel, f"TOP-DOWN GRAPH | frame={frame_index} t={timestamp:5.2f}s", (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (245, 250, 255), 1, cv2.LINE_AA)
    route_labels = route_node_labels((update or {}).get("path"), positions, labels)
    cv2.putText(panel, "route: " + " -> ".join(route_labels), (8, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (220, 230, 240), 1, cv2.LINE_AA)
    if anchor_age is not None:
        cv2.putText(panel, f"anchor age {anchor_age:.2f}s | magenta=user  orange=route", (8, PANEL[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (40, 40, 40), 1, cv2.LINE_AA)
    return panel


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    updates = load_updates(args.input_updates)
    anchors = enrich_anchors(updates)
    if not anchors:
        raise RuntimeError("no fresh AR anchors")
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

    previous_gray: np.ndarray | None = None
    visual_polygons = []
    previous_anchor_index = -1
    last_anchor_time: float | None = None
    records: list[dict[str, Any]] = []
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
            anchor_index = anchor_index_at(anchors, timestamp)
            anchor = anchors[anchor_index] if anchor_index >= 0 else None
            update = anchor.get("update") if anchor else None
            baseline = payload_screen_polygons(anchor["payload"], frame.shape) if anchor else []
            if anchor_index != previous_anchor_index and anchor is not None:
                visual_polygons = baseline
                previous_anchor_index = anchor_index
                last_anchor_time = float(anchor["timestamp"])
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            H, inliers, residual = (None, 0, None)
            if previous_gray is not None:
                H, inliers, residual = track_homography(previous_gray, gray)
                if not (H is not None and inliers >= 20 and residual is not None and residual <= 3.5):
                    H = None
            visual_polygons = bounded_visual_warp(visual_polygons, H, frame.shape)
            if not visual_polygons and baseline:
                visual_polygons = baseline

            gentle, max_deflection = route_is_gentle(update, float(args.gentle_angle))
            candidate_polygons = strip_carets(visual_polygons) if gentle else visual_polygons
            age = None if last_anchor_time is None else max(0.0, timestamp - last_anchor_time)
            bend = None
            if path_turn_angle is not None and update and point(update.get("position")) is not None:
                pos = point(update.get("position"))
                try:
                    bend = float(path_turn_angle(pos[0], pos[1], update.get("path") or []))
                except (TypeError, ValueError, IndexError):
                    bend = None

            baseline_frame = draw_label(
                draw_overlay(frame, baseline),
                "BASELINE / CURRENT CACHED AR",
                timestamp,
                f"carets={sum(kind == 'caret' for _, _, _, kind in baseline)} anchor={anchor_index}",
            )
            candidate_frame = draw_label(
                draw_overlay(frame, candidate_polygons),
                "CANDIDATE / CONTINUOUS ROUTE",
                timestamp,
                f"mode={'gentle' if gentle else 'directional'} bend={bend if bend is not None else max_deflection:.1f}deg age={age if age is not None else -1:.2f}s",
            )
            top_frame = map_panel(map_image, positions, edges, labels, update, age, frame_index, timestamp)
            writer.write(np.hstack([baseline_frame, candidate_frame, top_frame]))
            candidate_writer.write(candidate_frame)
            records.append({
                "frame": frame_index,
                "timestamp": timestamp,
                "anchor_index": anchor_index,
                "anchor_age_s": age,
                "flow_inliers": int(inliers),
                "flow_residual": None if residual is None else float(residual),
                "baseline_carets": int(sum(kind == "caret" for _, _, _, kind in baseline)),
                "candidate_carets": int(sum(kind == "caret" for _, _, _, kind in candidate_polygons)),
                "gentle_corridor": bool(gentle),
                "route_max_deflection_deg": float(max_deflection),
                "local_path_turn_deg": bend,
                "position": None if update is None else update.get("position"),
                "nav_text": None if update is None else update.get("nav_text"),
            })
            previous_gray = gray
    finally:
        cap.release()
        writer.release()
        candidate_writer.release()

    frame_count = len(records)
    gentle_count = sum(item["gentle_corridor"] for item in records)
    baseline_caret_frames = sum(item["baseline_carets"] > 0 for item in records)
    candidate_caret_frames = sum(item["candidate_carets"] > 0 for item in records)
    route_labels = route_node_labels(anchors[0].get("update", {}).get("path"), positions, labels)
    summary = {
        "experiment": "exhaustive every-frame AR review with graph/map panel",
        "video": str(args.video),
        "input_updates": str(args.input_updates),
        "graph_json": str(args.graph_json),
        "map_image": str(args.map_image),
        "start_seconds": start,
        "end_seconds": end,
        "fps": fps,
        "frames_reviewed": frame_count,
        "all_frames_in_interval": True,
        "anchor_count_available": len(anchors),
        "gentle_corridor_frames": gentle_count,
        "baseline_frames_with_carets": baseline_caret_frames,
        "candidate_frames_with_carets": candidate_caret_frames,
        "route_node_sequence_by_map_nearest": route_labels,
        "graph_nodes": len(positions),
        "graph_edges": len(edges),
        "comparison_output": str(comparison_path),
        "candidate_output": str(candidate_path),
        "records_output": str(args.output_dir / f"{safe_tag}_per_frame.json"),
        "interpretation": "The selected M21 path follows the direct graph edge Intersection 1 -> M23_B; Intersection 1 has alternate forward branches via M23_A and Intersection 2. The visible shallow direction change is route geometry, not a discrete 90-degree turn.",
    }
    summary_path = args.output_dir / f"{safe_tag}_summary.json"
    records_path = args.output_dir / f"{safe_tag}_per_frame.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
