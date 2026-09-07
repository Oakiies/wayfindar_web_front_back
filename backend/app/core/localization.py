"""
Core localization functions — pure functions with no module-level mutable state.
All configuration is passed explicitly as parameters.
"""
import cv2
import numpy as np
import torch
import torchvision.transforms as transforms
import time
import json
import os
import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from scipy.spatial.transform import Rotation
from tqdm import tqdm
from PIL import Image

from app.core.models import hloc_wrapper


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_camera_intrinsics(data_dir: Path) -> np.ndarray:
    camera_path = data_dir / 'camera.yaml'
    with open(camera_path, 'r') as f:
        lines = f.read().strip().split('\n')
    camera = {}
    for line in lines[1:]:
        if ':' in line:
            parts = line.split(':')
            camera[parts[0].strip()] = float(parts[1].strip())
    return np.array([
        [camera['Camera.fx'], 0, camera['Camera.cx']],
        [0, camera['Camera.fy'], camera['Camera.cy']],
        [0, 0, 1]
    ], dtype=np.float64)


def load_mappoints(data_dir: Path) -> dict:
    mappoints_raw = np.load(data_dir / 'mappoints.npy')
    return {int(row[0]): row[1:4] for row in mappoints_raw}


def load_keyframe_pose(pose_path: Path):
    if not pose_path.exists():
        return None, None, None
    with open(pose_path, 'r') as f:
        lines = f.readlines()
    matrix_lines = [l.strip() for l in lines if not l.startswith('#') and l.strip()]
    if len(matrix_lines) < 4:
        return None, None, None
    Tcw = np.array([[float(x) for x in line.split()] for line in matrix_lines[:4]])
    R = Tcw[:3, :3]
    t = Tcw[:3, 3]
    position = -R.T @ t
    return R, t, position


def _load_one_keyframe(kf_dir: Path) -> dict:
    """Load all files for a single keyframe directory. Called in parallel."""
    kf_id = int(kf_dir.name)
    desc   = np.load(kf_dir / 'descriptors.npy')
    kpts   = np.load(kf_dir / 'keypoints.npy')
    mp_ids = np.load(kf_dir / 'mappoint_ids.npy')
    score_path = kf_dir / 'keypoint_scores.npy'
    kp_scores = np.load(score_path).astype(np.float32) if score_path.exists() else np.ones(len(kpts), dtype=np.float32)
    R, t, position = load_keyframe_pose(kf_dir / 'pose.txt')
    global_desc = np.mean(desc, axis=0) if len(desc) > 0 else np.zeros(desc.shape[1] if len(desc.shape) > 1 else 256, dtype=np.float32)
    return {
        'kf_id': kf_id,
        'desc': desc,
        'kpts': kpts,
        'mp_ids': mp_ids,
        'kp_scores': kp_scores,
        'pose': {'R': R, 't': t, 'position': position},
        'global_desc': global_desc,
    }


def load_keyframe_database(keyframes_dir: Path, global_desc_path: Path | None = None) -> dict:
    """
    Load keyframe database.
    global_desc_path: required path to the selected retrieval descriptor file.
    There is no mean-ORB descriptor fallback: the active retrieval backend must
    be explicit and compatible with the database.
    Keyframes are loaded in parallel using threads (np.load releases the GIL during disk I/O).
    """
    if global_desc_path is None or not global_desc_path.exists():
        raise FileNotFoundError(
            f"Retrieval descriptor file is required but was not found: {global_desc_path}. "
            "Mean-ORB fallback is disabled."
        )
    keyframe_dirs = sorted([d for d in keyframes_dir.iterdir() if d.is_dir()])
    database: dict = {
        'keyframe_ids': [],
        'descriptors': [],
        'keypoints': [],
        'mappoint_ids': [],
        'keypoint_scores': [],
        'global_descriptors': [],
        'poses': []
    }

    n = len(keyframe_dirs)
    print(f"Loading {n} keyframes (parallel)...")
    workers = min(8, os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        loaded = list(tqdm(executor.map(_load_one_keyframe, keyframe_dirs), total=n))

    for r in loaded:
        database['keyframe_ids'].append(r['kf_id'])
        database['descriptors'].append(r['desc'])
        database['keypoints'].append(r['kpts'])
        database['mappoint_ids'].append(r['mp_ids'])
        database['keypoint_scores'].append(r['kp_scores'])
        database['poses'].append(r['pose'])
        database['global_descriptors'].append(r['global_desc'])

    name_lower = global_desc_path.name.lower()
    source_name = next(
        (label for token, label in (
            ('cosplace', 'CosPlace'),
            ('megaloc', 'MegaLoc'),
            ('netvlad', 'NetVLAD'),
        ) if token in name_lower),
        'selected retrieval',
    )
    print(f"Loading {source_name} descriptors from {global_desc_path}")
    retrieval_descs = np.load(global_desc_path, allow_pickle=True).item()
    valid_count = 0
    for i, kf_id in enumerate(database['keyframe_ids']):
        kf_name = f"{kf_id:04d}"
        if kf_name in retrieval_descs:
            database['global_descriptors'][i] = retrieval_descs[kf_name]
            valid_count += 1
    if valid_count != len(database['keyframe_ids']):
        raise RuntimeError(
            f"Only {valid_count}/{len(database['keyframe_ids'])} keyframes have "
            f"{source_name} descriptors in {global_desc_path}; descriptor fallback is disabled."
        )
    print(f"   Mapped {valid_count}/{len(database['keyframe_ids'])} {source_name} descriptors")

    valid_poses = sum(1 for p in database['poses'] if p['position'] is not None)
    print(f"   Loaded {valid_poses}/{len(database['keyframe_ids'])} keyframe poses for fallback")
    database['global_descriptors'] = np.array(database['global_descriptors'], dtype=np.float32)
    print(f"Loaded {len(database['keyframe_ids'])} keyframes")
    return database


def load_pca_model(path: Path):
    if not path.exists():
        print(f"PCA model not found at {path}")
        return None
    with open(path, 'rb') as f:
        pca = pickle.load(f)
    print(f"Loaded PCA model: {pca.n_components_} components")
    return pca


def apply_pca(descriptors: np.ndarray, pca) -> np.ndarray:
    if pca is None:
        return descriptors
    transformed = pca.transform(descriptors)
    norms = np.linalg.norm(transformed, axis=1, keepdims=True)
    return transformed / (norms + 1e-7)


# ---------------------------------------------------------------------------
# Retrieval model loading
# ---------------------------------------------------------------------------

def load_netvlad_model(netvlad_centroids_path: Path):
    from app.core.models import netvlad as netvlad_module
    print("Loading NetVLAD model...")
    model = netvlad_module.get_model(pretrained=True)
    if netvlad_centroids_path.exists():
        centroids = np.load(netvlad_centroids_path)
        model.net_vlad.centroids = torch.nn.Parameter(torch.from_numpy(centroids).float())
        model.net_vlad._init_params()
        print(f"Loaded NetVLAD centroids from {netvlad_centroids_path}")
    else:
        print("Warning: NetVLAD centroids not found! Model may not work correctly.")
    model._retrieval_backend = 'netvlad'
    model._input_size = (480, 640)
    model.eval()
    return model


def _load_checkpoint(ckpt_path: Path, label: str) -> 'torch.nn.Module | None':
    """Try TorchScript then nn.Module loading; return None on failure."""
    try:
        model = torch.jit.load(str(ckpt_path), map_location='cpu')
        print(f"Loaded {label} TorchScript from {ckpt_path}")
        return model
    except Exception:
        pass
    try:
        payload = torch.load(str(ckpt_path), map_location='cpu')
        if isinstance(payload, torch.nn.Module):
            print(f"Loaded {label} nn.Module from {ckpt_path}")
            return payload
    except Exception:
        pass
    return None


def load_cosplace_model(
    weights_path: str = '',
    backbone: str = 'ResNet50',
    output_dim: int = 2048,
) -> torch.nn.Module:
    print(f"Loading CosPlace model (backbone={backbone}, dim={output_dim})...")
    errors = []
    model = None

    # 1. Explicit weights path from config (overrides env var)
    for src in filter(None, [weights_path, os.getenv('COSPLACE_WEIGHTS_PATH', '').strip()]):
        p = Path(src)
        if p.exists():
            model = _load_checkpoint(p, 'CosPlace')
            if model is not None:
                break
            errors.append(f"Failed to load checkpoint: {p}")

    # 2. torch.hub fallback — try requested backbone/dim first, then fallbacks
    if model is None:
        fc_key = 'fc_output_dim'
        hub_attempts = [
            ('get_trained_model', {'backbone': backbone, fc_key: output_dim}),
            ('get_trained_model', {'backbone': 'ResNet50', fc_key: 2048}),
            ('get_trained_model', {'backbone': 'ResNet18', fc_key: 512}),
            ('cosplace_r50_2048', {'pretrained': True}),
            ('cosplace_r18_512',  {'pretrained': True}),
        ]
        for fn_name, kwargs in hub_attempts:
            try:
                model = torch.hub.load('gmberton/cosplace', fn_name, **kwargs)
                print(f"Loaded CosPlace via torch.hub: {fn_name}({kwargs})")
                break
            except Exception as exc:
                errors.append(f"torch.hub {fn_name} failed: {exc}")

    if model is None:
        raise RuntimeError('Unable to load CosPlace model. ' + ' | '.join(errors[:4]))

    model._retrieval_backend = 'cosplace'
    model._input_size = (320, 320)
    model.eval()
    return model


def load_megaloc_model() -> torch.nn.Module:
    """
    Load the pretrained MegaLoc model (DINOv2 + SALAD aggregation, 8448-dim output).

    Weights are downloaded automatically from HuggingFace on first call
    and cached in ~/.cache/huggingface/.

    Requires: pip install huggingface_hub safetensors
    """
    print("Loading MegaLoc model (DINOv2 + SALAD, 8448-dim)...")
    try:
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        from megaloc.megaloc_model import MegaLoc
    except ImportError as exc:
        raise RuntimeError(
            "MegaLoc requires 'huggingface_hub' and 'safetensors'. "
            "Run: pip install huggingface_hub safetensors"
        ) from exc

    model = MegaLoc()
    weights_path = hf_hub_download(repo_id="gberton/MegaLoc", filename="model.safetensors")
    state_dict = load_file(weights_path)
    model.load_state_dict(state_dict)
    print("MegaLoc weights loaded.")

    model._retrieval_backend = 'megaloc'
    model._input_size = (518, 518)  # DINOv2 training size (multiples of 14)
    model.eval()
    return model


def load_global_retrieval_model(
    retrieval_mode: str,
    data_dir: 'Path | None' = None,
    backend_cfg: 'dict | None' = None,
    netvlad_centroids_path: 'Path | None' = None,
) -> torch.nn.Module:
    """
    Dispatch to the correct backend via the retrieval registry.
    Falls back to the old positional-arg behaviour when called without backend_cfg
    so existing call-sites don't break.
    """
    import app.core.retrieval as _retrieval
    mode = (retrieval_mode or '').strip().lower()
    if not mode:
        raise ValueError("retrieval_mode is required; automatic NetVLAD fallback is disabled.")

    if backend_cfg is not None and data_dir is not None:
        backend = _retrieval.get_backend(mode)
        return backend.load_model(data_dir, backend_cfg)

    # Legacy path (called without cfg — e.g. from extraction scripts)
    if mode == 'cosplace':
        return load_cosplace_model()
    if mode == 'megaloc':
        return load_megaloc_model()
    if mode == 'netvlad':
        return load_netvlad_model(netvlad_centroids_path or Path('netvlad_centroids.npy'))
    raise ValueError(f"Unknown retrieval mode {mode!r}; no NetVLAD fallback is available.")


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _global_transform_for_model(model) -> transforms.Compose:
    backend = getattr(model, '_retrieval_backend', 'netvlad')
    input_size = getattr(model, '_input_size', (320, 320) if backend == 'cosplace' else (480, 640))
    return transforms.Compose([
        transforms.Resize(input_size),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])


def extract_global_features(image_input, model) -> np.ndarray:
    transform = _global_transform_for_model(model)
    if isinstance(image_input, (str, Path)):
        img = Image.open(image_input).convert('RGB')
    elif isinstance(image_input, np.ndarray):
        img = Image.fromarray(cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB))
    else:
        raise ValueError("Invalid input for extract_global_features")
    device = next(model.parameters()).device
    img_tensor = transform(img).unsqueeze(0).to(device)
    with torch.no_grad():
        desc = model(img_tensor)
        if isinstance(desc, (tuple, list)):
            desc = desc[0]
        if not torch.is_tensor(desc):
            desc = torch.as_tensor(desc)
        if desc.ndim > 2:
            desc = torch.flatten(desc, 1)
        if desc.ndim == 1:
            desc = desc.unsqueeze(0)
        desc = desc.detach().cpu().numpy().reshape(-1).astype(np.float32)
    norm = np.linalg.norm(desc)
    if norm > 1e-7:
        desc = desc / norm
    return desc


def get_reference_image_size_from_intrinsics(K: np.ndarray | None):
    if K is None:
        return None
    try:
        width = int(round(float(K[0, 2]) * 2.0))
        height = int(round(float(K[1, 2]) * 2.0))
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def resize_query_image(image: np.ndarray, target_size) -> np.ndarray:
    if image is None or target_size is None:
        return image
    target_w, target_h = int(target_size[0]), int(target_size[1])
    if target_w <= 0 or target_h <= 0:
        return image
    src_h, src_w = image.shape[:2]
    if src_w == target_w and src_h == target_h:
        return image
    is_downscale = target_w < src_w or target_h < src_h
    interp = cv2.INTER_AREA if is_downscale else cv2.INTER_LINEAR
    return cv2.resize(image, (target_w, target_h), interpolation=interp)


def extract_features(image_input, superpoint_extractor=None, target_size=None, use_superpoint: bool = True):
    """Extract local features. Returns (kpts, desc, scores, gray_img)."""
    if isinstance(image_input, (str, Path)):
        img = cv2.imread(str(image_input), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Cannot load image: {image_input}")
    elif isinstance(image_input, np.ndarray):
        img = cv2.cvtColor(image_input, cv2.COLOR_BGR2GRAY) if len(image_input.shape) == 3 else image_input
    else:
        raise ValueError("Invalid input type for extract_features")

    img = resize_query_image(img, target_size)

    if use_superpoint and superpoint_extractor is not None:
        kpts, descriptors, scores = superpoint_extractor.extract(img)
        if descriptors is None or len(kpts) == 0:
            return None, None, None, img
        return kpts, descriptors, scores, img
    else:
        orb = cv2.ORB_create(nfeatures=2000)
        keypoints, descriptors = orb.detectAndCompute(img, None)
        if descriptors is None:
            return None, None, None, img
        kpts = np.array([kp.pt for kp in keypoints], dtype=np.float32)
        scores = np.ones(len(kpts), dtype=np.float32)
        return kpts, descriptors.astype(np.uint8), scores, img


# ---------------------------------------------------------------------------
# Retrieval / re-ranking
# ---------------------------------------------------------------------------

def _mappoint_id_set_from_array(mp_ids) -> set:
    if mp_ids is None:
        return set()
    arr = np.asarray(mp_ids).reshape(-1)
    if arr.size == 0:
        return set()
    valid = arr[arr >= 0]
    return set(int(v) for v in np.unique(valid)) if valid.size > 0 else set()


def _jaccard_set_overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _paper_style_covisibility_rerank(sim_scores: np.ndarray, database: dict, top_k: int = 15) -> list:
    total = int(sim_scores.shape[0])
    if total <= 0:
        return []
    g1_size = min(max(top_k, 8), total)
    expanded_size = min(max(g1_size * 3, g1_size + 6), total)
    neighborhood_size = min(5, max(1, expanded_size - 1))

    sorted_indices = np.argsort(sim_scores)[::-1]
    g1_indices = [int(idx) for idx in sorted_indices[:g1_size]]
    expanded_indices = [int(idx) for idx in sorted_indices[:expanded_size]]
    g1_index_set = set(g1_indices)

    candidate_sets = {
        idx: _mappoint_id_set_from_array(database['mappoint_ids'][idx])
        for idx in expanded_indices
    }

    reranked = []
    for idx in g1_indices:
        base_score = float(sim_scores[idx])
        anchor_set = candidate_sets.get(idx, set())
        neighbor_candidates = []
        for other_idx in expanded_indices:
            if other_idx == idx:
                continue
            overlap = _jaccard_set_overlap(anchor_set, candidate_sets.get(other_idx, set()))
            neighbor_candidates.append((overlap, float(sim_scores[other_idx]), other_idx))
        neighbor_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        neighborhood = [item[2] for item in neighbor_candidates[:neighborhood_size] if item[0] > 0.0]
        if not neighborhood:
            neighborhood = [item[2] for item in neighbor_candidates[:neighborhood_size]]
        neighborhood_set = set(neighborhood)
        neighborhood_jaccard = _jaccard_set_overlap(neighborhood_set, g1_index_set)
        local_covisibility = float(sum(item[0] for item in neighbor_candidates[:len(neighborhood)]) / len(neighborhood)) if neighborhood else 0.0
        score = base_score + (0.06 * neighborhood_jaccard) + (0.02 * local_covisibility)
        reranked.append({
            'index': idx,
            'keyframe_id': database['keyframe_ids'][idx],
            'score': score,
            'raw_score': base_score,
            'covisibility_score': neighborhood_jaccard,
            'neighborhood_score': neighborhood_jaccard,
            'local_covisibility': local_covisibility,
            'neighbor_keyframes': [database['keyframe_ids'][n_idx] for n_idx in neighborhood]
        })
    reranked.sort(key=lambda item: item['score'], reverse=True)
    return reranked[:top_k]


def image_retrieval(query_desc: np.ndarray, database: dict, top_k: int = 15, use_netvlad: bool = False) -> list:
    if use_netvlad:
        db_descs = database['global_descriptors']
        sim_scores = np.dot(db_descs, query_desc)
        return _paper_style_covisibility_rerank(sim_scores, database, top_k=top_k)
    else:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        scores = []
        for i in range(len(database['descriptors'])):
            kf_desc = database['descriptors'][i].astype(np.uint8)
            if kf_desc is None or len(kf_desc) == 0:
                scores.append((i, 0))
                continue
            try:
                matches = bf.knnMatch(query_desc, kf_desc, k=2)
                good = [m for pair in matches if len(pair) == 2 for m, n in [pair] if m.distance < 0.75 * n.distance]
                scores.append((i, len(good)))
            except Exception:
                scores.append((i, 0))
        scores.sort(key=lambda item: item[1], reverse=True)
        return [{
            'index': idx,
            'keyframe_id': database['keyframe_ids'][idx],
            'score': float(score),
            'raw_score': float(score),
            'covisibility_score': 0.0
        } for idx, score in scores[:top_k]]


# ---------------------------------------------------------------------------
# 2D-3D matching
# ---------------------------------------------------------------------------

def match_2d_3d(
    query_kpts, query_desc, query_scores,
    kf_kpts, kf_desc, kf_scores, kf_mp_ids, mappoint_dict,
    superglue_matcher=None,
    use_superglue: bool = True,
):
    if query_desc is None or kf_desc is None:
        return None, None
    if len(query_desc) < 4 or len(kf_desc) < 4:
        return None, None

    if use_superglue and superglue_matcher is not None:
        return hloc_wrapper.match_2d_3d_superglue(
            query_kpts, query_desc, query_scores,
            kf_kpts, kf_desc, kf_scores,
            kf_mp_ids, mappoint_dict,
            superglue_matcher,
            min_matches=4
        )

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    try:
        matches = bf.knnMatch(query_desc.astype(np.uint8), kf_desc.astype(np.uint8), k=2)
    except Exception:
        return None, None

    good_matches = [m for pair in matches if len(pair) == 2 for m, n in [pair] if m.distance < 0.85 * n.distance]
    if len(good_matches) < 4:
        return None, None

    points_2d, points_3d = [], []
    for m in good_matches:
        mp_id = int(kf_mp_ids[m.trainIdx])
        if mp_id > 0 and mp_id in mappoint_dict:
            points_2d.append(query_kpts[m.queryIdx])
            points_3d.append(mappoint_dict[mp_id])

    if len(points_2d) < 4:
        return None, None
    return np.array(points_2d, dtype=np.float32), np.array(points_3d, dtype=np.float32)


# ---------------------------------------------------------------------------
# PnP / pose
# ---------------------------------------------------------------------------

def transform_yaw(theta: float, H_matrix=None) -> float:
    if H_matrix is None:
        return theta
    h_rot = np.degrees(np.arctan2(H_matrix[1, 0], H_matrix[0, 0]))
    return theta + h_rot


def get_yaw(R: np.ndarray) -> float:
    # R is Tcw (world -> camera). Camera forward in world = R^T @ [0,0,1],
    # i.e. row 2 of R, not column 2 -- atan2(R[0,2], R[2,2]) was reading the
    # world Z-axis expressed in camera frame and returned the negated angle.
    # Verified against map keyframes/pose.txt travel direction (see
    # poc_cross_camera/validate_yaw_formula.py): median error dropped from
    # ~8-13 deg to ~3-4 deg at well-powered motion thresholds.
    return np.degrees(np.arctan2(R[2, 0], R[2, 2]))


def solve_pnp_ransac(points_2d, points_3d, K, reproj_threshold: float = 8.0, iterations: int = 1000, min_inliers: int = 8):
    if points_2d is None or points_3d is None or len(points_2d) < 4:
        return False, None, None, None
    dist_coeffs = np.zeros(4)
    success, rvec, tvec, inliers = cv2.solvePnPRansac(
        objectPoints=points_3d,
        imagePoints=points_2d,
        cameraMatrix=K,
        distCoeffs=dist_coeffs,
        reprojectionError=reproj_threshold,
        iterationsCount=iterations,
        flags=cv2.SOLVEPNP_P3P
    )
    if not success or inliers is None or len(inliers) < min_inliers:
        return False, None, None, None
    R, _ = cv2.Rodrigues(rvec)
    return True, R, tvec.flatten(), inliers


def get_camera_position(R, t):
    if R is None or t is None:
        return None
    return -np.array(R).T @ np.array(t)


def get_6dof_pose(R, t) -> dict:
    position = get_camera_position(R, t)
    if position is None:
        return {'position': None, 'quaternion': None, 'euler_degrees': None, 'R': R, 't': t}
    rotation = Rotation.from_matrix(np.array(R).T)
    return {
        'position': position,
        'quaternion': rotation.as_quat(),
        'euler_degrees': rotation.as_euler('xyz', degrees=True),
        'R': R,
        't': t
    }


def compute_pnp_quality(points_2d, points_3d, inliers, R, t, K):
    if any(v is None for v in [points_2d, points_3d, inliers, R, t, K]):
        return 0.0, float('inf')
    total_matches = int(len(points_2d))
    inlier_idx = np.asarray(inliers).reshape(-1)
    inlier_count = int(len(inlier_idx))
    if total_matches <= 0 or inlier_count <= 0:
        return 0.0, float('inf')
    inlier_ratio = float(inlier_count) / float(max(total_matches, 1))
    try:
        pts3d = np.asarray(points_3d, dtype=np.float64)[inlier_idx]
        pts2d = np.asarray(points_2d, dtype=np.float64)[inlier_idx]
        rvec, _ = cv2.Rodrigues(np.asarray(R, dtype=np.float64))
        projected, _ = cv2.projectPoints(pts3d, rvec, np.asarray(t, dtype=np.float64).reshape(3, 1), np.asarray(K, dtype=np.float64), np.zeros(4, dtype=np.float64))
        errors = np.linalg.norm(projected.reshape(-1, 2) - pts2d, axis=1)
        median_error = float(np.median(errors)) if errors.size > 0 else float('inf')
    except Exception:
        median_error = float('inf')
    return inlier_ratio, median_error


def project_to_floor_plan(position, H_matrix=None, floor_config=None):
    if position is None:
        return None
    if not isinstance(position, np.ndarray):
        position = np.array(position)
    if floor_config is not None:
        floor_pt = np.array(floor_config['traj_center'])
        v1 = np.array(floor_config['floor_v1'])
        v2 = np.array(floor_config['floor_v2'])
        vec = position - floor_pt
        x = np.dot(vec, v1)
        y = np.dot(vec, v2)
    else:
        x = position[0]
        y = position[2]
    floor_pos = np.array([x, y, 1])
    if H_matrix is not None:
        pixel = H_matrix @ floor_pos
        pixel = pixel[:2] / pixel[2]
        return pixel
    return floor_pos[:2]


def is_pose_valid(pose: dict, floor_plan_size=None, H_matrix=None, floor_config=None) -> bool:
    if pose is None:
        return False
    pos = pose['position']
    if not np.all(np.isfinite(pos)):
        return False
    if np.any(np.abs(pos) > 10000.0):
        print(f"    [Sanity] Rejecting pose: astronomical coordinates {pos}")
        return False
    if floor_plan_size is not None:
        h, w = floor_plan_size
        pixel = project_to_floor_plan(pos, H_matrix, floor_config)
        if pixel is None:
            return False
        x, y = pixel
        margin = 50
        if not (-margin <= x < w + margin and -margin <= y < h + margin):
            print(f"    [Sanity] Rejecting pose: projected ({x:.1f}, {y:.1f}) outside map ({w}x{h})")
            return False
    return True


# ---------------------------------------------------------------------------
# Main localization pipeline
# ---------------------------------------------------------------------------

def localize_image(
    image_path,
    database: dict,
    mappoint_dict: dict,
    K: np.ndarray,
    pca_model=None,
    top_k: int = 40,
    reproj_threshold: float = 8.0,
    min_inliers: int = 10,
    min_inlier_ratio: float = 0.15,
    max_median_reproj_error: float = 9.0,
    floor_config=None,
    netvlad_model=None,
    superpoint_extractor=None,
    superglue_matcher=None,
    verbose: bool = True,
    floor_plan_size=None,
    H_matrix=None,
    debug_mode: bool = False,
    allow_orb_fallback: bool = True,
    allow_keyframe_fallback: bool = True,
    use_superpoint: bool = True,
    use_superglue: bool = True,
    calibration_callback=None,
) -> dict:
    """Full localization pipeline: Retrieval → Matching → PnP → Pose."""
    result = {
        'success': False,
        'image_path': str(image_path),
        'pose': None,
        'matched_keyframe': None,
        'num_inliers': 0,
        'num_matches': 0,
        'inlier_ratio': 0.0,
        'median_reproj_error': None,
        'method': None,
        'timing': {
            'feature_extract': 0.0, 'global_descriptor': 0.0, 'pca': 0.0,
            'retrieval_initial': 0.0, 'retrieval_fallback': 0.0,
            'matching': 0.0, 'pnp': 0.0, 'total': 0.0,
            'candidate_count': 0, 'fallback_candidate_count': 0, 'fallback_used': False
        }
    }
    timing = result['timing']
    start_time = time.time()

    reference_query_size = get_reference_image_size_from_intrinsics(K)
    feature_start = time.time()
    query_kpts, query_desc, query_scores, query_img = extract_features(
        image_path, superpoint_extractor, target_size=reference_query_size, use_superpoint=use_superpoint
    )
    timing['feature_extract'] = time.time() - feature_start
    if query_desc is None:
        return result

    if netvlad_model is not None:
        global_desc_start = time.time()
        query_global_desc = extract_global_features(image_path, netvlad_model)
        timing['global_descriptor'] = time.time() - global_desc_start
        if pca_model is not None:
            pca_start = time.time()
            query_global_desc = apply_pca(query_global_desc.reshape(1, -1), pca_model).flatten()
            timing['pca'] = time.time() - pca_start
        retrieval_start = time.time()
        retrieved = image_retrieval(query_global_desc, database, top_k=top_k, use_netvlad=True)
        timing['retrieval_initial'] = time.time() - retrieval_start
    else:
        retrieval_start = time.time()
        retrieved = image_retrieval(query_desc, database, top_k=top_k, use_netvlad=False)
        timing['retrieval_initial'] = time.time() - retrieval_start

    if debug_mode:
        result['debug_info'] = {
            'retrieved_keyframes': [
                {'index': r['index'], 'keyframe_id': r['keyframe_id'], 'score': float(r.get('score', 0))}
                for r in retrieved
            ],
            'query_keypoints': query_kpts.tolist() if query_kpts is not None else []
        }

    calibration_candidate = None

    def process_candidates(candidates, current_best_inliers=0, current_best_pose=None,
                           current_best_kf_id=None, current_best_matches=0, current_best_kf_idx=None,
                           current_best_retrieval_score=0, current_best_inlier_ratio=0.0,
                           current_best_median_reproj_error=float('inf'), counter_key='candidate_count'):
        nonlocal calibration_candidate
        best_pnp = {
            'inliers': current_best_inliers, 'pose': current_best_pose, 'kf_id': current_best_kf_id,
            'matches': current_best_matches, 'kf_idx': current_best_kf_idx,
            'retrieval_score': current_best_retrieval_score, 'inlier_ratio': current_best_inlier_ratio,
            'median_reproj_error': current_best_median_reproj_error,
            'quality_score': float(current_best_inliers)
        }
        for candidate in candidates:
            timing[counter_key] += 1
            kf_idx = candidate['index']
            kf_id = candidate['keyframe_id']
            retrieval_score = candidate.get('score', 0)
            if retrieval_score > best_pnp['retrieval_score']:
                best_pnp['retrieval_score'] = retrieval_score
                best_pnp['kf_idx'] = kf_idx

            kf_kpts = database['keypoints'][kf_idx]
            kf_desc = database['descriptors'][kf_idx]
            kf_mp_ids = database['mappoint_ids'][kf_idx]
            kf_scores = database['keypoint_scores'][kf_idx] if kf_idx < len(database.get('keypoint_scores', [])) else np.ones(len(kf_kpts), dtype=np.float32)

            match_start = time.time()
            points_2d, points_3d = match_2d_3d(
                query_kpts, query_desc, query_scores,
                kf_kpts, kf_desc, kf_scores, kf_mp_ids, mappoint_dict,
                superglue_matcher, use_superglue=use_superglue
            )
            timing['matching'] += time.time() - match_start
            if points_2d is None:
                continue

            # Keep the richest correspondence set from this request. It is
            # submitted once after all retrieval candidates are evaluated, so
            # several keyframes from one image cannot masquerade as temporal
            # multi-frame calibration evidence.
            if calibration_candidate is None or len(points_2d) > len(calibration_candidate[0]):
                calibration_candidate = (points_2d, points_3d)

            pnp_start = time.time()
            success, R, t, inliers = solve_pnp_ransac(points_2d, points_3d, K, reproj_threshold=reproj_threshold, min_inliers=min_inliers)
            timing['pnp'] += time.time() - pnp_start

            if success:
                inlier_ratio, median_reproj_error = compute_pnp_quality(points_2d, points_3d, inliers, R, t, K)
                if inlier_ratio < float(min_inlier_ratio):
                    continue
                if not np.isfinite(median_reproj_error) or median_reproj_error > float(max_median_reproj_error):
                    continue
                inlier_count = int(len(inliers))
                quality_score = float(inlier_count) + (inlier_ratio * 40.0) - (median_reproj_error * 2.0)
                if quality_score <= best_pnp['quality_score']:
                    continue
                candidate_pose = get_6dof_pose(R, t)
                if is_pose_valid(candidate_pose, floor_plan_size, H_matrix, floor_config):
                    candidate_pose['theta'] = transform_yaw(get_yaw(R), H_matrix)
                    best_pnp.update({
                        'inliers': inlier_count, 'pose': candidate_pose, 'kf_id': kf_id,
                        'matches': len(points_2d), 'kf_idx': kf_idx,
                        'inlier_ratio': float(inlier_ratio), 'median_reproj_error': float(median_reproj_error),
                        'quality_score': float(quality_score)
                    })
        return best_pnp

    best_pnp_result = process_candidates(retrieved)

    if allow_orb_fallback and best_pnp_result['inliers'] < min_inliers:
        timing['fallback_used'] = True
        fallback_retrieval_start = time.time()
        orb_retrieved = image_retrieval(query_desc, database, top_k=top_k, use_netvlad=False)
        timing['retrieval_fallback'] = time.time() - fallback_retrieval_start
        best_pnp_result = process_candidates(
            orb_retrieved,
            current_best_inliers=best_pnp_result['inliers'], current_best_pose=best_pnp_result['pose'],
            current_best_kf_id=best_pnp_result['kf_id'], current_best_matches=best_pnp_result['matches'],
            current_best_kf_idx=best_pnp_result['kf_idx'], current_best_retrieval_score=0,
            current_best_inlier_ratio=best_pnp_result['inlier_ratio'],
            current_best_median_reproj_error=best_pnp_result['median_reproj_error'],
            counter_key='fallback_candidate_count'
        )

    best_pose = best_pnp_result['pose']
    best_inliers = best_pnp_result['inliers']
    best_kf_id = best_pnp_result['kf_id']
    best_matches = best_pnp_result['matches']
    best_inlier_ratio = float(best_pnp_result.get('inlier_ratio', 0.0) or 0.0)
    best_median_reproj_error = best_pnp_result.get('median_reproj_error', None)

    # Image-only self-calibration is best-effort and asynchronous. The callback
    # must never delay or change this localization attempt.
    if calibration_callback is not None and calibration_candidate is not None:
        try:
            calibration_callback(*calibration_candidate)
        except Exception:
            pass

    timing['total'] = time.time() - start_time
    result['total_time'] = timing['total']

    if best_pose is not None and best_inliers >= min_inliers:
        result.update({
            'success': True, 'pose': best_pose, 'matched_keyframe': best_kf_id,
            'num_inliers': best_inliers, 'num_matches': best_matches,
            'inlier_ratio': best_inlier_ratio, 'median_reproj_error': best_median_reproj_error,
            'method': 'PnP'
        })
        if debug_mode and 'debug_info' in result:
            result['debug_info'].update({
                'num_matches': best_matches, 'num_inliers': best_inliers,
                'inlier_ratio': best_inlier_ratio, 'median_reproj_error': best_median_reproj_error,
                'timing': timing.copy()
            })
    elif allow_keyframe_fallback and len(retrieved) > 0:
        best_candidate = retrieved[0]
        fallback_idx = best_candidate['index']
        fallback_pose = database['poses'][fallback_idx]
        if fallback_pose['position'] is not None:
            fallback_pose_full = get_6dof_pose(fallback_pose['R'], fallback_pose['t'])
            fallback_pose_full['theta'] = transform_yaw(get_yaw(fallback_pose['R']), H_matrix)
            result.update({
                'success': True, 'pose': fallback_pose_full,
                'matched_keyframe': best_candidate['keyframe_id'],
                'num_inliers': 0, 'num_matches': 0, 'method': 'KEYFRAME_FALLBACK'
            })
    else:
        result.update({
            'success': False, 'pose': None, 'matched_keyframe': None,
            'num_inliers': best_inliers, 'num_matches': best_matches,
            'inlier_ratio': best_inlier_ratio, 'median_reproj_error': best_median_reproj_error
        })

    return result
