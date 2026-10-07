"""Fill one replay localization gap with target-frame tracked-landmark PnP.

This is a bounded experiment for the 37.52s HOLD_LAST_FIX gap. Map landmarks
matched at the last accepted source frame are tracked into every target frame;
only their target-frame 2D observations are passed to PnP. No screen-space AR
polygon is warped or held.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for import_path in (BACKEND_DIR, BACKEND_DIR / "app", BACKEND_DIR / "core"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from app.core import localization as loc
from app.core.localizer import Localizer
from app.services.accel import accelerate_localizer
import app.localization_config as localization_config
from render_fullrate_non_imu_ar import draw_label, open_writer, payload_screen_polygons
from render_registration_replay import interpolate_camera
from render_stale_free_ar import draw_overlay, strip_carets
from render_world_approach_graph_poc import latest_index, load_jsonl
from run_temporal_landmark_propagation import (
    DEFAULT_DATA,
    DEFAULT_GRAPH,
    DEFAULT_MAP,
    DEFAULT_VIDEO,
    build_source_items,
    dedupe_correspondences,
    evaluate_target,
    find_reference_size,
    track_source_to_target,
)
from poc_ar_arrow.ar_arrow_v2 import route_guidance_mode
from video_naming import next_video_path


PANEL = (640, 360)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--world-updates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", type=float, default=36.02)
    parser.add_argument("--end", type=float, default=39.10)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--fb-error", type=float, default=1.5)
    parser.add_argument("--past-offsets", default="-0.25,-0.125")
    parser.add_argument("--tag", default="tracked_pnp_gap_36_39")
    return parser.parse_args()


def backend_path(path: Path) -> Path:
    return path if path.is_absolute() else BACKEND_DIR / path


def track_step(previous_gray, current_gray, points_2d, points_3d, mp_ids, max_error):
    if len(points_2d) < 4:
        return points_2d[:0], points_3d[:0], mp_ids[:0]
    source = np.asarray(points_2d, np.float32).reshape(-1, 1, 2)
    target, status_forward, _ = cv2.calcOpticalFlowPyrLK(
        previous_gray, current_gray, source, None, winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    if target is None or status_forward is None:
        return points_2d[:0], points_3d[:0], mp_ids[:0]
    backward, status_backward, _ = cv2.calcOpticalFlowPyrLK(
        current_gray, previous_gray, target, None, winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    if backward is None or status_backward is None:
        return points_2d[:0], points_3d[:0], mp_ids[:0]
    target = target.reshape(-1, 2)
    backward = backward.reshape(-1, 2)
    h, w = current_gray.shape[:2]
    error = np.linalg.norm(backward - source.reshape(-1, 2), axis=1)
    keep = (
        (status_forward.reshape(-1) > 0) & (status_backward.reshape(-1) > 0) &
        np.isfinite(target).all(axis=1) & (error <= max_error) &
        (target[:, 0] >= 0) & (target[:, 0] < w) &
        (target[:, 1] >= 0) & (target[:, 1] < h)
    )
    return target[keep], np.asarray(points_3d)[keep], np.asarray(mp_ids)[keep]


def solve_pose(localizer, points_2d, points_3d):
    if len(points_2d) < 4:
        return None
    ok, rotation, translation, inliers = loc.solve_pnp_ransac(
        points_2d, points_3d, localizer.K, reproj_threshold=8.0, min_inliers=4)
    if not ok or inliers is None:
        return None
    indices = np.asarray(inliers).reshape(-1)
    ratio, error = loc.compute_pnp_quality(
        points_2d, points_3d, inliers, rotation, translation, localizer.K)
    accepted = (
        len(indices) >= int(localization_config.LOCALIZATION_PARAMS["min_inliers"]) and
        ratio >= float(localization_config.LOCALIZATION_PARAMS["min_inlier_ratio"]) and
        math.isfinite(error) and
        error <= float(localization_config.LOCALIZATION_PARAMS["max_median_reproj_error"])
    )
    return {
        "accepted": accepted,
        "R": rotation,
        "t": np.asarray(translation).reshape(3),
        "inliers": indices,
        "inlier_ratio": float(ratio),
        "reproj_error": float(error),
    }


def main() -> int:
    args = parse_args()
    args.data_dir = backend_path(args.data_dir)
    args.map_image = backend_path(args.map_image)
    args.graph_json = backend_path(args.graph_json)
    args.world_updates = backend_path(args.world_updates)
    args.output_dir = backend_path(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_jsonl(args.world_updates)
    source_row_index = latest_index(rows, args.source + 0.02)
    source_row = rows[source_row_index]
    source_payload = source_row.get("ar_world")
    if not isinstance(source_payload, dict):
        raise RuntimeError("source row has no world payload")

    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc")
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    reference_size = find_reference_size(args.data_dir)

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {args.video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    # The tracking source may be a full-rate frame between sparse backend
    # updates. Geometry/navigation state comes from the latest accepted row,
    # while 2D-3D correspondences are solved on the actual requested frame.
    source_frame_index = int(round(float(args.source) * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame_index)
    ok, source_frame = cap.read()
    if not ok:
        raise RuntimeError("cannot read source frame")
    source_query, direct, _ = evaluate_target(localizer, source_frame, reference_size, args.top_k)
    seed_items = [
        {"point_2d": p2, "point_3d": p3, "mp_id": int(mp), "track_error": 0.0}
        for p2, p3, mp in zip(direct["points_2d"], direct["points_3d"], direct["mp_ids"])
    ]
    for offset in [float(value) for value in args.past_offsets.split(",") if value.strip()]:
        past_index = source_frame_index + int(round(offset * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, past_index)
        ok, past_frame = cap.read()
        if not ok:
            continue
        past_query, past_direct, _ = evaluate_target(localizer, past_frame, reference_size, args.top_k)
        propagated = track_source_to_target(
            past_query["gray"], source_query["gray"],
            build_source_items(past_direct, past_index), args.fb_error)
        seed_items.extend(propagated)
    combined = dedupe_correspondences(seed_items)
    initial_pose = solve_pose(localizer, combined["points_2d"], combined["points_3d"])
    if initial_pose is None or not initial_pose["accepted"]:
        raise RuntimeError("source frame did not pass PnP quality gate")
    # Keep every matched landmark that survives the optical-flow FB gate.
    # Repeatedly shrinking the track set to the current PnP inliers causes an
    # irreversible 11 -> 8 -> 7 collapse even when reprojection remains good;
    # RANSAC is specifically responsible for rejecting those outliers per frame.
    points_2d = combined["points_2d"]
    points_3d = combined["points_3d"]
    mp_ids = combined["mp_ids"]
    previous_gray = source_query["gray"]

    safe_tag = "".join(char if char.isalnum() or char in "-_" else "_" for char in args.tag)
    comparison_path = next_video_path(args.output_dir, f"{safe_tag}_comparison")
    candidate_path = next_video_path(args.output_dir, safe_tag)
    writer = open_writer(comparison_path, (PANEL[0] * 2, PANEL[1]), fps)
    candidate_writer = open_writer(candidate_path, PANEL, fps)
    records = []
    last_accepted_centre = None
    cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame_index)
    try:
        while True:
            ok, frame_full = cap.read()
            if not ok:
                break
            frame_index = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            timestamp = frame_index / fps
            if timestamp > args.end:
                break
            gray = loc.resize_query_image(cv2.cvtColor(frame_full, cv2.COLOR_BGR2GRAY), reference_size)
            if frame_index != source_frame_index:
                points_2d, points_3d, mp_ids = track_step(
                    previous_gray, gray, points_2d, points_3d, mp_ids, args.fb_error)
            pose = initial_pose if frame_index == source_frame_index else solve_pose(
                localizer, points_2d, points_3d)
            accepted = bool(pose and pose["accepted"])
            if accepted:
                centre = -pose["R"].T @ pose["t"]
                if last_accepted_centre is not None and np.linalg.norm(centre - last_accepted_centre) > 0.10:
                    accepted = False
                else:
                    last_accepted_centre = centre
            row_index = latest_index(rows, timestamp)
            left = rows[row_index] if row_index >= 0 else None
            right = rows[row_index + 1] if 0 <= row_index + 1 < len(rows) else None
            buffered = interpolate_camera(left, right, timestamp)
            buffered_polygons = payload_screen_polygons(buffered, frame_full.shape)
            tracked_payload = None
            if accepted:
                tracked_payload = copy.deepcopy(source_payload)
                tracked_payload["R"] = pose["R"].tolist()
                tracked_payload["t"] = pose["t"].tolist()
            tracked_polygons = payload_screen_polygons(tracked_payload, frame_full.shape)
            position = (left or {}).get("position") or source_row.get("position")
            if isinstance(position, dict):
                mode, _ = route_guidance_mode(position["x"], position["y"], (left or source_row).get("path") or [])
                if mode == "gentle_corridor":
                    buffered_polygons = strip_carets(buffered_polygons)
                    tracked_polygons = strip_carets(tracked_polygons)
            frame = cv2.resize(frame_full, PANEL, interpolation=cv2.INTER_AREA)
            # payload_screen_polygons was evaluated at full size; scale once to
            # the diagnostic pane without changing its perspective.
            sx, sy = PANEL[0] / frame_full.shape[1], PANEL[1] / frame_full.shape[0]
            def scale(items):
                return [(poly * np.asarray([sx, sy]), color, alpha, kind) for poly, color, alpha, kind in items]
            buffered_frame = draw_label(draw_overlay(frame, scale(buffered_polygons)), "BUFFERED POLICY", timestamp,
                                        "hidden" if buffered is None else "pose")
            tracked_frame = draw_label(draw_overlay(frame, scale(tracked_polygons)), "TARGET-FRAME TRACKED PnP", timestamp,
                                       f"inliers={0 if pose is None else len(pose['inliers'])} {'PASS' if accepted else 'HIDE'}")
            writer.write(np.hstack([buffered_frame, tracked_frame]))
            candidate_writer.write(tracked_frame)
            records.append({
                "frame": frame_index, "timestamp": timestamp,
                "tracked_points": int(len(points_2d)),
                "pnp_inliers": 0 if pose is None else int(len(pose["inliers"])),
                "accepted": accepted,
                "reproj_error": None if pose is None else pose["reproj_error"],
                "buffered_visible": buffered is not None,
            })
            previous_gray = gray
    finally:
        cap.release()
        writer.release()
        candidate_writer.release()

    summary = {
        "experiment": "target-frame tracked-landmark PnP over replay gap",
        "source_timestamp": source_frame_index / fps,
        "geometry_source_timestamp": float(source_row["timestamp"]),
        "end_seconds": float(args.end),
        "frames": len(records),
        "tracked_pnp_accepted_frames": sum(record["accepted"] for record in records),
        "buffered_pose_frames": sum(record["buffered_visible"] for record in records),
        "comparison_output": str(comparison_path),
        "candidate_output": str(candidate_path),
        "records_output": str(args.output_dir / f"{safe_tag}_per_frame.json"),
        "policy": "Project fixed world route from target-frame 2D-3D PnP; hide on gate failure; never warp or hold screen polygons.",
    }
    (args.output_dir / f"{safe_tag}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (args.output_dir / f"{safe_tag}_per_frame.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
