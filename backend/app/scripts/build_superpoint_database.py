"""Build a SuperPoint-compatible keyframe database from the existing ORB keyframes."""

import argparse
import json
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

import hloc_wrapper

BUILDING_CONFIG_PATH = Path('data/config/building.json')


def load_building_config(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def get_enabled_floors(config, floor_ids=None):
    floors = [floor for floor in config.get('floors', []) if floor.get('enabled', True)]
    if floor_ids:
        floor_set = set(floor_ids)
        floors = [floor for floor in floors if floor.get('id') in floor_set]
    return floors


def nearest_transfer(superpoint_kpts, orb_kpts, orb_mp_ids, max_distance_px):
    assigned = np.full(len(superpoint_kpts), -1, dtype=np.int64)
    if len(superpoint_kpts) == 0 or len(orb_kpts) == 0 or len(orb_mp_ids) == 0:
        return assigned, 0
    valid = orb_mp_ids > 0
    if not np.any(valid):
        return assigned, 0
    source_kpts = orb_kpts[valid].astype(np.float32)
    source_ids = orb_mp_ids[valid].astype(np.int64)
    max_dist_sq = float(max_distance_px) ** 2
    chunk_size = 512
    for start in range(0, len(superpoint_kpts), chunk_size):
        chunk = superpoint_kpts[start:start + chunk_size].astype(np.float32)
        diff = chunk[:, None, :] - source_kpts[None, :, :]
        dist_sq = np.sum(diff * diff, axis=2)
        best_indices = np.argmin(dist_sq, axis=1)
        best_dist_sq = dist_sq[np.arange(len(chunk)), best_indices]
        keep = best_dist_sq <= max_dist_sq
        if np.any(keep):
            assigned[start:start + len(chunk)][keep] = source_ids[best_indices[keep]]
    return assigned, int(np.count_nonzero(assigned > 0))


def copy_if_exists(src, dst):
    if src.exists():
        shutil.copy2(src, dst)
        return True
    return False


def process_floor(floor_config, extractor, max_distance_px=5.0, force=False):
    floor_id = floor_config['id']
    data_dir = Path(floor_config['data_dir'])
    src_root = data_dir / 'keyframes'
    dst_root = data_dir / 'keyframes_superpoint'
    if not src_root.exists():
        raise FileNotFoundError(f'{src_root} does not exist')
    dst_root.mkdir(parents=True, exist_ok=True)
    report = {
        'floor_id': floor_id,
        'data_dir': str(data_dir),
        'source_keyframes': str(src_root),
        'output_keyframes': str(dst_root),
        'max_distance_px': float(max_distance_px),
        'frames': [],
        'started_at': time.time(),
    }
    keyframe_dirs = sorted([path for path in src_root.iterdir() if path.is_dir()])
    for index, src_dir in enumerate(keyframe_dirs, start=1):
        dst_dir = dst_root / src_dir.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        desc_path = dst_dir / 'descriptors.npy'
        if desc_path.exists() and not force:
            report['frames'].append({'keyframe_id': src_dir.name, 'status': 'skipped', 'reason': 'already_exists'})
            continue
        image_path = src_dir / 'image.png'
        if not image_path.exists():
            image_path = src_dir / 'image.jpg'
        if not image_path.exists():
            report['frames'].append({'keyframe_id': src_dir.name, 'status': 'failed', 'reason': 'image_missing'})
            continue
        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            report['frames'].append({'keyframe_id': src_dir.name, 'status': 'failed', 'reason': 'image_decode_failed'})
            continue
        orb_kpts = np.load(src_dir / 'keypoints.npy').astype(np.float32)
        orb_mp_ids = np.load(src_dir / 'mappoint_ids.npy')
        sp_kpts, sp_desc, sp_scores = extractor.extract(image)
        sp_mp_ids, matched_count = nearest_transfer(sp_kpts, orb_kpts, orb_mp_ids, max_distance_px)
        np.save(dst_dir / 'keypoints.npy', sp_kpts.astype(np.float32))
        np.save(dst_dir / 'descriptors.npy', sp_desc.astype(np.float32))
        np.save(dst_dir / 'keypoint_scores.npy', sp_scores.astype(np.float32))
        np.save(dst_dir / 'mappoint_ids.npy', sp_mp_ids.astype(np.int64))
        copy_if_exists(src_dir / 'pose.txt', dst_dir / 'pose.txt')
        if not copy_if_exists(src_dir / 'image.png', dst_dir / 'image.png'):
            copy_if_exists(src_dir / 'image.jpg', dst_dir / 'image.jpg')
        report['frames'].append({
            'keyframe_id': src_dir.name,
            'status': 'ok',
            'num_superpoint_keypoints': int(len(sp_kpts)),
            'num_assigned_mappoints': int(matched_count),
        })
        if index % 100 == 0 or index == len(keyframe_dirs):
            print(f'[{floor_id}] {index}/{len(keyframe_dirs)} keyframes processed')
    report['finished_at'] = time.time()
    report['duration_seconds'] = report['finished_at'] - report['started_at']
    report['num_frames'] = len(report['frames'])
    report['num_success'] = sum(1 for frame in report['frames'] if frame['status'] == 'ok')
    report['num_skipped'] = sum(1 for frame in report['frames'] if frame['status'] == 'skipped')
    report['num_failed'] = sum(1 for frame in report['frames'] if frame['status'] == 'failed')
    report_path = data_dir / 'superpoint_build_report.json'
    with open(report_path, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(f'[{floor_id}] report written to {report_path}')
    return report


def main():
    parser = argparse.ArgumentParser(description='Build SuperPoint keyframe databases from existing ORB keyframes.')
    parser.add_argument('--floor', action='append', dest='floors', help='Only process the specified floor id. Repeat for multiple floors.')
    parser.add_argument('--max-distance', type=float, default=5.0, help='Maximum pixel distance for inheriting an ORB map point id.')
    parser.add_argument('--force', action='store_true', help='Overwrite previously generated SuperPoint keyframes.')
    parser.add_argument('--device', default='auto', help='Extractor device: auto, cpu, or cuda.')
    args = parser.parse_args()
    config = load_building_config(BUILDING_CONFIG_PATH)
    floors = get_enabled_floors(config, args.floors)
    if not floors:
        raise SystemExit('No enabled floors matched the request.')
    extractor = hloc_wrapper.HlocExtractor(device=args.device)
    reports = [process_floor(floor, extractor, max_distance_px=args.max_distance, force=args.force) for floor in floors]
    summary = {
        'generated_at': time.time(),
        'floors': [report['floor_id'] for report in reports],
        'total_frames': sum(report['num_frames'] for report in reports),
        'total_success': sum(report['num_success'] for report in reports),
        'total_skipped': sum(report['num_skipped'] for report in reports),
        'total_failed': sum(report['num_failed'] for report in reports),
    }
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()

