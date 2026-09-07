"""Create sparse-frame AR videos comparing non-IMU smoothing strategies.

The experiment intentionally consumes one frame every 1.5 seconds, matching
the current replay pipeline. It first runs the real navigation backend to
obtain the PnP/AR payloads, then renders four alternatives:

  raw_pnp       : backend payload as received
  ema_pose      : low-pass camera-pose correction
  jump_hold     : reject large map-position jumps and hold the last pose
  klt_flow      : warp the previous AR overlay with visual KLT/homography

The KLT variant is deliberately visual-only. It is not claimed to solve
metric monocular odometry; this is a visual continuity experiment.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VIDEO = Path(r"D:\video\video_from_iphone_oak_wide\IMG_6955.MOV")
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "out"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--api", default="http://localhost:5000")
    parser.add_argument("--filename", default="IMG_6955.MOV")
    parser.add_argument("--destination", default="M21_A")
    parser.add_argument("--interval", type=float, default=1.5)
    parser.add_argument("--preview-seconds", type=float, default=0.25)
    parser.add_argument("--force-run", action="store_true")
    return parser.parse_args()


def read_sse_updates(api_base: str, session_id: int) -> list[dict[str, Any]]:
    url = f"{api_base.rstrip('/')}/api/navigation-stream"
    print(f"[experiment] reading SSE session {session_id}")
    updates: list[dict[str, Any]] = []
    with requests.get(
        url,
        params={"session_id": str(session_id), "replay": 1},
        stream=True,
        timeout=(15, 900),
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            payload = json.loads(raw_line[5:].strip())
            if payload.get("type") == "update":
                updates.append(payload)
            if payload.get("type") == "complete":
                break
            if payload.get("type") == "error" and "frame" not in payload:
                raise RuntimeError(payload.get("message", "navigation failed"))
    print(f"[experiment] received {len(updates)} localization updates")
    return updates


def get_backend_updates(args: argparse.Namespace, out_dir: Path) -> list[dict[str, Any]]:
    cached = out_dir / "non_imu_1p5s_localization_updates.json"
    if cached.exists() and not args.force_run:
        print(f"[experiment] using cached updates: {cached}")
        return json.loads(cached.read_text(encoding="utf-8"))

    payload = {
        "video_filename": args.filename,
        "origin": "floor1",
        "destination": args.destination,
        "interval": args.interval,
        "debug_mode": False,
        "floor_id": "floor1",
        "auto_floor": True,
        "destination_floor": "floor1",
    }
    start_url = f"{args.api.rstrip('/')}/api/start-navigation"
    print(f"[experiment] starting backend replay: {start_url}")
    response = requests.post(start_url, json=payload, timeout=30)
    response.raise_for_status()
    started = response.json()
    if not started.get("success") or not started.get("session_id"):
        raise RuntimeError(started)
    updates = read_sse_updates(args.api, int(started["session_id"]))
    cached.write_text(json.dumps(updates, ensure_ascii=False), encoding="utf-8")
    return updates


def sample_video(video_path: Path, interval: float) -> list[tuple[float, np.ndarray]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    samples: list[tuple[float, np.ndarray]] = []
    next_sample = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = float(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            if timestamp + 1e-6 >= next_sample:
                samples.append((timestamp, frame.copy()))
                next_sample += interval
    finally:
        cap.release()
    print(f"[experiment] extracted {len(samples)} frames at {interval:.2f}s")
    return samples


def update_for_sample(updates: list[dict[str, Any]], timestamp: float) -> dict[str, Any] | None:
    best = None
    best_delta = float("inf")
    for update in updates:
        ts = update.get("timestamp")
        if not isinstance(ts, (int, float)):
            continue
        delta = abs(float(ts) - timestamp)
        if delta < best_delta:
            best_delta = delta
            best = update
    return best if best is not None and best_delta <= 0.45 else None


def payload_pose(payload: dict[str, Any] | None) -> tuple[np.ndarray, np.ndarray] | None:
    if not isinstance(payload, dict) or payload.get("R") is None or payload.get("t") is None:
        return None
    try:
        R = np.asarray(payload["R"], dtype=np.float64).reshape(3, 3)
        t = np.asarray(payload["t"], dtype=np.float64).reshape(3)
    except (TypeError, ValueError):
        return None
    if not np.all(np.isfinite(R)) or not np.all(np.isfinite(t)):
        return None
    return R, t


def smooth_rotation(previous: np.ndarray, current: np.ndarray, alpha: float) -> np.ndarray:
    blended = (1.0 - alpha) * previous + alpha * current
    U, _, Vt = np.linalg.svd(blended)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1.0
        R = U @ Vt
    return R


def ema_payload(previous: dict[str, Any] | None, current: dict[str, Any] | None,
                alpha: float = 0.42) -> dict[str, Any] | None:
    if current is None:
        return copy.deepcopy(previous) if previous is not None else None
    if previous is None or payload_pose(previous) is None or payload_pose(current) is None:
        return copy.deepcopy(current)
    previous_pose = payload_pose(previous)
    current_pose = payload_pose(current)
    assert previous_pose is not None and current_pose is not None
    previous_R, previous_t = previous_pose
    current_R, current_t = current_pose
    result = copy.deepcopy(current)
    result["R"] = smooth_rotation(previous_R, current_R, alpha).tolist()
    result["t"] = ((1.0 - alpha) * previous_t + alpha * current_t).tolist()
    return result


def project_world_points(points: Any, payload: dict[str, Any], frame_shape: tuple[int, ...]) -> np.ndarray | None:
    try:
        xyz = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        K = np.asarray(payload["K"], dtype=np.float64).reshape(4)
        R = np.asarray(payload["R"], dtype=np.float64).reshape(3, 3)
        t = np.asarray(payload["t"], dtype=np.float64).reshape(3)
        img_wh = np.asarray(payload.get("imgWH", [frame_shape[1], frame_shape[0]]), dtype=np.float64)
        img_w = float(img_wh[0])
        img_h = float(img_wh[1])
        fx, fy, cx, cy = K
        camera = (R @ xyz.T + t.reshape(3, 1)).T
        z = camera[:, 2]
        if np.any(z <= 1e-6):
            return None
        uv = np.column_stack((fx * camera[:, 0] / z + cx, fy * camera[:, 1] / z + cy))
        sx = frame_shape[1] / max(img_w, 1.0)
        sy = frame_shape[0] / max(img_h, 1.0)
        uv[:, 0] *= sx
        uv[:, 1] *= sy
        if not np.all(np.isfinite(uv)):
            return None
        return uv.astype(np.float32)
    except (TypeError, ValueError, KeyError):
        return None


def payload_screen_polygons(payload: dict[str, Any] | None, frame_shape: tuple[int, ...]) -> list[tuple[np.ndarray, tuple[int, int, int], float, str]]:
    if payload is None or payload_pose(payload) is None:
        return []
    polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]] = []

    for item in payload.get("ribbon_quads", []) or []:
        if not isinstance(item, (list, tuple)) or len(item) < 1:
            continue
        poly = project_world_points(item[0], payload, frame_shape)
        if poly is not None and len(poly) >= 3:
            polygons.append((poly, (255, 180, 20), 0.18, "ribbon"))

    for item in payload.get("ribbon_edges", []) or []:
        poly = project_world_points(item, payload, frame_shape)
        if poly is not None and len(poly) >= 2:
            polygons.append((poly, (255, 235, 100), 0.55, "edge"))

    alphas = payload.get("alphas", []) or []
    for index, item in enumerate(payload.get("carets", []) or []):
        poly = project_world_points(item, payload, frame_shape)
        if poly is not None and len(poly) >= 3:
            alpha = float(alphas[index]) if index < len(alphas) else 0.85
            polygons.append((poly, (40, 230, 255), max(0.20, min(0.92, alpha)), "caret"))

    return polygons


def draw_polygons(frame: np.ndarray, polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]]) -> np.ndarray:
    out = frame.copy()
    for poly, color, alpha, kind in polygons:
        pts = np.round(poly).astype(np.int32).reshape(-1, 1, 2)
        if kind == "edge":
            cv2.polylines(out, [pts], False, color, 3, cv2.LINE_AA)
            continue
        layer = out.copy()
        cv2.fillPoly(layer, [pts], color)
        out = cv2.addWeighted(layer, alpha, out, 1.0 - alpha, 0.0)
        cv2.polylines(out, [pts], True, (0, 255, 255), 2, cv2.LINE_AA)
    return out


def track_homography(previous_gray: np.ndarray, current_gray: np.ndarray) -> tuple[np.ndarray | None, int, float | None]:
    points0 = cv2.goodFeaturesToTrack(
        previous_gray,
        maxCorners=500,
        qualityLevel=0.008,
        minDistance=8,
        blockSize=7,
    )
    if points0 is None or len(points0) < 8:
        return None, 0, None
    points1, status, _ = cv2.calcOpticalFlowPyrLK(
        previous_gray,
        current_gray,
        points0,
        None,
        winSize=(31, 31),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if points1 is None or status is None:
        return None, 0, None
    points0_back, status_back, _ = cv2.calcOpticalFlowPyrLK(
        current_gray,
        previous_gray,
        points1,
        None,
        winSize=(31, 31),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    valid = status.reshape(-1).astype(bool) & status_back.reshape(-1).astype(bool)
    p0 = points0.reshape(-1, 2)[valid]
    p1 = points1.reshape(-1, 2)[valid]
    p0b = points0_back.reshape(-1, 2)[valid]
    if len(p0) < 8:
        return None, int(len(p0)), None
    fb_error = np.linalg.norm(p0 - p0b, axis=1)
    keep = fb_error < 1.5
    p0 = p0[keep]
    p1 = p1[keep]
    if len(p0) < 8:
        return None, int(len(p0)), None
    H, mask = cv2.findHomography(p0, p1, cv2.RANSAC, 4.0)
    if H is None or mask is None:
        return None, 0, None
    inlier = mask.reshape(-1).astype(bool)
    if int(inlier.sum()) < 8:
        return None, int(inlier.sum()), None
    projected = cv2.perspectiveTransform(p0.reshape(-1, 1, 2), H).reshape(-1, 2)
    residual = np.linalg.norm(projected - p1, axis=1)
    median_residual = float(np.median(residual[inlier]))
    return H.astype(np.float32), int(inlier.sum()), median_residual


def warp_polygons(polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]], H: np.ndarray) -> list[tuple[np.ndarray, tuple[int, int, int], float, str]]:
    warped: list[tuple[np.ndarray, tuple[int, int, int], float, str]] = []
    for poly, color, alpha, kind in polygons:
        result = cv2.perspectiveTransform(poly.reshape(-1, 1, 2).astype(np.float32), H).reshape(-1, 2)
        if np.all(np.isfinite(result)):
            warped.append((result, color, alpha, kind))
    return warped


def draw_label(frame: np.ndarray, label: str, timestamp: float, extra: str = "") -> np.ndarray:
    out = frame.copy()
    text = f"{label} | source t={timestamp:6.1f}s"
    if extra:
        text += f" | {extra}"
    cv2.rectangle(out, (0, 0), (out.shape[1], 40), (8, 18, 32), -1)
    cv2.putText(out, text, (12, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (240, 250, 255), 2, cv2.LINE_AA)
    return out


def overlay_centroid(polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]]) -> tuple[float, float] | None:
    points = [poly for poly, _, _, kind in polygons if kind == "caret"]
    if not points:
        points = [poly for poly, _, _, _ in polygons]
    if not points:
        return None
    all_points = np.concatenate(points, axis=0)
    return float(np.mean(all_points[:, 0])), float(np.mean(all_points[:, 1]))


def resize_panel(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)


def writer_for(path: Path, size: tuple[int, int], fps: float) -> cv2.VideoWriter:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise RuntimeError(f"cannot create video writer: {path}")
    return writer


def main() -> int:
    args = parse_args()
    if not args.video.exists():
        raise FileNotFoundError(args.video)
    out_dir = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    updates = get_backend_updates(args, out_dir)
    samples = sample_video(args.video, args.interval)
    if not samples:
        raise RuntimeError("no video samples")

    sample_updates = [update_for_sample(updates, timestamp) for timestamp, _ in samples]
    video_h, video_w = samples[0][1].shape[:2]
    preview_fps = 1.0 / max(0.05, args.preview_seconds)
    panel_size = (640, 360)
    full_size = (panel_size[0] * 3, panel_size[1] * 2)

    names = {
        "raw_pnp": "RAW PnP",
        "ema_pose": "EMA POSE",
        "jump_hold": "JUMP-GATED HOLD",
        "klt_flow": "VISUAL KLT FLOW",
        "klt_corrected": "KLT + SOFT PnP CORRECTION",
    }
    writers = {
        key: writer_for(out_dir / f"non_imu_1p5s_{key}.mp4", panel_size, preview_fps)
        for key in names
    }
    comparison_writer = writer_for(out_dir / "non_imu_1p5s_comparison.mp4", full_size, preview_fps)

    previous_ema: dict[str, Any] | None = None
    previous_jump: dict[str, Any] | None = None
    previous_flow_polygons: list[tuple[np.ndarray, tuple[int, int, int], float, str]] = []
    previous_gray: np.ndarray | None = None
    previous_raw_payload: dict[str, Any] | None = None
    preview_snapshots: list[np.ndarray] = []
    metrics: dict[str, dict[str, Any]] = {
        key: {"frames": 0, "with_overlay": 0, "max_sample_jump_px": 0.0, "total_sample_motion_px": 0.0, "centroids": []}
        for key in names
    }
    flow_metrics: list[dict[str, Any]] = []

    try:
        for index, ((timestamp, frame), update) in enumerate(zip(samples, sample_updates)):
            raw_payload = update.get("ar_world") if isinstance(update, dict) else None
            raw_position = update.get("position") if isinstance(update, dict) else None
            if raw_payload is not None:
                previous_raw_payload = raw_payload

            raw_polygons = payload_screen_polygons(raw_payload, frame.shape)
            raw_frame = draw_polygons(frame, raw_polygons)
            raw_frame = draw_label(raw_frame, names["raw_pnp"], timestamp, f"polys={len(raw_polygons)}")

            ema = ema_payload(previous_ema, raw_payload, alpha=0.42)
            if ema is not None:
                previous_ema = ema
            ema_polygons = payload_screen_polygons(ema, frame.shape)
            ema_frame = draw_polygons(frame, ema_polygons)
            ema_frame = draw_label(ema_frame, names["ema_pose"], timestamp, f"polys={len(ema_polygons)}")

            accept_jump = True
            if previous_jump is not None and isinstance(raw_position, dict):
                previous_position = previous_jump.get("__position")
                if isinstance(previous_position, dict):
                    try:
                        distance = math.hypot(
                            float(raw_position["x"]) - float(previous_position["x"]),
                            float(raw_position["y"]) - float(previous_position["y"]),
                        )
                        accept_jump = distance <= max(42.0, 18.0 * args.interval * 2.0)
                    except (KeyError, TypeError, ValueError):
                        accept_jump = True
            if accept_jump and raw_payload is not None:
                jump_payload = copy.deepcopy(raw_payload)
                jump_payload["__position"] = raw_position
                previous_jump = jump_payload
            jump_payload = previous_jump if previous_jump is not None else raw_payload
            jump_polygons = payload_screen_polygons(jump_payload, frame.shape)
            jump_frame = draw_polygons(frame, jump_polygons)
            jump_extra = f"accepted={'yes' if accept_jump else 'no'} polys={len(jump_polygons)}"
            jump_frame = draw_label(jump_frame, names["jump_hold"], timestamp, jump_extra)

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            flow_inliers = 0
            flow_residual: float | None = None
            if previous_gray is None:
                flow_polygons = raw_polygons
            else:
                H, flow_inliers, flow_residual = track_homography(previous_gray, gray)
                if H is not None and previous_flow_polygons:
                    flow_polygons = warp_polygons(previous_flow_polygons, H)
                elif raw_polygons:
                    flow_polygons = raw_polygons
                else:
                    flow_polygons = previous_flow_polygons
            flow_frame = draw_polygons(frame, flow_polygons)
            flow_extra = f"inliers={flow_inliers} residual={flow_residual:.1f}px" if flow_residual is not None else f"inliers={flow_inliers}"
            flow_frame = draw_label(flow_frame, names["klt_flow"], timestamp, flow_extra)

            # Keep the visual warp, but use the current PnP overlay only as a
            # low-gain absolute correction. This is the practical hybrid we
            # want to test: visual motion between fixes, PnP to pull drift back.
            corrected_polygons = flow_polygons
            flow_centroid = overlay_centroid(flow_polygons)
            raw_centroid = overlay_centroid(raw_polygons)
            if flow_centroid is not None and raw_centroid is not None and flow_polygons:
                correction = 0.35 * np.asarray(
                    [raw_centroid[0] - flow_centroid[0], raw_centroid[1] - flow_centroid[1]],
                    dtype=np.float32,
                )
                corrected_polygons = [
                    (poly + correction.reshape(1, 2), color, alpha, kind)
                    for poly, color, alpha, kind in flow_polygons
                ]
            corrected_frame = draw_polygons(frame, corrected_polygons)
            corrected_frame = draw_label(
                corrected_frame,
                names["klt_corrected"],
                timestamp,
                f"inliers={flow_inliers} correction=35%",
            )
            previous_flow_polygons = flow_polygons
            previous_gray = gray

            panels = {
                "raw_pnp": resize_panel(raw_frame, panel_size),
                "ema_pose": resize_panel(ema_frame, panel_size),
                "jump_hold": resize_panel(jump_frame, panel_size),
                "klt_flow": resize_panel(flow_frame, panel_size),
                "klt_corrected": resize_panel(corrected_frame, panel_size),
            }
            for key, panel in panels.items():
                writers[key].write(panel)
                item = metrics[key]
                item["frames"] += 1
                polygons = {
                    "raw_pnp": raw_polygons,
                    "ema_pose": ema_polygons,
                    "jump_hold": jump_polygons,
                    "klt_flow": flow_polygons,
                    "klt_corrected": corrected_polygons,
                }[key]
                centroid = overlay_centroid(polygons)
                if centroid is not None:
                    item["with_overlay"] += 1
                    item["centroids"].append([centroid[0], centroid[1]])
                    if len(item["centroids"]) >= 2:
                        p0 = np.asarray(item["centroids"][-2], dtype=float)
                        p1 = np.asarray(item["centroids"][-1], dtype=float)
                        jump = float(np.linalg.norm(p1 - p0))
                        item["max_sample_jump_px"] = max(float(item["max_sample_jump_px"]), jump)
                        item["total_sample_motion_px"] += jump
            flow_metrics.append({"timestamp": timestamp, "inliers": flow_inliers, "median_residual_px": flow_residual})

            comparison = np.zeros((full_size[1], panel_size[0] * 3, 3), dtype=np.uint8)
            comparison[0:panel_size[1], 0:panel_size[0]] = panels["raw_pnp"]
            comparison[0:panel_size[1], panel_size[0]:panel_size[0] * 2] = panels["ema_pose"]
            comparison[0:panel_size[1], panel_size[0] * 2:panel_size[0] * 3] = panels["jump_hold"]
            comparison[panel_size[1]:panel_size[1] * 2, 0:panel_size[0]] = panels["klt_flow"]
            comparison[panel_size[1]:panel_size[1] * 2, panel_size[0]:panel_size[0] * 2] = panels["klt_corrected"]
            comparison[panel_size[1]:panel_size[1] * 2, panel_size[0] * 2:panel_size[0] * 3] = np.zeros_like(panels["raw_pnp"])
            comparison_writer.write(comparison)
            if index in {0, 30, 60, 100, 150, 200}:
                preview_snapshots.append(comparison.copy())

            if index % 20 == 0:
                print(f"[experiment] rendered sample {index + 1}/{len(samples)} t={timestamp:.1f}s")
    finally:
        for writer in writers.values():
            writer.release()
        comparison_writer.release()

    for item in metrics.values():
        item.pop("centroids", None)
    if preview_snapshots:
        snapshot_w = 960
        snapshot_h = int(preview_snapshots[0].shape[0] * snapshot_w / preview_snapshots[0].shape[1])
        snapshots = [cv2.resize(image, (snapshot_w, snapshot_h), interpolation=cv2.INTER_AREA) for image in preview_snapshots]
        contact = np.zeros((snapshot_h * 3, snapshot_w * 2, 3), dtype=np.uint8)
        for index, image in enumerate(snapshots[:6]):
            row, column = divmod(index, 2)
            contact[row * snapshot_h:(row + 1) * snapshot_h, column * snapshot_w:(column + 1) * snapshot_w] = image
        cv2.imwrite(str(out_dir / "non_imu_1p5s_contact_sheet.png"), contact)
    summary = {
        "video": str(args.video),
        "destination": args.destination,
        "sample_interval_seconds": args.interval,
        "preview_seconds_per_sample": args.preview_seconds,
        "preview_speedup": args.interval / max(args.preview_seconds, 1e-6),
        "sample_count": len(samples),
        "backend_update_count": len(updates),
        "methods": metrics,
        "flow_quality": flow_metrics,
        "outputs": [str(out_dir / f"non_imu_1p5s_{key}.mp4") for key in names]
        + [str(out_dir / "non_imu_1p5s_comparison.mp4")],
    }
    (out_dir / "non_imu_1p5s_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
