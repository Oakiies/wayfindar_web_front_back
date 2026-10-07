"""Run fresh production navigation; compare raw/EMA AR on identical poses.

Standalone process only. Does not start/stop an API server or use cached fixes.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('NAV_ACCEL', '1')
os.environ.setdefault('NAV_MATCHING_MODE', 'superpoint')
os.environ.setdefault('NAV_RETRIEVAL_MODE', 'megaloc')

import cv2
import numpy as np

from app.services.floor_service import initialize_system
from app.services.session import NavigationSession
from app.services import video_processor as vp, ar_service
from poc_ar_arrow.ar_arrow_v2 import PoseStabilizer
from run_non_imu_video_comparison import payload_screen_polygons
from render_fullrate_non_imu_ar import draw_overlay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=float, default=60)
    parser.add_argument('--interval', type=float, default=1.5)
    parser.add_argument('--destination', default='M21_A')
    parser.add_argument('--video', default=r'D:\video\video_from_iphone_oak_wide\IMG_6955.MOV')
    args = parser.parse_args()
    out = ROOT / 'poc_cross_camera/out/replay_registration_1p5s'
    out.mkdir(parents=True, exist_ok=True)
    initialize_system()
    session = NavigationSession(int(time.time()*1000), args.destination, 'floor1',
        Path(args.video).name, 'megaloc', False, start_floor='floor1', auto_floor=True)
    original_extract, original_ar = vp.extract_frames_from_video, vp._ar_world
    shadow = {'stabilizer': None, 'floor': None, 'payload': None, 'time': None}
    current = {}
    updates = []
    contacts = []
    next_contact = 0
    writer = cv2.VideoWriter(str(out / 'comparison.mp4'), cv2.VideoWriter_fourcc(*'mp4v'),
                             1 / args.interval, (1280, 360))
    if not writer.isOpened():
        raise RuntimeError('Cannot open comparison writer')

    def extract(path, interval):
        for item in original_extract(path, interval):
            if item[2] > args.duration:
                break
            current['frame'], current['timestamp'] = item[1], item[2]
            yield item

    def compare_ar(sess, localizer, floor, pose, x, y, path, inliers,
                   image_size=None, reproj_error=None, **kwargs):
        if shadow['floor'] != floor:
            projector = ar_service.get_projector(floor, localizer)
            if projector:
                shadow['stabilizer'] = PoseStabilizer(alpha=.24, max_jump_m=1,
                    max_turn_deg=22, turn_follow_deg=6, turn_alpha=.5,
                    expected_interval_s=1.5, metres_per_unit=projector.metres_per_unit)
                shadow['floor'] = floor
        fresh = ar_service.build_ar_world_poc(localizer, floor, pose, x, y, path,
            inliers, image_size, reproj_error, shadow['stabilizer'],
            timestamp=kwargs.get('timestamp'))
        if fresh is not None:
            shadow['payload'], shadow['time'] = fresh, current['timestamp']
        return original_ar(sess, localizer, floor, pose, x, y, path, inliers,
                           image_size, reproj_error)

    original_put = session.queue.put
    stream = (out / 'updates.jsonl').open('w', encoding='utf-8')

    def put(event, *a, **kw):
        nonlocal next_contact
        original_put(event, *a, **kw)
        if event.get('type') != 'update':
            return
        ts = event['timestamp']
        baseline = shadow['payload'] if shadow['time'] is not None and ts-shadow['time'] <= 3 else None
        if event.get('ar_state') == 'arrived':
            baseline = vp._ar_arrival_only(baseline)
        record = {**event, 'baseline_ar_world': baseline}
        stream.write(json.dumps(record, ensure_ascii=False)+'\n')
        stream.flush()
        updates.append({'timestamp': ts, 'method': event.get('method'),
            'ar': event.get('ar_world') is not None, 'baseline_ar': baseline is not None,
            'ar_state': event.get('ar_state')})
        frame = current['frame']
        panes = []
        for label, payload in [('BEFORE: backend EMA + hold', baseline),
                               ('AFTER: current accepted pose', event.get('ar_world'))]:
            pane = draw_overlay(frame, payload_screen_polygons(payload, frame.shape))
            pane = cv2.resize(pane, (640, 360))
            cv2.rectangle(pane, (0, 0), (640, 42), (0, 0, 0), -1)
            cv2.putText(pane, f'{label}  {ts:.2f}s', (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                        .52, (255, 255, 255), 1, cv2.LINE_AA)
            panes.append(pane)
        pair = np.hstack(panes)
        writer.write(pair)
        if ts >= next_contact:
            contacts.append(pair)
            cv2.imwrite(str(out / f'frame_{ts:06.2f}.jpg'), pair)
            next_contact = ts+5
        if len(updates) % 50 == 0:
            print(f'VALIDATION {ts:.2f}s: {len(updates)} updates', flush=True)

    session.queue.put = put
    vp.extract_frames_from_video, vp._ar_world = extract, compare_ar
    try:
        vp.process_navigation(session, args.video, args.interval)
    finally:
        vp.extract_frames_from_video, vp._ar_world = original_extract, original_ar
        stream.close()
        writer.release()
    if contacts:
        cv2.imwrite(str(out / 'contact_sheet.jpg'), np.vstack(contacts))
    summary = {'video': args.video, 'duration_requested': args.duration,
               'interval': args.interval, 'updates': updates,
               'note': 'Fresh production fixes. Baseline shares fixes/routes; browser easing excluded. '
                       'Preview contains only update frames; gaps are omitted, so it is not real-time playback.'}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'VALIDATION COMPLETE: {len(updates)} updates; {out}', flush=True)


if __name__ == '__main__':
    main()
