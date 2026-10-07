"""
Localizer class — per-floor localization state.
Uses the retrieval backend registry and localization_config for all tunable params.
"""
import cv2
import numpy as np
import torch
import json
import threading
import os
from pathlib import Path

import app.core.localization as loc
import app.core.retrieval as retrieval
import app.core.navigation as nav
from app.core.topology import load_graph
from app.core.self_calibration import CameraSelfCalibrator
import app.localization_config as lc


# Shared retrieval models, keyed by backend.model_cache_key(). Multiple floors
# that use the same (floor-independent) model — e.g. MegaLoc/CosPlace — share a
# single GPU-resident instance instead of each loading its own copy. This is
# what makes parallel preloading of every floor safe (no N× GPU model loads).
_RETRIEVAL_MODEL_CACHE: dict[str, torch.nn.Module] = {}
_RETRIEVAL_MODEL_CACHE_LOCK = threading.Lock()
_RETRIEVAL_DIM_VALIDATION_CACHE: set[tuple[str, str, int]] = set()


def _get_cached_retrieval_model(backend, data_dir: Path, cfg: dict, device: str):
    key = backend.model_cache_key(data_dir, cfg)
    model = _RETRIEVAL_MODEL_CACHE.get(key)
    if model is not None:
        return model
    with _RETRIEVAL_MODEL_CACHE_LOCK:
        model = _RETRIEVAL_MODEL_CACHE.get(key)
        if model is None:
            model = _load_startup_optimized_model(backend, data_dir, cfg, device)
            _RETRIEVAL_MODEL_CACHE[key] = model
        return model


def _load_startup_optimized_model(backend, data_dir: Path, cfg: dict, device: str):
    """Avoid constructing a Torch model that accelerated mode immediately replaces."""
    accel_enabled = os.getenv('NAV_ACCEL', '1').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    # ONNX graph/session construction can be slower than loading Torch on some
    # machines. Keep it opt-in until the deployment device has a measured win;
    # persistent server processes still benefit from the shared ONNX session.
    direct_onnx = os.getenv('NAV_DIRECT_ONNX_STARTUP', '0').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    if backend.name == 'megaloc' and accel_enabled and direct_onnx:
        onnx_path = Path(__file__).resolve().parents[1] / 'data' / 'models' / 'megaloc_fp16.onnx'
        if onnx_path.exists():
            try:
                from app.core.models.megaloc_onnx.onnx_megaloc import OnnxMegaLoc

                optimized = OnnxMegaLoc(str(onnx_path), device=device)
                if optimized.on_cuda:
                    print('[ACCEL] MegaLoc ONNX fp16 loaded directly at startup')
                    return optimized
                print('[ACCEL] ONNX CUDA unavailable; falling back to Torch MegaLoc')
            except Exception as exc:
                print(f'[ACCEL] direct ONNX startup load skipped ({exc}); using Torch MegaLoc')
    return backend.load_model(data_dir, cfg).to(device)


def clear_retrieval_model_cache() -> None:
    """Drop all cached retrieval models (e.g. after switching retrieval mode)."""
    with _RETRIEVAL_MODEL_CACHE_LOCK:
        _RETRIEVAL_MODEL_CACHE.clear()
        _RETRIEVAL_DIM_VALIDATION_CACHE.clear()


def _find_h_matrix_path(data_dir: Path):
    candidates = sorted(data_dir.glob('H_matrix*_offset.npy'))
    return candidates[0] if candidates else None


DEFAULT_FLOOR_ID = 'floor5'
DEFAULT_DATA_DIR = Path('map_data/result_floor5_6')
DEFAULT_FLOOR_PLAN_PATH = Path('map/floor5.jpg')
DEFAULT_JSON_MAP_PATH = Path('json_map/floor5.json')


class Localizer:
    def __init__(
        self,
        floor_id: str = DEFAULT_FLOOR_ID,
        data_dir=None,
        floor_plan_path=None,
        json_map_path=None,
        matching_mode: str = 'superpoint',
        retrieval_mode: str | None = None,
    ):
        self.floor_id = floor_id
        self.data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
        self.requested_matching_mode = matching_mode
        self.matching_mode = matching_mode

        # Resolve retrieval mode: arg → localization_config default
        mode = (retrieval_mode or lc.RETRIEVAL_MODE or '').strip().lower()
        if mode not in retrieval.supported_modes():
            raise ValueError(
                f"Unknown retrieval mode {mode!r}; automatic NetVLAD fallback is disabled."
            )
        self.retrieval_mode = mode
        self._backend = retrieval.get_backend(self.retrieval_mode)
        self._backend_cfg = lc.BACKEND_CONFIGS.get(self.retrieval_mode, {})

        preferred_keyframes_dir = self.data_dir / (
            'keyframes_superpoint' if matching_mode == 'superpoint' else 'keyframes'
        )
        if matching_mode == 'superpoint' and not preferred_keyframes_dir.exists():
            raise FileNotFoundError(
                f"SuperPoint map is required but was not found: {preferred_keyframes_dir}. "
                "Automatic ORB fallback is disabled."
            )

        self.keyframes_dir = preferred_keyframes_dir

        # PCA path comes from backend config.
        # An empty pca_file means the backend needs no PCA (e.g. MegaLoc is
        # already L2-normalized) — do NOT fall back to the NetVLAD pca_model.pkl.
        pca_filename = self._backend.pca_file(self._backend_cfg)
        self.pca_model_path = self.data_dir / pca_filename if pca_filename else None

        self.floor_plan_path = Path(floor_plan_path) if floor_plan_path is not None else DEFAULT_FLOOR_PLAN_PATH
        self.json_map_path   = Path(json_map_path)   if json_map_path   is not None else DEFAULT_JSON_MAP_PATH
        self.debug_mode = False

        print(f"Initializing Localizer for {self.floor_id} "
              f"(match={self.matching_mode}, retrieval={self.retrieval_mode})...")

        self.K = loc.load_camera_intrinsics(self.data_dir)
        self.map_K = np.asarray(self.K, dtype=np.float64).copy()
        # Retrieval/matching models are shared by live camera requests and the
        # causal video worker. Serialize inference at this boundary while
        # keeping the request handler itself non-blocking.
        self._localize_lock = threading.RLock()
        self._calibration_generation = 0
        # Map K is provisional; query-side calibration runs asynchronously.
        self.camera_self_calibrator = CameraSelfCalibrator(
            self.K,
            on_commit=lambda calibrated_K: self._commit_camera_calibration(calibrated_K, 0),
        )
        self.mappoint_dict = loc.load_mappoints(self.data_dir)

        desc_filename = self._backend.descriptor_file(self._backend_cfg)
        global_desc_path = self.data_dir / desc_filename
        if not global_desc_path.exists():
            raise FileNotFoundError(
                f"{self.retrieval_mode} descriptor file is required but was not found: "
                f"{global_desc_path}. Automatic NetVLAD fallback is disabled."
            )
        self.database = loc.load_keyframe_database(self.keyframes_dir, global_desc_path=global_desc_path)
        self.pca_model = loc.load_pca_model(self.pca_model_path) if self.pca_model_path else None

        if self.pca_model:
            print("Applying PCA to database descriptors...")
            self.database['global_descriptors'] = loc.apply_pca(
                self.database['global_descriptors'], self.pca_model
            )

        self.floor_config = None
        self.H_matrix = None
        config_path = self.data_dir / 'floor_algin_offset_config.json'
        h_matrix_path = _find_h_matrix_path(self.data_dir)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                self.floor_config = json.load(f)
        if h_matrix_path and h_matrix_path.exists():
            self.H_matrix = np.load(h_matrix_path)

        # Load retrieval model via registry
        self.retrieval_model = None
        self.netvlad_model = None
        self._load_retrieval_model()

        # Verify descriptor dimension matches database
        self._verify_retrieval_dim()

        # Load navigation graph
        print("Loading Topology Graph...")
        self.G, self.nodes = load_graph(self.json_map_path, verbose=False)

        # Check ORB vs SuperPoint compatibility. An explicit legacy ORB run is
        # still possible with NAV_ACCEL=0; only the requested SuperPoint stack
        # is rejected when the selected map contains ORB descriptors.
        use_hloc = self.matching_mode == 'superpoint'
        if use_hloc:
            for desc in self.database['descriptors']:
                if desc is not None and len(desc) > 0:
                    if desc.shape[1] == 32:
                        raise RuntimeError(
                            f"Map {self.data_dir} contains ORB descriptors, but the requested "
                            "SuperPoint map is required. Automatic ORB fallback is disabled."
                        )
                    break

        self.superpoint_extractor = None
        self.superglue_matcher = None
        if use_hloc:
            print("Loading SuperPoint features and production matcher...")
            try:
                from app.core.models import hloc_wrapper
                import app.config as app_config
                device = 'cuda' if torch.cuda.is_available() else 'cpu'
                self.superpoint_extractor = hloc_wrapper.HlocExtractor(
                    max_keypoints=2048, keypoint_threshold=0.005, device=device
                )
                if app_config.ACCEL_MODE:
                    # LightGlue is the production matcher. Avoid constructing
                    # SuperGlue only to replace it after Localizer initialization.
                    from app.core.models.lightglue_matcher import LightGlueMatcher
                    self.superglue_matcher = LightGlueMatcher(mp=True, flash=True, device=device)
                else:
                    self.superglue_matcher = hloc_wrapper.HlocMatcher(match_threshold=0.2, device=device)
                print(f"hloc models loaded on {device}")
            except Exception as e:
                raise RuntimeError(
                    f"Failed to load SuperPoint features. Automatic ORB fallback is disabled: {e}"
                ) from e

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _load_retrieval_model(self) -> None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        try:
            self.retrieval_model = _get_cached_retrieval_model(
                self._backend, self.data_dir, self._backend_cfg, device
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load required {self.retrieval_mode} retrieval model. "
                f"Automatic NetVLAD fallback is disabled: {exc}"
            ) from exc
        self.netvlad_model = self.retrieval_model

    def _verify_retrieval_dim(self) -> None:
        db_descs = self.database.get('global_descriptors')
        if (
            self.retrieval_model is None
            or not isinstance(db_descs, np.ndarray)
            or db_descs.ndim != 2
            or db_descs.shape[0] == 0
        ):
            return
        db_dim = int(db_descs.shape[1])
        validation_key = (
            self.retrieval_mode,
            self.retrieval_model.__class__.__name__,
            db_dim,
        )
        if validation_key in _RETRIEVAL_DIM_VALIDATION_CACHE:
            return
        probe_image = None
        if self.keyframes_dir.exists():
            for kf_dir in sorted(self.keyframes_dir.iterdir()):
                if not kf_dir.is_dir():
                    continue
                for ext in ('image.jpg', 'image.png'):
                    candidate = kf_dir / ext
                    if candidate.exists():
                        probe_image = candidate
                        break
                if probe_image:
                    break
        if probe_image is None:
            return
        try:
            probe = loc.extract_global_features(probe_image, self.retrieval_model)
            if self.pca_model is not None:
                probe = loc.apply_pca(
                    np.asarray(probe, dtype=np.float32).reshape(1, -1), self.pca_model
                ).reshape(-1)
            if int(np.asarray(probe).shape[0]) != db_dim:
                raise RuntimeError(
                    f"{self.retrieval_mode} descriptor dimension mismatch for {self.floor_id}: "
                    f"model={int(np.asarray(probe).shape[0])}, database={db_dim}. "
                    "Retrieval is required; it will not be disabled or replaced by NetVLAD."
                )
            _RETRIEVAL_DIM_VALIDATION_CACHE.add(validation_key)
        except Exception as probe_exc:
            print(f"Warning: retrieval dimension probe failed: {probe_exc}")

    # ── Public API ───────────────────────────────────────────────────────────

    def _commit_camera_calibration(self, calibrated_K: np.ndarray, generation: int | None = None) -> None:
        # Replace the reference after a request has copied K for its pipeline.
        if generation is not None and generation != self._calibration_generation:
            return
        self.K = np.asarray(calibrated_K, dtype=np.float64).copy()
        print(f"[CALIB] committed image-only focal={self.K[0, 0]:.1f}px")

    def reset_camera_calibration(self) -> None:
        """Start a new camera session from map intrinsics without reloading maps."""
        previous = getattr(self, 'camera_self_calibrator', None)
        if previous is not None:
            previous.close()
        self._calibration_generation += 1
        generation = self._calibration_generation
        self.K = self.map_K.copy()
        self.camera_self_calibrator = CameraSelfCalibrator(
            self.K,
            on_commit=lambda calibrated_K: self._commit_camera_calibration(calibrated_K, generation),
        )

    def localize(
        self,
        image_input,
        return_correspondences: bool = False,
        *,
        camera_K=None,
        calibration_callback=None,
    ):
        """
        Localize a single frame (Path or numpy array).
        Returns (result dict, xy_map tuple or None).
        """
        img_name = (
            Path(image_input).name if isinstance(image_input, (str, Path)) else "frame_buffer"
        )
        print(f"\n--- Localizing: {img_name} ---")

        floor_plan_size = None
        if self.floor_plan_path.exists():
            img = cv2.imread(str(self.floor_plan_path))
            if img is not None:
                floor_plan_size = img.shape[:2]

        use_superpoint = self.matching_mode == 'superpoint'
        use_superglue = use_superpoint and self.superglue_matcher is not None

        p = lc.LOCALIZATION_PARAMS
        camera_K = (
            self.camera_self_calibrator.active_K()
            if camera_K is None else np.asarray(camera_K, dtype=np.float64).copy()
        )

        # A sweep/retry can localize the same image through several hypotheses.
        # Deduplicate that image so one physical frame contributes at most one
        # calibration estimate to the session-level consensus.
        if isinstance(image_input, np.ndarray):
            token_image = cv2.resize(image_input, (16, 9), interpolation=cv2.INTER_AREA)
            calibration_frame_token = hash(token_image.tobytes())
        else:
            calibration_frame_token = ("path", str(image_input))

        def submit_calibration(points_2d, points_3d):
            if calibration_callback is not None:
                return calibration_callback(points_2d, points_3d)
            return self.camera_self_calibrator.submit(
                points_2d, points_3d, frame_token=calibration_frame_token,
            )

        with self._localize_lock:
            result = loc.localize_image(
                image_input,
                self.database,
                self.mappoint_dict,
                camera_K,
                pca_model=self.pca_model,
                floor_config=self.floor_config,
                netvlad_model=self.retrieval_model,
                superpoint_extractor=self.superpoint_extractor,
                superglue_matcher=self.superglue_matcher,
                H_matrix=self.H_matrix,
                top_k=p['top_k'],
                reproj_threshold=p['reproj_threshold'],
                min_inliers=p['min_inliers'],
                min_inlier_ratio=p['min_inlier_ratio'],
                max_median_reproj_error=p['max_median_reproj_error'],
                floor_plan_size=floor_plan_size,
                verbose=False,
                debug_mode=self.debug_mode,
                allow_orb_fallback=False,
                allow_keyframe_fallback=False,
                use_superpoint=use_superpoint,
                use_superglue=use_superglue,
                calibration_callback=submit_calibration,
                return_correspondences=return_correspondences,
            )

        xy_map = None
        if result['success']:
            pos_3d = result['pose']['position']
            xy_map = loc.project_to_floor_plan(pos_3d, self.H_matrix, self.floor_config)
            print(
                f"Success! Map: ({xy_map[0]:.1f}, {xy_map[1]:.1f})"
                if xy_map is not None else "Success!"
            )
        else:
            print("Localization Failed.")

        if isinstance(result, dict):
            if return_correspondences and result.get('_tracking_points_3d') is not None:
                # The production matcher exposes 2D/3D pairs, while the
                # temporal tracker also needs stable map-point identities for
                # bounded deduplication. Reconstruct them from the immutable
                # map database; points originate from this exact dictionary.
                point_ids = []
                by_point = {
                    np.asarray(point, dtype=np.float32).tobytes(): int(mp_id)
                    for mp_id, point in self.mappoint_dict.items()
                }
                for point in result['_tracking_points_3d']:
                    point_ids.append(by_point.get(np.asarray(point, dtype=np.float32).tobytes(), -1))
                result['_tracking_mp_ids'] = np.asarray(point_ids, dtype=np.int64)
            result['matching_mode'] = self.matching_mode
            result['requested_matching_mode'] = self.requested_matching_mode
            result['keyframes_dir'] = str(self.keyframes_dir)
            result['floor_id'] = self.floor_id
            result['retrieval_mode'] = self.retrieval_mode
            result['camera_calibration'] = self.camera_self_calibrator.snapshot()

        return result, xy_map

    def navigate(self, start_xy, target_room_name):
        """Calculate path from start_xy (pixels) to target_room_name."""
        if start_xy is None:
            return None, None
        pixel_x, pixel_y = start_xy
        start_node, _ = nav.find_nearest_node(self.G, self.nodes, pixel_x, pixel_y)
        end_node = nav.get_node_by_name(self.nodes, target_room_name)
        if not end_node:
            print(f"Error: Target '{target_room_name}' not found.")
            return None, None
        path_nodes = nav.find_path(self.G, start_node, end_node)
        if not path_nodes:
            print("Error: No path found.")
            return None, None
        return path_nodes, end_node
