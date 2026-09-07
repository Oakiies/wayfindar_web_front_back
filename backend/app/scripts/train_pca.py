import argparse
import pickle
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA

import build_topology as top

BUILDING_CONFIG_PATH = Path('data/config/building.json')
TARGET_DIM = 4096


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


def _load_descriptor_matrix(floors):
    matrices = []
    loaded_floors = []

    for floor in floors:
        data_dir = Path(floor['data_dir'])
        input_desc_path = data_dir / 'global_descriptors.npy'

        if not input_desc_path.exists():
            print(f"Skipping {floor['id']}: {input_desc_path.name} not found")
            continue

        data_dict = np.load(input_desc_path, allow_pickle=True).item()
        if not data_dict:
            print(f"Skipping {floor['id']}: descriptor file is empty")
            continue

        descriptors = np.array(list(data_dict.values()))
        if descriptors.ndim != 2:
            print(f"Skipping {floor['id']}: invalid descriptor matrix shape {descriptors.shape}")
            continue

        matrices.append(descriptors)
        loaded_floors.append(floor)
        print(f"Loaded {descriptors.shape[0]} descriptors from {floor['id']} ({descriptors.shape[1]} dims)")

    if not matrices:
        return None, []

    return np.vstack(matrices), loaded_floors


def train_pca(selected_floor_ids=None, target_dim=TARGET_DIM):
    floors = _load_target_floors(selected_floor_ids)
    if not floors:
        print("No enabled floors found in building config.")
        return

    descriptors, loaded_floors = _load_descriptor_matrix(floors)
    if descriptors is None:
        print("Error: No descriptors available. Run extract_netvlad_features.py first.")
        return

    print(f"Combined descriptor matrix: {descriptors.shape}")

    actual_target = min(descriptors.shape[0], descriptors.shape[1], target_dim)
    if actual_target < 1:
        print("Error: Not enough descriptors to train PCA.")
        return

    if actual_target != target_dim:
        print(f"Adjusting PCA dimension from {target_dim} to {actual_target}")

    print(f"Training shared PCA (whitening=True) to {actual_target} dimensions...")
    pca = PCA(n_components=actual_target, whiten=True)
    pca.fit(descriptors)

    explained = float(np.sum(pca.explained_variance_ratio_))
    print(f"PCA explained variance ratio sum: {explained:.4f}")

    for floor in loaded_floors:
        output_pca_path = Path(floor['data_dir']) / 'pca_model.pkl'
        with open(output_pca_path, 'wb') as handle:
            pickle.dump(pca, handle)
        print(f"Saved shared PCA model to {output_pca_path}")

    print(f"Done. PCA written to {len(loaded_floors)} floor(s).")


def _parse_args():
    parser = argparse.ArgumentParser(description='Train a shared PCA model for NetVLAD descriptors across enabled floors.')
    parser.add_argument(
        '--floor',
        action='append',
        dest='floors',
        help='Train PCA using only the given floor id. Repeat for multiple floors.'
    )
    parser.add_argument(
        '--target-dim',
        type=int,
        default=TARGET_DIM,
        help=f'Target PCA dimension (default: {TARGET_DIM}).'
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    train_pca(selected_floor_ids=args.floors, target_dim=args.target_dim)

