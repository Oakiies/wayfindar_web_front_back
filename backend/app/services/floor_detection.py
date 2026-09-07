"""Floor detection via NetVLAD/CosPlace scoring across all enabled floors."""
import time
import threading
from pathlib import Path
import numpy as np
import cv2
from app.services.state import state
from app.services.floor_service import get_floor_config, get_keyframes_dir
from app.services.localizer_service import get_or_create_localizer
import app.core.localization as loc
import app.config as config
import app.localization_config as lc
from app.core.retrieval import get_backend


# Floor ranking must not construct a full Localizer for every floor: that loads
# all local keypoints/descriptors and can take tens of seconds per cold floor.
# The global descriptor files are small enough to cache independently, then a
# full Localizer is built only for the best hypothesis.
_GLOBAL_DESCRIPTOR_CACHE = {}
_GLOBAL_DESCRIPTOR_CACHE_LOCK = threading.RLock()


def _load_global_descriptor_index(floor_id: str):
    cache_key = (state.retrieval_mode, floor_id)
    cached = _GLOBAL_DESCRIPTOR_CACHE.get(cache_key)
    if cached is not None:
        return cached

    floor_config = get_floor_config(floor_id)
    backend = get_backend(state.retrieval_mode)
    backend_config = lc.BACKEND_CONFIGS.get(state.retrieval_mode, {})
    descriptor_path = Path(floor_config['data_dir']) / backend.descriptor_file(backend_config)
    if not descriptor_path.exists():
        return None

    raw_descriptors = np.load(descriptor_path, allow_pickle=True).item()
    keyframes_dir = get_keyframes_dir(
        floor_id,
        matching_mode='superpoint' if config.ACCEL_MODE else config.MATCHING_MODE,
    )
    keyframe_ids = []
    descriptors = []
    for keyframe_dir in sorted(keyframes_dir.iterdir()):
        if not keyframe_dir.is_dir():
            continue
        try:
            keyframe_id = int(keyframe_dir.name)
        except ValueError:
            continue
        descriptor = raw_descriptors.get(f'{keyframe_id:04d}', raw_descriptors.get(keyframe_id))
        if descriptor is None:
            continue
        keyframe_ids.append(keyframe_id)
        descriptors.append(np.asarray(descriptor, dtype=np.float32).reshape(-1))
    if not descriptors:
        return None

    database_descriptors = np.asarray(descriptors, dtype=np.float32)
    pca_model = None
    pca_filename = backend.pca_file(backend_config)
    if pca_filename:
        pca_path = Path(floor_config['data_dir']) / pca_filename
        if pca_path.exists():
            pca_model = loc.load_pca_model(pca_path)
            if pca_model is not None:
                database_descriptors = loc.apply_pca(database_descriptors, pca_model)

    record = (keyframe_ids, database_descriptors, pca_model)
    with _GLOBAL_DESCRIPTOR_CACHE_LOCK:
        return _GLOBAL_DESCRIPTOR_CACHE.setdefault(cache_key, record)


def _rank_floor_with_global_descriptors(frame) -> list:
    warm_localizer = state.localizer
    if warm_localizer is None or warm_localizer.netvlad_model is None:
        return []

    rankings = []
    query_desc_cache = None
    for floor_id in sorted(state.floor_configs.keys(), key=lambda item: state.floor_configs[item].get('order', 0)):
        try:
            index = _load_global_descriptor_index(floor_id)
            if index is None:
                continue
            keyframe_ids, db_descs, pca_model = index
            if query_desc_cache is None:
                query_desc_cache = loc.extract_global_features(frame, warm_localizer.netvlad_model).reshape(1, -1)
            query_desc = query_desc_cache
            if pca_model is not None:
                query_desc = loc.apply_pca(query_desc, pca_model)
            else:
                norms = np.linalg.norm(query_desc, axis=1, keepdims=True)
                query_desc = query_desc / (norms + 1e-7)
            sim_scores = np.dot(db_descs, query_desc.flatten())
            if sim_scores.size == 0:
                continue
            top_k = min(5, sim_scores.shape[0])
            top_indices = np.argsort(sim_scores)[::-1][:top_k]
            raw_score = float(sim_scores[top_indices[0]])
            rankings.append({
                'floor_id': floor_id,
                'score': raw_score,
                'raw_score': raw_score,
                'covisibility_score': 0.0,
                'top_keyframe_ids': [keyframe_ids[idx] for idx in top_indices],
            })
        except Exception as exc:
            print(f"WARN: lightweight floor ranking failed for {floor_id}: {exc}")
    rankings.sort(key=lambda item: item['score'], reverse=True)
    return rankings


def _get_mappoint_id_sets_for_localizer(floor_localizer) -> list:
    cached = getattr(floor_localizer, '_mappoint_id_sets', None)
    if cached is not None:
        return cached
    mp_sets = []
    for mp_ids in floor_localizer.database.get('mappoint_ids', []):
        if mp_ids is None:
            mp_sets.append(set())
            continue
        arr = np.asarray(mp_ids).reshape(-1)
        if arr.size == 0:
            mp_sets.append(set())
            continue
        valid = arr[arr >= 0]
        mp_sets.append(set(int(v) for v in np.unique(valid)))
    floor_localizer._mappoint_id_sets = mp_sets
    return mp_sets


def _compute_jaccard_similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _compute_covisibility_support(floor_localizer, top_indices) -> float:
    if top_indices is None or len(top_indices) == 0:
        return 0.0
    mp_sets = _get_mappoint_id_sets_for_localizer(floor_localizer)
    valid_sets = [mp_sets[idx] for idx in top_indices if 0 <= idx < len(mp_sets)]
    if len(valid_sets) < 2:
        return 0.0
    anchor_set = valid_sets[0]
    anchor_scores = [_compute_jaccard_similarity(anchor_set, s) for s in valid_sets[1:]]
    anchor_support = sum(anchor_scores) / len(anchor_scores) if anchor_scores else 0.0
    pair_scores = [
        _compute_jaccard_similarity(valid_sets[i], valid_sets[j])
        for i in range(len(valid_sets)) for j in range(i + 1, len(valid_sets))
    ]
    pair_support = sum(pair_scores) / len(pair_scores) if pair_scores else 0.0
    return (0.7 * anchor_support) + (0.3 * pair_support)


def rank_floor_candidates_for_frame(frame) -> list:
    if frame is None or not state.floor_configs:
        return []

    # Ranking only needs the per-floor global descriptors. Keep the old
    # Localizer-backed path as a fallback for unusual datasets that do not have
    # a readable descriptor index.
    lightweight_rankings = _rank_floor_with_global_descriptors(frame)
    if lightweight_rankings:
        print('[DEBUG] Floor ranking used global-descriptor index (no keyframe load)')
        return lightweight_rankings

    rankings = []
    for floor_id in sorted(state.floor_configs.keys(), key=lambda item: state.floor_configs[item].get('order', 0)):
        try:
            floor_localizer = get_or_create_localizer(floor_id)
            db_descs = floor_localizer.database.get('global_descriptors')
            if floor_localizer.netvlad_model is None or db_descs is None or len(db_descs) == 0:
                continue
            query_desc = loc.extract_global_features(frame, floor_localizer.netvlad_model).reshape(1, -1)
            if floor_localizer.pca_model is not None:
                query_desc = loc.apply_pca(query_desc, floor_localizer.pca_model)
            else:
                norms = np.linalg.norm(query_desc, axis=1, keepdims=True)
                query_desc = query_desc / (norms + 1e-7)
            sim_scores = np.dot(db_descs, query_desc.flatten())
            if sim_scores.size == 0:
                continue
            top_k = min(5, sim_scores.shape[0])
            top_indices = np.argsort(sim_scores)[::-1][:top_k]
            raw_score = float(sim_scores[top_indices[0]])
            covisibility_score = float(_compute_covisibility_support(floor_localizer, top_indices))
            score = raw_score + (0.08 * covisibility_score)
            rankings.append({
                'floor_id': floor_id,
                'score': score,
                'raw_score': raw_score,
                'covisibility_score': covisibility_score,
                'top_keyframe_ids': [floor_localizer.database['keyframe_ids'][idx] for idx in top_indices]
            })
        except Exception as exc:
            print(f"WARN: start-floor inference failed for {floor_id}: {exc}")
    rankings.sort(key=lambda item: item['score'], reverse=True)
    return rankings


def get_top_floor_candidates(rankings: list, limit: int = 2) -> list:
    candidates = []
    for item in rankings or []:
        floor_id = item.get('floor_id')
        if floor_id and floor_id not in candidates:
            candidates.append(floor_id)
        if len(candidates) >= limit:
            break
    return candidates


def build_floor_hypothesis_candidates(selected_floor: str, rankings: list, seed_candidates=None, limit: int = 2) -> list:
    candidate_floor_ids = []
    for source in ([selected_floor], get_top_floor_candidates(rankings, limit=limit), seed_candidates or []):
        for floor_id in source:
            if not floor_id or floor_id in candidate_floor_ids:
                continue
            candidate_floor_ids.append(floor_id)
            if len(candidate_floor_ids) >= limit:
                return candidate_floor_ids
    return candidate_floor_ids


def evaluate_floor_hypotheses(frame, rankings: list, candidate_floor_ids: list):
    ranking_scores = {item['floor_id']: float(item['score']) for item in (rankings or []) if item.get('floor_id')}
    evaluated = {}
    for floor_id in candidate_floor_ids:
        try:
            hypothesis_localizer = get_or_create_localizer(floor_id)
            t0 = time.time()
            result, xy = hypothesis_localizer.localize(frame)
            localize_time = time.time() - t0
            success = bool(result.get('success')) if isinstance(result, dict) else False
            num_inliers = int(result.get('num_inliers', 0) or 0) if isinstance(result, dict) else 0
            num_matches = int(result.get('num_matches', 0) or 0) if isinstance(result, dict) else 0
            retrieval_score = ranking_scores.get(floor_id, 0.0)
            hypothesis_score = retrieval_score * 100.0
            if success:
                hypothesis_score += min(num_inliers, 120) * 2.0
                hypothesis_score += min(num_matches, 300) * 0.05
            else:
                hypothesis_score -= 1000.0
            evaluated[floor_id] = {
                'floor_id': floor_id, 'result': result, 'xy': xy, 'localize_time': localize_time,
                'success': success, 'num_inliers': num_inliers, 'num_matches': num_matches,
                'retrieval_score': retrieval_score, 'hypothesis_score': hypothesis_score
            }
        except Exception as exc:
            print(f"WARN: floor hypothesis evaluation failed for {floor_id}: {exc}")

    if not evaluated:
        return None, {}

    ordered = sorted(
        evaluated.values(),
        key=lambda item: (item['success'], item['hypothesis_score'], item['retrieval_score'], item['num_inliers'], item['num_matches']),
        reverse=True
    )
    summary = ', '.join(
        f"{item['floor_id']}: ok={item['success']} score={item['hypothesis_score']:.2f} "
        f"(ret={item['retrieval_score']:.4f}, inliers={item['num_inliers']}, matches={item['num_matches']})"
        for item in ordered
    )
    print(f"[DEBUG] Top-floor hypothesis check: {summary}")
    return ordered[0], evaluated


def infer_start_floor_from_frame(frame, return_rankings: bool = False):
    rankings = rank_floor_candidates_for_frame(frame)
    if not rankings:
        fallback = state.current_floor_id or state.default_floor_id
        return (fallback, []) if return_rankings else fallback
    best_floor = rankings[0]['floor_id']
    best_score = rankings[0]['score']
    runner_up = rankings[1] if len(rankings) > 1 else None
    best_raw = rankings[0].get('raw_score', best_score)
    best_covis = rankings[0].get('covisibility_score', 0.0)
    if runner_up is not None:
        margin = best_score - runner_up['score']
        print(f"[OK] Inferred start floor: {best_floor} (score={best_score:.4f}, raw={best_raw:.4f}, covis={best_covis:.4f}, margin={margin:.4f} vs {runner_up['floor_id']})")
    else:
        print(f"[OK] Inferred start floor: {best_floor} (score={best_score:.4f}, raw={best_raw:.4f}, covis={best_covis:.4f})")
    return (best_floor, rankings) if return_rankings else best_floor


def infer_start_floor_from_video(video_path, return_candidates: bool = False):
    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            fallback = state.current_floor_id or state.default_floor_id
            return (fallback, [fallback]) if return_candidates else fallback

        fps = capture.get(cv2.CAP_PROP_FPS) or 1.0
        sample_period_seconds = 1.0
        next_sample_ts = 0.0
        max_samples = 5
        sample_index = 0
        frame_index = 0
        aggregated_scores: dict = {}
        vote_counts: dict = {}
        # Probe the warm current/default floor first. This is the common case
        # for the demo and avoids loading every floor before the first fix.
        preferred_floor = state.current_floor_id or state.default_floor_id
        preferred_probe_done = False

        while sample_index < max_samples:
            success, frame = capture.read()
            if not success:
                break
            timestamp_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
            timestamp = max(0.0, float(timestamp_ms) / 1000.0 if timestamp_ms is not None and timestamp_ms >= 0 else frame_index / fps)
            if timestamp + 1e-6 >= next_sample_ts:
                if not preferred_probe_done:
                    preferred_probe_done = True
                    try:
                        preferred_localizer = get_or_create_localizer(preferred_floor)
                        result, xy = preferred_localizer.localize(frame)
                        if isinstance(result, dict) and result.get('success') and xy is not None:
                            print(f"[OK] Start-floor fast path: {preferred_floor} localized first frame")
                            return (preferred_floor, [preferred_floor]) if return_candidates else preferred_floor
                    except Exception as exc:
                        print(f"WARN: start-floor fast probe failed for {preferred_floor}: {exc}")
                _, rankings = infer_start_floor_from_frame(frame, return_rankings=True)
                if rankings:
                    top_floor = rankings[0]['floor_id']
                    vote_counts[top_floor] = vote_counts.get(top_floor, 0) + 1
                    for item in rankings:
                        aggregated_scores[item['floor_id']] = aggregated_scores.get(item['floor_id'], 0.0) + float(item['score'])
                sample_index += 1
                next_sample_ts += sample_period_seconds
            frame_index += 1

        if not aggregated_scores:
            fallback = state.current_floor_id or state.default_floor_id
            return (fallback, [fallback]) if return_candidates else fallback

        sorted_floors = sorted(aggregated_scores.keys(), key=lambda f: (vote_counts.get(f, 0), aggregated_scores.get(f, 0.0)), reverse=True)
        best_floor = sorted_floors[0]
        summary = ', '.join(f"{f}: votes={vote_counts.get(f, 0)} score={aggregated_scores.get(f, 0.0):.4f}" for f in sorted_floors)
        print(f"[OK] Start-floor consensus: {summary}")
        print(f"[OK] Selected start floor: {best_floor}")
        return (best_floor, sorted_floors[:2]) if return_candidates else best_floor
    finally:
        capture.release()
