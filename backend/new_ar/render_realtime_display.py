"""Render what a camera user could see at each display deadline.

Input poses must come from a paced ``live_session.py`` run. At video time t the
renderer considers only results whose measured completion time is <= t. A weak
or stale latest result hides world AR; it never looks ahead for a better pose.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

from render_live import render_scene


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-pose-age-s', type=float, default=0.15)
    args = parser.parse_args()
    out = args.out.resolve()
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    scene = json.loads((out / 'prepared_scene.json').read_text(encoding='utf-8'))
    rows = [json.loads(line) for line in (out / 'poses.jsonl').open(encoding='utf-8')]

    if len(rows) != summary['frames']:
        raise ValueError('Pose log frame count differs from the run summary')
    if any(float(b['available_wall_s']) < float(a['available_wall_s']) for a, b in zip(rows, rows[1:])):
        raise ValueError('Pose completion times are not monotonic')
    if any(row['frame'] != index or row['time'] > row['available_wall_s'] for index, row in enumerate(rows)):
        raise ValueError('Pose log is out of order or contains a negative latency')

    cap = cv2.VideoCapture(summary['video'])
    if not cap.isOpened():
        raise RuntimeError(f"Cannot read source video: {summary['video']}")
    fps = float(summary['fps'])
    size = (1280, 720)
    temporary = out / 'camera_view_deadline.mp4v.mp4'
    final = out / 'camera_view_deadline.mp4'
    writer = cv2.VideoWriter(str(temporary), cv2.VideoWriter_fourcc(*'mp4v'), fps, size)
    if not writer.isOpened():
        raise RuntimeError('VideoWriter unavailable')

    latest = -1
    visible = 0
    counts = {'awaiting_result': 0, 'pose_rejected': 0, 'pose_stale': 0,
              'geometry_out_of_view': 0, 'world_ar_visible': 0}
    max_selected_age = 0.0
    provenance = []
    for frame_index in range(len(rows)):
        ok, raw = cap.read()
        if not ok:
            raise RuntimeError(f'Source video ended at frame {frame_index}')
        display_time = frame_index / fps
        while latest + 1 < len(rows) and float(rows[latest + 1]['available_wall_s']) <= display_time:
            latest += 1

        frame = cv2.resize(raw, size, interpolation=cv2.INTER_AREA)
        selected = rows[latest] if latest >= 0 else None
        state = 'WAITING FOR LOCALIZATION'
        reason = 'awaiting_result'
        age = None
        arrows = 0
        if selected is not None:
            age = display_time - float(selected['time'])
            if not selected['accepted'] or selected.get('error') is None or selected['error'] > 6.3:
                state, reason = 'POSITION UNCERTAIN', 'pose_rejected'
            elif age > args.max_pose_age_s:
                state, reason = 'POSITION TOO OLD', 'pose_stale'
            else:
                K = np.asarray(selected['K'], dtype=float).copy()
                K[0] *= size[0] / raw.shape[1]
                K[1] *= size[1] / raw.shape[0]
                frame, arrows = render_scene(
                    frame, scene['anchors'], np.asarray(selected['R']),
                    np.asarray(selected['t']), K,
                )
                if arrows:
                    state, reason = 'WORLD AR VISIBLE', 'world_ar_visible'
                    visible += 1
                else:
                    state, reason = 'ROUTE OUT OF VIEW', 'geometry_out_of_view'
                max_selected_age = max(max_selected_age, age)
        counts[reason] += 1

        cv2.rectangle(frame, (0, 0), (size[0], 72), (20, 20, 20), -1)
        cv2.putText(frame, f'CAMERA VIEW  {display_time:05.2f}s  |  {state}',
                    (15, 28), cv2.FONT_HERSHEY_SIMPLEX, .68, (255, 255, 255), 1, cv2.LINE_AA)
        detail = 'No completed pose yet'
        if selected is not None:
            detail = (f"pose frame={selected['frame']}  age={age * 1000:.0f}ms  "
                      f"completed={selected['available_wall_s']:.3f}s  arrows={arrows}")
        cv2.putText(frame, detail, (15, 56), cv2.FONT_HERSHEY_SIMPLEX,
                    .55, (210, 225, 230), 1, cv2.LINE_AA)
        cv2.rectangle(frame, (0, 687), (size[0], 720), (20, 20, 20), -1)
        cv2.putText(frame, 'Fixed test route: M21_B | No future video frames or poses',
                    (15, 710), cv2.FONT_HERSHEY_SIMPLEX, .52,
                    (220, 220, 220), 1, cv2.LINE_AA)
        writer.write(frame)
        provenance.append({'display_frame': frame_index, 'display_time_s': display_time,
                           'selected_pose_frame': selected['frame'] if selected else None,
                           'selected_pose_time_s': selected['time'] if selected else None,
                           'selected_pose_available_s': selected['available_wall_s'] if selected else None,
                           'pose_age_s': age, 'state': reason, 'visible_arrows': arrows})
    cap.release()
    writer.release()

    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error',
                    '-i', str(temporary), '-c:v', 'libx264', '-preset', 'veryfast',
                    '-crf', '19', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                    str(final)], check=True)
    check = cv2.VideoCapture(str(final))
    decoded = 0
    while check.read()[0]:
        decoded += 1
    check.release()
    if decoded != len(rows):
        raise RuntimeError(f'Output frame count {decoded} differs from {len(rows)}')

    no_future = all(
        item['selected_pose_frame'] is None or
        (item['selected_pose_frame'] <= item['display_frame'] and
         item['selected_pose_available_s'] <= item['display_time_s'])
        for item in provenance
    )
    age_ok = all(
        item['state'] not in {'world_ar_visible', 'geometry_out_of_view'} or
        (0 <= item['pose_age_s'] <= args.max_pose_age_s)
        for item in provenance
    )
    audit = {'source_video': summary['video'], 'output': str(final),
             'frames': len(rows), 'fps': fps, 'max_pose_age_s': args.max_pose_age_s,
             'visible_ar_frames': visible, 'states': counts,
             'max_selected_pose_age_s': max_selected_age,
             'no_future_pose_at_display': no_future, 'age_gate_pass': age_ok,
             'note': 'Camera frame t displays the latest completed pose by t; '
                     'fixed map anchors and route are prepared before camera time zero.'}
    (out / 'camera_view_deadline_audit.json').write_text(
        json.dumps(audit, indent=2), encoding='utf-8')
    (out / 'camera_view_deadline_timeline.jsonl').write_text(
        ''.join(json.dumps(item) + '\n' for item in provenance), encoding='utf-8')
    if not no_future or not age_ok:
        raise RuntimeError('Causality or freshness gate failed')
    print(json.dumps(audit, indent=2))


if __name__ == '__main__':
    main()
