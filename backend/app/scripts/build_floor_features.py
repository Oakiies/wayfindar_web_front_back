"""Build SuperPoint keyframes + MegaLoc global descriptors for one registered floor.

Run from the backend root so `app.*` imports and data/ paths resolve:

    cd WebNav_front_back/backend
    .venv/Scripts/python -m app.scripts.build_floor_features --floor siamdis_floor3

Steps (each skipped if its output exists, unless --force):
  1. SuperPoint   -> <data_dir>/keyframes_superpoint/   (reuses build_superpoint_database.process_floor)
  2. MegaLoc      -> <data_dir>/global_descriptors_megaloc.npy  ({keyframe_id: float32[8448]})
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / 'data'
# build_superpoint_database.py does a bare `import hloc_wrapper`.
sys.path.insert(0, str(APP_DIR / 'core' / 'models'))
sys.path.insert(0, str(APP_DIR.parent))


def load_floor(floor_id):
    config = json.loads((DATA_DIR / 'config' / 'building.json').read_text(encoding='utf-8-sig'))
    for floor in config['floors']:
        if floor['id'] == floor_id:
            return {**floor, 'data_dir': str(DATA_DIR / floor['data_dir'])}
    raise SystemExit(f'floor {floor_id!r} is not in building.json')


def build_superpoint(floor, force):
    import hloc_wrapper
    from app.scripts.build_superpoint_database import process_floor
    extractor = hloc_wrapper.HlocExtractor(device='auto')
    report = process_floor(
        floor,
        extractor,
        max_distance_px=5.0,
        force=force,
        progress=lambda done, total: print(
            f'FEATURE_PROGRESS {json.dumps({"stage": "superpoint", "done": done, "total": total})}',
            flush=True,
        ),
    )
    print(f"[superpoint] ok={report['num_success']} skipped={report['num_skipped']} failed={report['num_failed']}")


def build_megaloc(floor, force):
    import torch
    from app.core.localization import extract_global_features, load_megaloc_model

    data_dir = Path(floor['data_dir'])
    out_path = data_dir / 'global_descriptors_megaloc.npy'
    if out_path.exists() and not force:
        print(f'[megaloc] {out_path.name} exists, skipping (use --force)')
        return
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = load_megaloc_model().to(device).eval()
    descriptors, failed = {}, 0
    keyframe_dirs = sorted(p for p in (data_dir / 'keyframes').iterdir() if p.is_dir())
    for index, kf_dir in enumerate(keyframe_dirs, start=1):
        image = next((p for p in (kf_dir / 'image.jpg', kf_dir / 'image.png') if p.exists()), None)
        if image is None:
            failed += 1
        else:
            try:
                descriptors[kf_dir.name] = np.asarray(extract_global_features(image, model), dtype=np.float32)
            except Exception as exc:  # keep going; the report below shows the count
                print(f'  {kf_dir.name}: {exc}')
                failed += 1
        print(
            f'FEATURE_PROGRESS {json.dumps({"stage": "megaloc", "done": index, "total": len(keyframe_dirs)})}',
            flush=True,
        )
    np.save(out_path, descriptors)
    print(f'[megaloc] saved {len(descriptors)} descriptors ({failed} failed) -> {out_path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--floor')
    parser.add_argument('--data-dir', help='Use this project data directory instead of a registered floor.')
    parser.add_argument('--floor-id', help='Display name when --data-dir is used.')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--only', choices=['superpoint', 'megaloc'])
    args = parser.parse_args()
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
        if not (data_dir / 'keyframes').is_dir():
            raise SystemExit(f'keyframes directory not found: {data_dir / "keyframes"}')
        floor = {'id': args.floor_id or data_dir.name, 'data_dir': str(data_dir)}
    elif args.floor:
        floor = load_floor(args.floor)
    else:
        parser.error('provide --floor or --data-dir')
    keyframes_dir = Path(floor['data_dir']) / 'keyframes'
    if not any(path.is_dir() for path in keyframes_dir.iterdir()):
        raise SystemExit(f'no keyframes found in {keyframes_dir}')
    if args.only != 'megaloc':
        build_superpoint(floor, args.force)
    if args.only != 'superpoint':
        build_megaloc(floor, args.force)


if __name__ == '__main__':
    main()
