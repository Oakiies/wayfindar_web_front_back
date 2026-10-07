"""Record and render the exact AR payload emitted by Test Localize."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
import requests


ROOT = Path(__file__).resolve().parent


def draw_payload(frame, payload):
    if not isinstance(payload, dict):
        return frame, 0
    polygons = payload.get('carets') or payload.get('chevrons') or []
    if not polygons:
        return frame, 0
    fx, fy, cx, cy = payload['K']
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=float)
    R = np.asarray(payload['R'], dtype=float)
    t = np.asarray(payload['t'], dtype=float).reshape(3)
    source_w, source_h = payload['imgWH']
    sx, sy = frame.shape[1] / source_w, frame.shape[0] / source_h
    output = frame.copy(); count = 0
    alphas = payload.get('alphas') or []
    for index, polygon in enumerate(polygons):
        world = np.asarray(polygon, dtype=float)
        camera = (R @ world.T).T + t
        if len(world) < 3 or np.any(camera[:, 2] <= 1e-8):
            continue
        pixels = (K @ camera.T).T
        pixels = pixels[:, :2] / pixels[:, 2:]
        pixels[:, 0] *= sx; pixels[:, 1] *= sy
        if not np.isfinite(pixels).all():
            continue
        mask = np.zeros(frame.shape[:2], np.uint8)
        contour = np.round(pixels).astype(np.int32)
        cv2.fillPoly(mask, [contour], 255)
        if cv2.countNonZero(mask) < 12:
            continue
        alpha = float(alphas[index]) if index < len(alphas) else 0.68
        layer = output.copy(); layer[mask > 0] = (255, 170, 0)
        output = cv2.addWeighted(layer, alpha, output, 1 - alpha, 0)
        cv2.polylines(output, [contour], True, (255, 240, 195), 1, cv2.LINE_AA)
        count += 1
    return output, count


def collect(base_url, filename, destination, duration):
    payload = {
        'video_filename': filename, 'origin': 'My location',
        'destination': destination, 'interval': 1.5,
        'auto_floor': False, 'start_floor': 'floor1',
        'destination_floor': 'floor1', 'debug_mode': False,
    }
    response = requests.post(f'{base_url}/api/start-navigation', json=payload)
    response.raise_for_status()
    session_id = response.json()['session_id']
    updates = []
    try:
        with requests.get(
            f'{base_url}/api/navigation-stream',
            params={'session_id': session_id, 'replay': 1}, stream=True,
        ) as stream:
            stream.raise_for_status()
            for line in stream.iter_lines(decode_unicode=True):
                if not line or not line.startswith('data:'):
                    continue
                event = json.loads(line[5:].strip())
                if event.get('type') == 'update':
                    updates.append(event)
                    if float(event.get('timestamp', 0)) >= duration:
                        break
                if event.get('type') == 'complete':
                    break
                if event.get('type') == 'error' and event.get('frame') is None:
                    break
    finally:
        requests.post(f'{base_url}/api/stop-navigation', json={'session_id': session_id})
    return session_id, updates


def render(video, updates, output, duration):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f'Cannot open {video}')
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    width, height = 1280, 720
    temporary = output.with_suffix('.mp4v.mp4')
    writer = cv2.VideoWriter(str(temporary), cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError('VideoWriter unavailable')
    by_frame = {int(item['frame']): item for item in updates}
    visible = 0; frames = 0; panels = []
    limit = int(round(duration * fps))
    for frame_index in range(limit):
        ok, raw = cap.read()
        if not ok: break
        frame = cv2.resize(raw, (width, height), interpolation=cv2.INTER_AREA)
        event = by_frame.get(frame_index)
        count = 0
        if event:
            frame, count = draw_payload(frame, event.get('ar_world'))
        visible += int(count > 0)
        label = f'{frame_index / fps:05.2f}s | {event.get("method") if event else "FINDING POSITION"} | arrows={count}'
        cv2.rectangle(frame, (0, 0), (width, 42), (20, 20, 20), -1)
        cv2.putText(frame, label, (14, 28), 0, .62, (255, 255, 255), 1, cv2.LINE_AA)
        writer.write(frame); frames += 1
        if frame_index % int(round(fps * 5)) == 0:
            panels.append(cv2.resize(frame, (640, 360)))
    cap.release(); writer.release()
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error',
        '-i', str(temporary), '-c:v', 'libx264', '-preset', 'veryfast',
        '-crf', '19', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output),
    ], check=True)
    if panels:
        while len(panels) % 3: panels.append(np.zeros_like(panels[0]))
        sheet = np.vstack([np.hstack(panels[i:i + 3]) for i in range(0, len(panels), 3)])
        cv2.imwrite(str(output.with_name(output.stem + '_contact.png')), sheet)
    return {'frames': frames, 'fps': fps, 'visible_ar_frames': visible}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:5010')
    parser.add_argument('--filename', default='floor1_pare_wide_mp4.mp4')
    parser.add_argument('--video', type=Path, default=Path(__file__).parents[1] / 'app/runtime/uploads/floor1_pare_wide_mp4.mp4')
    parser.add_argument('--destination', default='M21_B')
    parser.add_argument('--duration', type=float, default=60.0)
    parser.add_argument('--output', type=Path, default=ROOT / 'IMG_1895_TestLocalize_shared_core_0_60.mp4')
    args = parser.parse_args(); args.output = args.output.resolve()
    session_id, updates = collect(args.base_url, args.filename, args.destination, args.duration)
    args.output.with_suffix('.jsonl').write_text(
        ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in updates), encoding='utf-8',
    )
    summary = {'session_id': session_id, 'updates': len(updates), **render(args.video, updates, args.output, args.duration)}
    args.output.with_suffix('.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
