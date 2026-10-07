"""Calibrate first, then track map landmarks at source FPS with periodic reseeding.

No time-specific route/pose corrections. Production map and solvers are read-only.
"""
from pathlib import Path
import argparse
import json
import sys
import time
import cv2
import numpy as np

def finite_json(value):
    if isinstance(value, dict): return {k: finite_json(v) for k,v in value.items()}
    if isinstance(value, list): return [finite_json(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value): return None
    if isinstance(value, np.generic): return finite_json(value.item())
    return value

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parent
sys.path[:0] = [str(BACKEND / 'poc_cross_camera'), str(BACKEND), str(BACKEND / 'app')]
from run_temporal_landmark_propagation import (
    Localizer, accelerate_localizer, DEFAULT_DATA, DEFAULT_MAP, DEFAULT_GRAPH,
    find_reference_size, evaluate_target, loc, dedupe_correspondences,
)
from run_gap_tracked_pnp import track_step, solve_pose
from app.core.self_calibration import _solve_p4pf
from app.core.ar_geometry import FloorProjector

def dump(path, value):
    path.write_text(json.dumps(finite_json(value), indent=2, allow_nan=False), encoding='utf-8')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', default=r'D:\video\video_from_iphone_pare\IMG_1895.MOV')
    ap.add_argument('--start', type=float, default=20)
    ap.add_argument('--end', type=float, default=60)
    ap.add_argument('--calibration-seconds', type=float, default=5,
        help='seconds from --start sampled before rendering; increase when the opening is texture-poor')
    ap.add_argument('--out', type=Path, default=ROOT / 'out')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cv2.setRNGSeed(1895)
    localizer = Localizer(floor_id='floor1', data_dir=DEFAULT_DATA,
        floor_plan_path=DEFAULT_MAP, json_map_path=DEFAULT_GRAPH,
        matching_mode='superpoint', retrieval_mode='megaloc')
    accelerate_localizer(localizer)
    localizer.camera_self_calibrator.close()
    size = find_reference_size(DEFAULT_DATA)
    projector = FloorProjector(localizer.H_matrix, localizer.floor_config)
    cap = cv2.VideoCapture(args.video)
    assert cap.isOpened(), args.video
    fps = cap.get(cv2.CAP_PROP_FPS)
    map_K = localizer.K.copy()
    calibration_file = args.out / 'camera_calibration.json'
    if calibration_file.exists():
        calibration = json.loads(calibration_file.read_text())
        assert calibration['video'] == args.video and calibration['image_size'] == list(size)
    else:
        estimates, views, thumbs = [], [], []
        for seconds in np.arange(args.start, args.start + args.calibration_seconds, 1.0):
            cap.set(cv2.CAP_PROP_POS_FRAMES, round(seconds * fps))
            ok, frame = cap.read()
            assert ok
            query, direct, _ = evaluate_target(localizer, frame, size, 20)
            estimate = _solve_p4pf(direct['points_2d'], direct['points_3d'],
                map_K[0, 2], map_K[1, 2], 256, 8.0, int(seconds * 100))
            estimates.append({'time': float(seconds), 'estimate': estimate})
            views.append(direct)
            thumb = cv2.resize(frame, (480, 270))
            cv2.putText(thumb, f'{seconds:.1f}s', (12, 28), 0, .8, (0,255,255), 2)
            thumbs.append(thumb)
            print('CALIBRATION', estimates[-1], flush=True)
        valid = [x['estimate']['focal_px'] for x in estimates
            if x['estimate'] and x['estimate']['inliers'] >= 10
            and 0.25 * size[0] < x['estimate']['focal_px'] < 3 * size[0]]
        if len(valid) < 3:
            raise RuntimeError('Three valid startup estimates required before rendering')
        focal = float(np.median(valid))
        K = map_K.copy()
        K[0,0] = K[1,1] = focal
        checks = []
        validation_indices = list(range(max(0, len(views)-2), len(views)))
        for label, model in [('map_K', map_K), ('estimated_K', K)]:
            localizer.K = model
            for index in validation_indices:
                pose = solve_pose(localizer, views[index]['points_2d'], views[index]['points_3d'])
                checks.append({'model': label, 'time': float(args.start + index),
                    'accepted': bool(pose and pose['accepted']),
                    'inliers': len(pose['inliers']) if pose else 0,
                    'error': float(pose['reproj_error']) if pose else None})
        if not all(x['accepted'] for x in checks if x['model'] == 'estimated_K'):
            raise RuntimeError('Estimated K failed held-out startup validation')
        calibration = dict(video=args.video, image_size=list(size), fps=fps,
            method='Existing P4Pf solver; median of 20,21,22s; validation on 23,24s',
            K=K.tolist(), map_K=map_K.tolist(), distortion=[0]*5,
            assumptions=['fixed focal, square pixels', 'principal point inherited from map image center',
                'zero residual distortion assumed for phone-processed video; not measured',
                '20-24s calibration warmup is included in output, not independent evaluation'],
            focal_estimates=estimates, validation=checks,
            hfov_deg=float(np.degrees(2*np.arctan(size[0]/(2*focal)))),
            focal_mad_px=float(np.median(np.abs(np.array(valid)-focal))))
        dump(calibration_file, calibration)
        cv2.imwrite(str(args.out / 'calibration_frames.jpg'), np.hstack(thumbs))
    localizer.K = np.array(calibration['K'])
    dump(args.out / 'map_geometry.json', dict(H=localizer.H_matrix.tolist(),
        floor_config=localizer.floor_config, metres_per_unit=projector.metres_per_unit))
    print('CALIBRATION LOCKED', calibration['K'], flush=True)
    start_index, end_index = int(np.ceil(args.start * fps)), int(np.ceil(args.end * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_index)
    p2, p3, ids = np.empty((0,2), np.float32), np.empty((0,3), np.float32), np.empty(0,np.int64)
    previous = None
    last_seed = -10000
    last_C, last_time = None, None
    rows = []
    started = time.perf_counter()
    with (args.out / 'poses.jsonl').open('w', encoding='utf-8') as log:
        for index in range(start_index, end_index):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Unexpected end of source video')
            timestamp = index / fps
            gray = loc.resize_query_image(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), size)
            if previous is not None:
                p2,p3,ids = track_step(previous, gray, p2,p3,ids, 1.0)
            reseed = index-last_seed >= round(fps) or (len(p2)<20 and index-last_seed>=round(fps*.25))
            if reseed:
                _, direct, _ = evaluate_target(localizer, frame, size, 20)
                direct_pose = solve_pose(localizer, direct['points_2d'], direct['points_3d'])
                if direct_pose and direct_pose['accepted']:
                    keep = direct_pose['inliers']
                    # Fresh verified observations supersede old tracks of the same map point.
                    items = [dict(point_2d=a, point_3d=b, mp_id=int(c), track_error=0)
                        for a,b,c in zip(direct['points_2d'][keep],direct['points_3d'][keep],direct['mp_ids'][keep])]
                    items += [dict(point_2d=a,point_3d=b,mp_id=int(c),track_error=1)
                        for a,b,c in zip(p2,p3,ids)]
                    combined = dedupe_correspondences(items)
                    p2,p3,ids = (combined[k] for k in ['points_2d','points_3d','mp_ids'])
                last_seed = index
            pose = solve_pose(localizer,p2,p3)
            accepted = bool(pose and pose['accepted'])
            reason = 'ok' if accepted else 'pnp_quality'
            if accepted:
                C = -pose['R'].T @ pose['t']
                # Time-aware physical displacement gate; never freeze a stale AR overlay.
                if last_C is not None and np.linalg.norm(C-last_C)*projector.metres_per_unit > .25 + 2.5*(timestamp-last_time):
                    accepted,reason = False,'position_jump'
                if accepted:
                    last_C,last_time = C,timestamp
            row = dict(frame=index,time=timestamp,accepted=accepted,reason=reason,
                reseed=reseed,tracks=len(p2),inliers=len(pose['inliers']) if pose else 0,
                error=float(pose['reproj_error']) if pose else None)
            if pose:
                row.update(R=pose['R'].tolist(),t=pose['t'].tolist(),
                    xy=projector.camera_floor_px(pose['R'],pose['t']).tolist())
            log.write(json.dumps(row)+'\n')
            rows.append(row)
            previous=gray
            if index % round(fps) == 0:
                print(f'TRACK {timestamp:.2f}s accepted={accepted} tracks={len(p2)} inliers={row["inliers"]}', flush=True)
    cap.release()
    dump(args.out/'tracking_summary.json', dict(frames=len(rows),fps=fps,
        accepted=sum(x['accepted'] for x in rows),reseeds=sum(x['reseed'] for x in rows),
        elapsed_s=time.perf_counter()-started,video=args.video,start=args.start,end=args.end))

if __name__ == '__main__':
    main()
