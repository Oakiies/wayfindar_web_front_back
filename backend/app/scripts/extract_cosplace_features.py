import argparse
from pathlib import Path

import numpy as np
import torch
from tqdm import tqdm

import build_topology as top
import localize_version2 as loc

BUILDING_CONFIG_PATH = Path('data/config/building.json')


def _load_target_floors(selected_floor_ids=None):
    if BUILDING_CONFIG_PATH.exists():
        building_config = top.load_building_config(str(BUILDING_CONFIG_PATH))
        floors = top.get_enabled_floors(building_config)
    else:
        floors = [{
            'id': 'floor5',
            'label': 'Floor 5',
            'data_dir': 'data/map_data/result_floor5_6'
        }]

    if selected_floor_ids:
        selected = set(selected_floor_ids)
        floors = [floor for floor in floors if floor['id'] in selected]

    return floors


def _extract_floor_descriptors(floor, model, overwrite=False):
    floor_id = floor['id']
    data_dir = Path(floor['data_dir'])
    keyframes_dir = data_dir / 'keyframes'
    output_desc_path = data_dir / 'global_descriptors_cosplace.npy'

    if not keyframes_dir.exists():
        print(f"Skipping {floor_id}: keyframes directory not found at {keyframes_dir}")
        return False

    if output_desc_path.exists() and not overwrite:
        print(f"Skipping {floor_id}: {output_desc_path.name} already exists")
        return True

    kf_dirs = sorted([d for d in keyframes_dir.iterdir() if d.is_dir()])
    print(f"Extracting CosPlace features for {floor_id} ({len(kf_dirs)} keyframes)")

    descriptors_dict = {}
    for kf_dir in tqdm(kf_dirs, desc=f"CosPlace {floor_id}"):
        image_path = kf_dir / 'image.jpg'
        if not image_path.exists():
            image_path = kf_dir / 'image.png'

        if not image_path.exists():
            print(f"Warning: missing image in {kf_dir}")
            continue

        try:
            desc = loc.extract_global_features(image_path, model)
            descriptors_dict[kf_dir.name] = desc
        except Exception as exc:
            print(f"Error processing {image_path}: {exc}")

    np.save(output_desc_path, descriptors_dict)
    print(f"Saved {len(descriptors_dict)} descriptors to {output_desc_path}")
    return True


def extract_features(selected_floor_ids=None, overwrite=False):
    floors = _load_target_floors(selected_floor_ids)
    if not floors:
        print("No enabled floors found in building config.")
        return

    print("Loading CosPlace model...")
    model = loc.load_global_retrieval_model('cosplace')
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = model.to(device)
    model.eval()

    completed = 0
    for floor in floors:
        if _extract_floor_descriptors(floor, model, overwrite=overwrite):
            completed += 1

    print(f"Done. Processed {completed}/{len(floors)} floor(s).")


def _parse_args():
    parser = argparse.ArgumentParser(description='Extract CosPlace global descriptors for all enabled floors.')
    parser.add_argument(
        '--floor',
        action='append',
        dest='floors',
        help='Process only the given floor id. Repeat for multiple floors.'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing global_descriptors_cosplace.npy files.'
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    extract_features(selected_floor_ids=args.floors, overwrite=args.overwrite)

