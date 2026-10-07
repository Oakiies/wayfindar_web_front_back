"""Render validation JSONL at source FPS, preserving failed-fix gaps."""
import json
from pathlib import Path
import cv2
import numpy as np
from run_non_imu_video_comparison import payload_screen_polygons
from render_fullrate_non_imu_ar import draw_overlay

OUT = Path(__file__).resolve().parent / 'out/replay_registration_1p5s'
VIDEO = r'D:\video\video_from_iphone_oak_wide\IMG_6955.MOV'
NORMAL_POSE_GAP_SECONDS = 1.65
MAX_BUFFERED_BRIDGE_SECONDS = 3.10
MAX_BRIDGE_SPEED_MPS = 3.0
MAX_BRIDGE_ROTATION_DPS = 45.0


def interpolate_camera(left, right, time):
    """Same bounded rigid-camera interpolation as frontend replayArPose.ts."""
    a = left.get('ar_world') if left else None
    if not a or left.get('method') == 'HOLD_LAST_FIX' or a.get('heldAge', 0) > 0:
        return None
    age = time-left['timestamp']
    if age < 0:
        return None
    if age < .001:
        return a
    b = right.get('ar_world') if right else None
    gap = right['timestamp']-left['timestamp'] if right else float('inf')
    if (not b or not 0 < gap <= MAX_BUFFERED_BRIDGE_SECONDS or age > gap
            or left.get('current_floor') != right.get('current_floor')
            or right.get('method') == 'HOLD_LAST_FIX' or b.get('heldAge', 0) > 0
            or a['imgWH'] != b['imgWH']):
        return a if age <= .15 else None
    ra, rb = np.array(a['R']), np.array(b['R'])
    ca, cb = -ra.T @ np.array(a['t']), -rb.T @ np.array(b['t'])
    if gap > NORMAL_POSE_GAP_SECONDS:
        metres_per_unit = float(a.get('metres_per_unit', 0) or 0)
        speed_mps = np.linalg.norm(cb-ca)*metres_per_unit/gap if metres_per_unit > 0 else float('inf')
        rotation_dps = np.degrees(np.linalg.norm(cv2.Rodrigues(rb @ ra.T)[0]))/gap
        if speed_mps > MAX_BRIDGE_SPEED_MPS or rotation_dps > MAX_BRIDGE_ROTATION_DPS:
            return a if age <= .15 else None
    f = age/gap
    delta = cv2.Rodrigues(rb @ ra.T)[0]*f
    r = cv2.Rodrigues(delta)[0] @ ra
    t = -r @ ((1-f)*ca+f*cb)
    k = (1-f)*np.array(a['K'])+f*np.array(b['K'])
    return {**a, 'R': r.tolist(), 't': t.tolist(), 'K': k.tolist()}


def main(out=OUT, baseline_interpolate=False):
    records = [json.loads(line) for line in (out / 'updates.jsonl').read_text(encoding='utf-8').splitlines()]
    if not records:
        raise RuntimeError('No fresh localization results')
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS)
    writer = cv2.VideoWriter(str(out / 'comparison_realtime.mp4'),
                            cv2.VideoWriter_fourcc(*'mp4v'), fps, (1280, 360))
    if not writer.isOpened():
        raise RuntimeError('Video writer failed')
    selected = None
    index = 0
    total = 0
    visible = [0, 0]
    pose_frames = [0, 0]
    contact = []
    next_contact = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts = cap.get(cv2.CAP_PROP_POS_MSEC)/1000
        if ts > 60:
            break
        # Project directly into the diagnostic pane; full-resolution alpha
        # compositing for every polygon needlessly multiplies export cost.
        frame = cv2.resize(frame, (640, 360))
        while index < len(records) and records[index]['timestamp'] <= ts:
            selected = records[index]
            index += 1
        age = ts - selected['timestamp'] if selected else float('inf')
        before = selected.get('baseline_ar_world') if selected and age <= 3 else None
        if baseline_interpolate:
            next_row = records[index] if index < len(records) else None
            old_left = {**selected, 'ar_world': selected.get('baseline_ar_world')} if selected else None
            old_right = {**next_row, 'ar_world': next_row.get('baseline_ar_world')} if next_row else None
            before = interpolate_camera(old_left, old_right, ts)
        after = interpolate_camera(selected, records[index] if index < len(records) else None, ts)
        panes = []
        titles = ('BEFORE: moving world anchors', 'AFTER: fixed world anchors') if baseline_interpolate else ('BEFORE: EMA + hold', 'AFTER: buffered pose')
        for i, (title, payload) in enumerate([(titles[0], before), (titles[1], after)]):
            polygons = payload_screen_polygons(payload, frame.shape)
            pane = cv2.resize(draw_overlay(frame, polygons), (640, 360))
            cv2.rectangle(pane, (0, 0), (640, 47), (0, 0, 0), -1)
            cv2.putText(pane, f'{title} | {ts:.2f}s | {selected.get("method", "") if selected else "no fix"}',
                        (8, 20), cv2.FONT_HERSHEY_SIMPLEX, .48, (255,255,255), 1, cv2.LINE_AA)
            cv2.putText(pane, 'world AR present' if payload else 'world AR hidden', (8, 39),
                        cv2.FONT_HERSHEY_SIMPLEX, .44, (255,255,255), 1, cv2.LINE_AA)
            panes.append(pane)
            pose_frames[i] += payload is not None
            # Visibility requires at least one polygon overlapping the image.
            visible[i] += any(np.isfinite(poly).all() and poly[:,0].max() >= 0
                and poly[:,0].min() < frame.shape[1] and poly[:,1].max() >= 0
                and poly[:,1].min() < frame.shape[0] for poly, *_ in polygons)
        pair = np.hstack(panes)
        writer.write(pair)
        if ts >= next_contact:
            contact.append(pair)
            next_contact += 5
        total += 1
    cap.release()
    writer.release()
    cv2.imwrite(str(out / 'contact_realtime.jpg'), np.vstack(contact))
    result = {'frames': total, 'fps': fps, 'payload_frames_before_after': pose_frames,
              'visible_polygon_frames_before_after': visible,
              'baseline_interpolated': baseline_interpolate,
              'note': 'Coverage, not spatial accuracy. Baseline excludes browser easing. '
                      'Destination marker is not drawn by this diagnostic renderer.'}
    (out / 'coverage.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', type=Path, default=OUT)
    parser.add_argument('--baseline-interpolate', action='store_true')
    args = parser.parse_args()
    main(args.input_dir, args.baseline_interpolate)
