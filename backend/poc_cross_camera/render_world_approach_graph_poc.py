"""Compare screen-warped AR with world-projected route geometry.

The left pane intentionally reproduces the rejected V2 KLT/homography policy:
already-projected polygons are warped in image coordinates. The middle pane
keeps route geometry in world coordinates and reprojects it with a bounded
interpolation of accepted camera poses. The latter is valid only for recorded
replay because it uses the next buffered pose; live AR still needs target-frame
tracked-landmark PnP.
"""

from __future__ import annotations

import argparse
import json
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
from render_graph_exhaustive_poc import load_graph, map_panel, point
from render_registration_replay import interpolate_camera
from render_stale_free_ar import bounded_visual_warp, draw_overlay, enrich_anchors, strip_carets
from poc_ar_arrow.ar_arrow_v2 import route_guidance_mode
from video_naming import next_video_path


PANEL = (640, 360)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--screen-updates", type=Path, required=True)
    parser.add_argument("--world-updates", type=Path, required=True)
    parser.add_argument("--graph-json", type=Path, required=True)
    parser.add_argument("--map-image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=float, default=24.0)
    parser.add_argument("--end", type=float, default=50.0)
    parser.add_argument("--tag", default="world_approach_graph_24_50")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(rows, key=lambda item: float(item.get("timestamp", 0.0)))


def latest_index(rows: list[dict[str, Any]], timestamp: float) -> int:
    index = -1
    for candidate, row in enumerate(rows):
        if float(row.get("timestamp", 0.0)) <= timestamp + 1e-6:
            index = candidate
        else:
            break
    return index


def polygon_bounds(polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]]) -> dict[str, float] | None:
    filled = [poly for poly, _, _, kind in polygons if kind != "edge" and len(poly) >= 3]
    if not filled:
        return None
    points = np.concatenate(filled, axis=0)
    x0, y0 = np.min(points, axis=0)
    x1, y1 = np.max(points, axis=0)
    return {
        "x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1),
        "area": float(max(0.0, x1 - x0) * max(0.0, y1 - y0)),
    }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    screen_anchors = enrich_anchors(load_updates(args.screen_updates))
    world_rows = load_jsonl(args.world_updates)
    if not screen_anchors or not world_rows:
        raise RuntimeError("missing screen or world AR updates")

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
    screen_polygons = []
    previous_screen_index = -1
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

            screen_index = anchor_index_at(screen_anchors, timestamp)
            screen_anchor = screen_anchors[screen_index] if screen_index >= 0 else None
            if screen_anchor is not None and screen_index != previous_screen_index:
                screen_polygons = payload_screen_polygons(screen_anchor["payload"], frame.shape)
                previous_screen_index = screen_index
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            H, inliers, residual = (None, 0, None)
            if previous_gray is not None:
                H, inliers, residual = track_homography(previous_gray, gray)
                if not (H is not None and inliers >= 20 and residual is not None and residual <= 3.5):
                    H = None
            screen_polygons = bounded_visual_warp(screen_polygons, H, frame.shape)
            previous_gray = gray

            world_index = latest_index(world_rows, timestamp)
            left = world_rows[world_index] if world_index >= 0 else None
            right = world_rows[world_index + 1] if 0 <= world_index + 1 < len(world_rows) else None
            world_payload = interpolate_camera(left, right, timestamp)
            world_polygons = payload_screen_polygons(world_payload, frame.shape)
            position = point((left or {}).get("position"))
            mode = "unknown"
            bend = 0.0
            if position is not None:
                mode, bend = route_guidance_mode(position[0], position[1], (left or {}).get("path") or [])
                if mode == "gentle_corridor":
                    world_polygons = strip_carets(world_polygons)

            age = None if left is None else max(0.0, timestamp - float(left["timestamp"]))
            screen_frame = draw_label(
                draw_overlay(frame, screen_polygons),
                "REJECTED: SCREEN KLT/HOMOGRAPHY",
                timestamp,
                f"flow={inliers}",
            )
            world_frame = draw_label(
                draw_overlay(frame, world_polygons),
                "WORLD ROUTE + CAMERA POSE",
                timestamp,
                f"mode={mode} bend={bend:.1f}deg",
            )
            top_frame = map_panel(map_image, positions, edges, labels, left, age, frame_index, timestamp)
            writer.write(np.hstack([screen_frame, world_frame, top_frame]))
            candidate_writer.write(world_frame)
            records.append({
                "frame": frame_index,
                "timestamp": timestamp,
                "screen_anchor": screen_index,
                "world_anchor": world_index,
                "world_pose_available": world_payload is not None,
                "guidance_mode": mode,
                "screen_bounds": polygon_bounds(screen_polygons),
                "world_bounds": polygon_bounds(world_polygons),
                "position": None if left is None else left.get("position"),
            })
    finally:
        cap.release()
        writer.release()
        candidate_writer.release()

    visible_world = sum(record["world_bounds"] is not None for record in records)
    summary = {
        "experiment": "screen-space KLT rejection vs world route reprojection",
        "video": str(args.video),
        "start_seconds": start,
        "end_seconds": end,
        "fps": fps,
        "frames_reviewed": len(records),
        "world_pose_frames": sum(record["world_pose_available"] for record in records),
        "world_visible_frames": visible_world,
        "comparison_output": str(comparison_path),
        "candidate_output": str(candidate_path),
        "records_output": str(args.output_dir / f"{safe_tag}_per_frame.json"),
        "decision": "Reject screen-warped world AR. Reproject fixed world geometry from a current camera pose; hide it when no pose is available.",
        "replay_limit": "Buffered camera interpolation uses a future pose and is not a live tracking implementation.",
    }
    (args.output_dir / f"{safe_tag}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / f"{safe_tag}_per_frame.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
