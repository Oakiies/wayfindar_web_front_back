import argparse
import shutil
from pathlib import Path

import numpy as np
import torch
from tqdm import tqdm

import build_topology as top
import localize_version2 as loc

BUILDING_CONFIG_PATH = Path('data/config/building.json')
LEGACY_CENTROID_CANDIDATES = [
    Path('result_IMG_5003_2/netvlad_centroids.npy')
]


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


def _resolve_shared_centroids_path(floors):
    for floor in floors:
        candidate = Path(floor['data_dir']) / 'netvlad_centroids.npy'
        if candidate.exists():
            return candidate

    for candidate in LEGACY_CENTROID_CANDIDATES:
        if candidate.exists():
            return candidate

    return None


def _ensure_floor_centroids(data_dir, shared_centroids_path):
    destination = data_dir / 'netvlad_centroids.npy'
    if destination.exists() or shared_centroids_path is None:
        return destination if destination.exists() else None

    shutil.copy(shared_centroids_path, destination)
    print(f"Copied NetVLAD centroids to {destination}")
    return destination


def _extract_floor_descriptors(floor, model, overwrite=False):
    floor_id = floor['id']
    data_dir = Path(floor['data_dir'])
    keyframes_dir = data_dir / 'keyframes'
    output_desc_path = data_dir / 'global_descriptors.npy'

    if not keyframes_dir.exists():
        print(f"Skipping {floor_id}: keyframes directory not found at {keyframes_dir}")
        return False

    if output_desc_path.exists() and not overwrite:
        print(f"Skipping {floor_id}: {output_desc_path.name} already exists")
        return True

    kf_dirs = sorted([d for d in keyframes_dir.iterdir() if d.is_dir()])
    print(f"Extracting NetVLAD features for {floor_id} ({len(kf_dirs)} keyframes)")

    descriptors_dict = {}
    for kf_dir in tqdm(kf_dirs, desc=f"NetVLAD {floor_id}"):
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

    shared_centroids_path = _resolve_shared_centroids_path(floors)
    if shared_centroids_path is None:
        print("Error: No NetVLAD centroids found.")
        print("Provide at least one existing netvlad_centroids.npy or keep result_IMG_5003_2/netvlad_centroids.npy.")
        return

    for floor in floors:
        _ensure_floor_centroids(Path(floor['data_dir']), shared_centroids_path)

    loc.NETVLAD_CENTROIDS_PATH = shared_centroids_path

    print(f"Using shared centroids from {shared_centroids_path}")
    print("Loading NetVLAD model...")
    model = loc.load_netvlad_model()
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = model.to(device)
    model.eval()

    completed = 0
    for floor in floors:
        if _extract_floor_descriptors(floor, model, overwrite=overwrite):
            completed += 1

    print(f"Done. Processed {completed}/{len(floors)} floor(s).")


def _parse_args():
    parser = argparse.ArgumentParser(description='Extract NetVLAD global descriptors for all enabled floors.')
    parser.add_argument(
        '--floor',
        action='append',
        dest='floors',
        help='Process only the given floor id. Repeat for multiple floors.'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing global_descriptors.npy files.'
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    extract_features(selected_floor_ids=args.floors, overwrite=args.overwrite)

