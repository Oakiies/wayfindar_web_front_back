"""Capture a repeatable causal navigation timeline and offline AR evidence.

This script talks to an already-running backend. It never changes the video
file and it does not use browser timing; ``presentation_*`` fields are an
explicit receive-clock simulation documented in the generated summary.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from statistics import median
from urllib.request import Request, urlopen

import cv2
import numpy as np


BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def request_json(base_url: str, method: str, path: str, payload: dict | None = None):
    body = None
    headers = {'Accept': 'application/json'}
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = Request(base_url.rstrip('/') + path, method=method, data=body, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def iter_sse(base_url: str, session_id: int):
    request = Request(
        base_url.rstrip('/') + f'/api/navigation-stream?session_id={session_id}',
        headers={'Accept': 'text/event-stream', 'Cache-Control': 'no-cache'},
    )
    with urlopen(request, timeout=300) as response:
        data_lines = []
        while True:
            line = response.readline()
            if not line:
                break
            text = line.decode('utf-8', errors='replace').rstrip('\r\n')
            if text.startswith('data: '):
                data_lines.append(text[6:])
            elif text == '' and data_lines:
                raw = '\n'.join(data_lines)
                data_lines = []
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue


def percentile(values: list[float], fraction: float):
    if not values:
        return None
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def video_metadata(video_path: Path) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        return {
            'source_path': str(video_path),
            'bytes': video_path.stat().st_size,
            'fps': fps,
            'frame_count': frames,
            'duration_s': frames / fps if fps > 0 else None,
            'width': width,
            'height': height,
            'transform': 'none; decoded with OpenCV, server downsamples 60 FPS to 30 FPS',
        }
    finally:
        cap.release()


def choose_update(updates: list[dict], presented_timestamp: float):
    selected = None
    for update in updates:
        timestamp = update.get('timestamp')
        if isinstance(timestamp, (int, float)) and timestamp <= presented_timestamp + 1e-6:
            selected = update
        elif isinstance(timestamp, (int, float)):
            break
    return selected


def geometry_status(update: dict) -> bool:
    return bool(update.get('ar_projected_geometry'))


def contiguous_intervals(updates: list[dict], predicate) -> list[dict]:
    intervals = []
    start = None
    last = None
    reason = None
    for update in updates:
        timestamp = update.get('timestamp')
        if not isinstance(timestamp, (int, float)):
            continue
        matched = bool(predicate(update))
        if matched and start is None:
            start = float(timestamp)
            reason = update.get('ar_world_status')
        if matched:
            last = float(timestamp)
        elif start is not None:
            intervals.append({'start_s': start, 'end_s': last, 'duration_s': max(0.0, last - start), 'reason': reason})
            start = last = reason = None
    if start is not None:
        intervals.append({'start_s': start, 'end_s': last, 'duration_s': max(0.0, last - start), 'reason': reason})
    return intervals


def draw_label(frame, label: str):
    out = frame.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 34), (10, 16, 28), -1)
    cv2.putText(out, label, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (220, 245, 255), 1, cv2.LINE_AA)
    return out


def render_payload(frame, payload):
    """Render a JSONL payload using the same offline renderer as production POC."""
    from poc_ar_arrow.ar_arrow_v2 import render_v2

    if not isinstance(payload, dict):
        return frame
    renderable = dict(payload)
    if 'K' in renderable:
        camera_k = np.asarray(renderable['K'], dtype=np.float64)
        if camera_k.size == 4:
            fx, fy, cx, cy = camera_k.reshape(-1)
            camera_k = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)
        renderable['K'] = camera_k
    for key in ('R', 't'):
        if key in renderable:
            renderable[key] = np.asarray(renderable[key], dtype=np.float64)
    return render_v2(frame, renderable)


def render_contact_sheet(video_path: Path, updates: list[dict], output_path: Path):
    valid = [item for item in updates if geometry_status(item)]
    hidden = [item for item in updates if not geometry_status(item)]
    chosen = []
    for item in ([valid[0]] if valid else []) + ([valid[len(valid) // 2]] if valid else []) + ([valid[-1]] if valid else []):
        if item not in chosen:
            chosen.append(item)
    for item in hidden[:2]:
        if item not in chosen:
            chosen.append(item)
    chosen = chosen[:6]
    if not chosen:
        return None

    cap = cv2.VideoCapture(str(video_path))
    tiles = []
    try:
        for item in chosen:
            timestamp = float(item.get('timestamp', 0.0))
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            payload = item.get('ar_world')
            if isinstance(payload, dict):
                try:
                    render_frame = render_payload(frame, payload)
                except Exception:
                    render_frame = frame
            else:
                render_frame = frame
            reason = item.get('ar_world_status', 'unknown')
            label = f"t={timestamp:.2f}s f={item.get('frame')} {reason}"
            render_frame = draw_label(render_frame, label)
            scale = 480.0 / render_frame.shape[1]
            tiles.append(cv2.resize(render_frame, (480, int(render_frame.shape[0] * scale))))
    finally:
        cap.release()
    if not tiles:
        return None
    tile_h = max(tile.shape[0] for tile in tiles)
    blank = np.zeros_like(tiles[0])
    rows = []
    for start in range(0, len(tiles), 2):
        pair = tiles[start:start + 2]
        while len(pair) < 2:
            pair.append(blank.copy())
        rows.append(np.hstack(pair))
    sheet = np.vstack(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), sheet)
    return output_path


def render_dropout_preview(video_path: Path, updates: list[dict], output_path: Path):
    hidden = [item for item in updates if not geometry_status(item)]
    if not hidden:
        return None
    start_s = max(0.0, float(hidden[0].get('timestamp', 0.0)) - 2.0)
    end_s = start_s + 10.0
    source = cv2.VideoCapture(str(video_path))
    fps = float(source.get(cv2.CAP_PROP_FPS) or 30.0)
    sample_fps = min(15.0, fps)
    stride = max(1, int(round(fps / sample_fps)))
    width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*'mp4v'), fps / stride, (width, height))
    frames = []
    try:
        source.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)
        index = 0
        while True:
            ok, frame = source.read()
            if not ok:
                break
            timestamp = float(source.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
            if timestamp > end_s:
                break
            if index % stride == 0:
                update = choose_update(updates, timestamp)
                payload = update.get('ar_world') if update else None
                if update and geometry_status(update) and isinstance(payload, dict):
                    try:
                        frame = render_payload(frame, payload)
                    except Exception:
                        pass
                frame = draw_label(frame, f"t={timestamp:.2f}s {update.get('ar_world_status') if update else 'no_event'}")
                writer.write(frame)
                frames.append(timestamp)
            index += 1
    finally:
        source.release()
        writer.release()
    return output_path if frames else None


def summarize(events: list[dict], first_receive: float, video_info: dict, args) -> dict:
    updates = sorted(
        [event for event in events if event.get('type') == 'update' and isinstance(event.get('timestamp'), (int, float))],
        key=lambda item: float(item['timestamp']),
    )
    delivery_lag = []
    end_to_end = []
    frontend_pose_age = []
    enriched_updates = []
    first_ts = float(updates[0]['timestamp']) if updates else 0.0
    first_update_receive = float(updates[0].get('_evidence', {}).get('received_wall_time_s', first_receive)) if updates else first_receive
    for update in updates:
        evidence = update.get('_evidence', {})
        present_ts = first_ts + (float(evidence.get('received_wall_time_s', first_update_receive)) - first_update_receive)
        selected = choose_update(updates[:updates.index(update) + 1], present_ts)
        if selected is not None:
            pose_age = max(0.0, present_ts - float(selected['timestamp']))
            frontend_pose_age.append(pose_age)
            evidence['simulated_presented_video_time_s'] = present_ts
            evidence['simulated_pose_frame'] = selected.get('frame')
            evidence['simulated_pose_age_s'] = pose_age
        video_elapsed = float(update['timestamp']) - first_ts
        receive_elapsed = float(evidence.get('received_wall_time_s', first_update_receive)) - first_update_receive
        lag = receive_elapsed - video_elapsed
        delivery_lag.append(lag)
        emit_wall = update.get('emit_wall_time_s')
        if isinstance(emit_wall, (int, float)):
            end_to_end.append(float(evidence.get('received_wall_time_s', 0.0)) - float(emit_wall))
        update['_evidence'] = evidence
        enriched_updates.append(update)

    statuses = {}
    for update in updates:
        key = str(update.get('tracking_status') or 'unknown')
        statuses[key] = statuses.get(key, 0) + 1
    ar_statuses = {}
    for update in updates:
        key = str(update.get('ar_world_status') or 'unknown')
        ar_statuses[key] = ar_statuses.get(key, 0) + 1
    visible_intervals = contiguous_intervals(updates, geometry_status)
    hidden_intervals = contiguous_intervals(updates, lambda item: not geometry_status(item))
    return {
        'schema': 'luna_live_camera_navigation_rework_v1',
        'backend_url': args.backend_url,
        'session_id': args.session_id,
        'video_filename': args.video_filename,
        'source_video': video_info,
        'destination': args.destination,
        'start_floor': args.start_floor,
        'destination_floor': args.destination_floor,
        'sample_target_video_s': args.duration,
        'captured_event_count': len(events),
        'captured_update_count': len(updates),
        'first_update_timestamp_s': first_ts if updates else None,
        'last_update_timestamp_s': float(updates[-1]['timestamp']) if updates else None,
        'tracking_status_counts': statuses,
        'ar_world_status_counts': ar_statuses,
        'payload_ready_update_count': sum(bool(item.get('ar_payload_ready')) for item in updates),
        'projected_geometry_update_count': sum(geometry_status(item) for item in updates),
        'first_projected_geometry_s': float(next((item['timestamp'] for item in updates if geometry_status(item)), 0.0)) if any(geometry_status(item) for item in updates) else None,
        'last_projected_geometry_s': float(next((item['timestamp'] for item in reversed(updates) if geometry_status(item)), 0.0)) if any(geometry_status(item) for item in updates) else None,
        'visible_intervals': visible_intervals,
        'hidden_intervals': hidden_intervals,
        'delivery_lag_s': {'p50': percentile(delivery_lag, 0.50), 'p95': percentile(delivery_lag, 0.95), 'max': max(delivery_lag) if delivery_lag else None},
        'server_to_client_wall_latency_s': {'p50': percentile(end_to_end, 0.50), 'p95': percentile(end_to_end, 0.95), 'max': max(end_to_end) if end_to_end else None},
        'simulated_frontend_pose_age_s': {'p50': percentile(frontend_pose_age, 0.50), 'p95': percentile(frontend_pose_age, 0.95), 'max': max(frontend_pose_age) if frontend_pose_age else None, 'gate_s': 0.15},
        'source_to_current_video_s': {'p50': percentile([item['source_to_current_video_s'] for item in updates if isinstance(item.get('source_to_current_video_s'), (int, float))], 0.50), 'p95': percentile([item['source_to_current_video_s'] for item in updates if isinstance(item.get('source_to_current_video_s'), (int, float))], 0.95), 'max': max([item['source_to_current_video_s'] for item in updates if isinstance(item.get('source_to_current_video_s'), (int, float))], default=None)},
        'tracking_diagnostics_last_event': next((item.get('tracking_diagnostics') for item in reversed(events) if item.get('type') in ('complete', 'diagnostics_snapshot')), None),
        'floor_transition_events': [item for item in events if item.get('type') == 'floor_transition'],
        'clock': 'receive_wall_time_s and emit_wall_time_s are epoch time.time() seconds on the same host; simulated presentation uses relative receive elapsed time, not browser video.currentTime',
        'browser_qa': 'not performed; this is offline receive-clock simulation plus OpenCV render_v2 projection QA',
        'offline_renderer': 'backend/poc_ar_arrow/ar_arrow_v2.py::render_v2; output is not evidence of WebGL pixels',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend-url', default='http://127.0.0.1:5011')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--video-filename', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--start-floor', required=True)
    parser.add_argument('--destination-floor', required=True)
    parser.add_argument('--duration', type=float, default=60.0)
    parser.add_argument('--out-dir', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    video_info = video_metadata(args.video)
    start = request_json(args.backend_url, 'POST', '/api/start-navigation', {
        'video_filename': args.video_filename,
        'destination': args.destination,
        'start_floor': args.start_floor,
        'destination_floor': args.destination_floor,
        'auto_floor': False,
        'interval': 1.5,
        'debug_mode': False,
    })
    if not start.get('success'):
        raise RuntimeError(f'backend rejected start: {start}')
    args.session_id = int(start['session_id'])
    timeline_path = args.out_dir / f'{args.video.stem}_timeline.jsonl'
    events = []
    first_receive = None
    first_update_receive = None
    last_timestamp = -math.inf
    updates_seen = []
    with timeline_path.open('w', encoding='utf-8') as stream:
        for event in iter_sse(args.backend_url, args.session_id):
            received = time.time()
            first_receive = first_receive or received
            if event.get('type') == 'update' and isinstance(event.get('timestamp'), (int, float)):
                first_update_receive = first_update_receive or received
                updates_seen.append(event)
                if float(event['timestamp']) >= args.duration and float(event['timestamp']) > last_timestamp:
                    last_timestamp = float(event['timestamp'])
            evidence = event.setdefault('_evidence', {})
            evidence['received_wall_time_s'] = received
            evidence['receive_elapsed_from_first_event_s'] = received - first_receive
            if event.get('type') == 'update' and isinstance(event.get('timestamp'), (int, float)) and first_update_receive is not None:
                evidence['receive_elapsed_from_first_update_s'] = received - first_update_receive
            stream.write(json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n')
            stream.flush()
            events.append(event)
            if last_timestamp >= args.duration:
                break

    try:
        request_json(args.backend_url, 'POST', '/api/stop-navigation', {'session_id': args.session_id})
    except Exception:
        pass
    try:
        final_state = {}
        for _ in range(20):
            final_state = request_json(
                args.backend_url, 'GET',
                f'/api/navigation-state?session_id={args.session_id}'
            )
            if final_state.get('tracking_diagnostics') is not None:
                break
            time.sleep(0.1)
        if final_state.get('tracking_diagnostics'):
            events.append({
                'type': 'diagnostics_snapshot',
                'tracking_diagnostics': final_state['tracking_diagnostics'],
                '_evidence': {'received_wall_time_s': time.time()},
            })
    except Exception:
        pass
    summary = summarize(events, first_receive or time.time(), video_info, args)
    summary['timeline_path'] = str(timeline_path)
    summary_path = args.out_dir / f'{args.video.stem}_summary.json'
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    updates = [event for event in events if event.get('type') == 'update']
    render_contact_sheet(args.video, updates, args.out_dir / f'{args.video.stem}_contact_sheet.png')
    render_dropout_preview(args.video, updates, args.out_dir / f'{args.video.stem}_dropout_preview.mp4')
    print(json.dumps({
        'session_id': args.session_id,
        'timeline': str(timeline_path),
        'summary': str(summary_path),
        'updates': len(updates),
        'last_timestamp_s': summary['last_update_timestamp_s'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
