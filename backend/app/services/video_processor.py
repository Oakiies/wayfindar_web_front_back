"""Video I/O and per-frame navigation orchestration."""
from __future__ import annotations
import math
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

import app.config as config
from app.services.state import state
from app.services.session import NavigationSession
from app.services.floor_service import set_active_floor
from app.services.localizer_service import get_or_create_localizer
from app.services.floor_detection import (
    infer_start_floor_from_video,
    rank_floor_candidates_for_frame,
)
from app.services.nav_service import resolve_destination_node, compute_navigation_route
from app.services import ar_service
from app.utils.heading import (
    normalize_heading_deg,
    blend_heading_deg,
    calculate_direction,
    calculate_camera_heading,
)
from app.core.smoothing import create_smoother
from app.core import navigation as nav
import app.core.localization as localization_core
import app.localization_config as lc

MAX_DEBUG_FRAMES = 200
# Trigger an immediate production relocalization after consecutive rejected
# tracking updates. The existing cadence remains the retry path if it misses.
TRACKING_LOSS_RELOCALIZE_FRAMES = 3


def _track_step(previous_gray, current_gray, points_2d, points_3d, point_ids, max_error=1.5):
    """Forward/backward Lucas-Kanade tracking for a 2D–3D seed set."""
    if len(points_2d) < 4:
        return points_2d[:0], points_3d[:0], point_ids[:0]
    if previous_gray is None or current_gray is None or previous_gray.shape != current_gray.shape:
        return points_2d[:0], points_3d[:0], point_ids[:0]
    source = np.asarray(points_2d, np.float32).reshape(-1, 1, 2)
    target, status_forward, _ = cv2.calcOpticalFlowPyrLK(
        previous_gray, current_gray, source, None, winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if target is None or status_forward is None:
        return points_2d[:0], points_3d[:0], point_ids[:0]
    backward, status_backward, _ = cv2.calcOpticalFlowPyrLK(
        current_gray, previous_gray, target, None, winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if backward is None or status_backward is None:
        return points_2d[:0], points_3d[:0], point_ids[:0]
    target = target.reshape(-1, 2)
    backward = backward.reshape(-1, 2)
    source_flat = source.reshape(-1, 2)
    h, w = current_gray.shape[:2]
    error = np.linalg.norm(backward - source_flat, axis=1)
    keep = (
        (status_forward.reshape(-1) > 0) & (status_backward.reshape(-1) > 0) &
        np.isfinite(target).all(axis=1) & (error <= max_error) &
        (target[:, 0] >= 0) & (target[:, 0] < w) &
        (target[:, 1] >= 0) & (target[:, 1] < h)
    )
    return target[keep], np.asarray(points_3d)[keep], np.asarray(point_ids)[keep]


class _ContinuousPoseTracker:
    """Propagate a localized 2D-3D seed through native video frames.

    Global retrieval/matching is intentionally performed only at the caller's
    cadence.  Between those requests, Lucas-Kanade KLT tracks the seed
    landmarks and PnP reconstructs a camera pose for the current frame.  This
    is the same division used by the causal replay pipeline and keeps AR
    updates at the source FPS without uploading/locating every frame.
    """

    def __init__(self, localizer, floor_id: str):
        self.track_step = _track_step
        self.localizer = localizer
        self.floor_id = floor_id
        self.previous_gray = None
        self.points_2d = np.empty((0, 2), np.float32)
        self.points_3d = np.empty((0, 3), np.float32)
        self.point_ids = np.empty((0,), np.int64)
        self._last_tracks_before = 0
        self._last_tracks_after = 0

    def reset(self, localizer=None, floor_id: str | None = None):
        if localizer is not None:
            self.localizer = localizer
        if floor_id is not None:
            self.floor_id = floor_id
        self.previous_gray = None
        self.points_2d = np.empty((0, 2), np.float32)
        self.points_3d = np.empty((0, 3), np.float32)
        self.point_ids = np.empty((0,), np.int64)

    def _gray(self, frame):
        K = self.localizer.camera_self_calibrator.active_K()
        size = localization_core.get_reference_image_size_from_intrinsics(K)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return localization_core.resize_query_image(gray, size) if size else gray

    def _tracked_result(self):
        if len(self.points_2d) < 4:
            return None, None
        K = self.localizer.camera_self_calibrator.active_K()
        ok, R, t, inliers = localization_core.solve_pnp_ransac(
            self.points_2d, self.points_3d, K, reproj_threshold=8.0,
            min_inliers=4,
        )
        if not ok or inliers is None:
            return None, None
        ratio, error = localization_core.compute_pnp_quality(
            self.points_2d, self.points_3d, inliers, R, t, K,
        )
        params = lc.LOCALIZATION_PARAMS
        accepted = (
            len(inliers) >= int(params['min_inliers']) and
            ratio >= float(params['min_inlier_ratio']) and
            math.isfinite(error) and
            error <= float(params['max_median_reproj_error'])
        )
        pose = localization_core.get_6dof_pose(R, t)
        pose['theta'] = localization_core.transform_yaw(
            localization_core.get_yaw(R), self.localizer.H_matrix,
        )
        xy = localization_core.project_to_floor_plan(
            pose.get('position'), self.localizer.H_matrix, self.localizer.floor_config,
        )
        if xy is None or not np.isfinite(xy).all():
            accepted = False
            xy = None
        result = {
            'success': bool(accepted),
            'pose': pose if accepted else None,
            'num_inliers': int(len(inliers)),
            'num_matches': int(len(self.points_2d)),
            'inlier_ratio': float(ratio),
            'median_reproj_error': float(error),
            'method': 'KLT-PnP',
            'matching_mode': self.localizer.matching_mode,
            'floor_id': self.floor_id,
            '_inlier_indices': np.asarray(inliers).reshape(-1).astype(np.int32),
            'tracks_before': int(self._last_tracks_before),
            'tracks_after': int(self._last_tracks_after),
            'pnp_inliers': int(len(inliers)),
            'pnp_inlier_ratio': float(ratio),
            'pnp_reproj_error': float(error),
        }
        return result, tuple(float(value) for value in xy) if xy is not None else None

    def update(self, frame, seed_result=None, seed_xy=None):
        gray = self._gray(frame)
        seed_ok = bool(seed_result and seed_result.get('success') and seed_xy is not None)
        if seed_ok:
            points_2d = seed_result.get('_tracking_points_2d')
            points_3d = seed_result.get('_tracking_points_3d')
            if points_2d is not None and points_3d is not None and len(points_2d) >= 4:
                self.points_2d = np.asarray(points_2d, dtype=np.float32).reshape(-1, 2)
                self.points_3d = np.asarray(points_3d, dtype=np.float32).reshape(-1, 3)
                self.point_ids = np.arange(len(self.points_2d), dtype=np.int64)
            else:
                self.points_2d = np.empty((0, 2), np.float32)
                self.points_3d = np.empty((0, 3), np.float32)
            self.previous_gray = gray
            return seed_result, seed_xy

        if self.previous_gray is not None and len(self.points_2d) >= 4:
            self.points_2d, self.points_3d, self.point_ids = self.track_step(
                self.previous_gray, gray, self.points_2d, self.points_3d,
                self.point_ids, 1.5,
            )
        self.previous_gray = gray
        return self._tracked_result()


class _CausalPoseTracker(_ContinuousPoseTracker):
    """Causal tracker used by every video destination and floor.

    Global localization runs in one background worker at the requested tick.
    The foreground loop only consumes completed results after tracking their
    source landmarks through frames that have already arrived. No future frame
    is used and no worker mutates the shared Localizer/CameraSelfCalibrator.
    """

    def __init__(self, localizer, floor_id: str):
        super().__init__(localizer, floor_id)
        from poc_cross_camera.run_temporal_landmark_propagation import (
            dedupe_correspondences,
        )
        self._dedupe = dedupe_correspondences
        self._history = deque(maxlen=180)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='causal-localize')
        self._pending = None
        self._pending_source = None
        self._pending_generation = 0
        self._generation = 0
        self._closed = False
        self._track_source_frame = None
        self._track_source_timestamp = None
        self._last_completed_work_s = None
        self._last_completed_source_wall_time = None
        self._floor_reset_this_step = False
        self._tracking_failure_streak = 0
        self._loss_relocalize_attempted = False
        self.diagnostics = {
            'localization_submitted': 0,
            'localization_completed': 0,
            'localization_rejected_stale': 0,
            'localization_rejected_session': 0,
            'localization_errors': 0,
            'track_dropouts': 0,
            'seed_rejections': {},
            'floor_resets': 0,
        }

    def close(self):
        self._closed = True
        self._generation += 1
        pending = self._pending
        self._pending = None
        if pending is not None:
            pending.cancel()
        self._worker.shutdown(wait=False, cancel_futures=True)

    def reset(self, localizer=None, floor_id: str | None = None):
        """Invalidate every in-flight result before changing floor/session."""
        self._generation += 1
        pending = self._pending
        self._pending = None
        self._pending_source = None
        self._pending_generation = self._generation
        if pending is not None:
            pending.cancel()
        super().reset(localizer, floor_id)
        self._history.clear()
        self._track_source_frame = None
        self._track_source_timestamp = None
        self._floor_reset_this_step = False
        self._tracking_failure_streak = 0
        self._loss_relocalize_attempted = False

    def _seed(self, frame, frame_index, timestamp, K, generation,
              submitted_wall_time_s=None, allow_floor_handoff=False):
        started = time.perf_counter()
        # Use the production Localizer pipeline with a private K snapshot. The
        # callback is intentionally disabled here; calibration is committed by
        # the foreground session after this result passes generation/history
        # checks, so a late worker cannot mutate a new session.
        result, xy = self.localizer.localize(
            frame,
            return_correspondences=True,
            camera_K=np.asarray(K, dtype=np.float64).copy(),
            calibration_callback=lambda *_args: False,
        )
        result_floor_id = getattr(self, 'floor_id', None) or getattr(self.localizer, 'floor_id', None)
        handoff_reason = None
        if allow_floor_handoff and not (isinstance(result, dict) and result.get('success')):
            # A lost visual track is the only time we spend the extra global
            # descriptor pass. It sees this frame only, then validates the
            # best alternative floor with the same production localizer.
            rankings = rank_floor_candidates_for_frame(frame)
            for candidate in rankings[:3]:
                candidate_floor = candidate.get('floor_id')
                if not candidate_floor or candidate_floor == self.floor_id:
                    continue
                candidate_localizer = get_or_create_localizer(candidate_floor)
                candidate_result, candidate_xy = candidate_localizer.localize(
                    frame,
                    return_correspondences=True,
                    camera_K=candidate_localizer.camera_self_calibrator.active_K().copy(),
                    calibration_callback=lambda *_args: False,
                )
                if isinstance(candidate_result, dict) and candidate_result.get('success'):
                    result, xy = candidate_result, candidate_xy
                    result_floor_id = candidate_floor
                    handoff_reason = 'current_floor_miss'
                    break
        return {
            'frame': int(frame_index), 'timestamp': float(timestamp),
            'result': result, 'xy': xy, 'generation': int(generation),
            'floor_id': result_floor_id,
            'handoff_reason': handoff_reason,
            'submitted_wall_time_s': float(submitted_wall_time_s or time.time()),
            'work_s': time.perf_counter() - started,
        }

    def _merge_completed_seed(self, current_frame_index):
        if self._pending is None or not self._pending.done():
            return False
        try:
            result = self._pending.result()
        except Exception:
            self._pending = None
            self.diagnostics['localization_errors'] += 1
            self.diagnostics['seed_rejections']['worker_exception'] = self.diagnostics['seed_rejections'].get('worker_exception', 0) + 1
            return False
        self._pending = None
        self.diagnostics['localization_completed'] += 1
        self._last_completed_work_s = float(result.get('work_s', 0.0) or 0.0)
        if self._closed or result.get('generation') != self._generation:
            self.diagnostics['localization_rejected_session'] += 1
            return False
        source_frame = int(result['frame'])
        history_indices = [idx for idx, _gray in self._history]
        if not history_indices or source_frame < history_indices[0] \
                or source_frame > current_frame_index \
                or source_frame not in history_indices:
            self.diagnostics['localization_rejected_stale'] += 1
            self.diagnostics['seed_rejections']['history_or_future'] = self.diagnostics['seed_rejections'].get('history_or_future', 0) + 1
            return False
        localization_result = result.get('result') or {}
        if not localization_result.get('success'):
            reason = localization_result.get('rejection_reason', 'localization_miss')
            self.diagnostics['seed_rejections'][reason] = self.diagnostics['seed_rejections'].get(reason, 0) + 1
            return False
        result_floor_id = result.get('floor_id') or self.floor_id
        if result_floor_id != self.floor_id:
            set_active_floor(result_floor_id)
            self.localizer = state.localizer
            self.localizer.reset_camera_calibration()
            self.floor_id = result_floor_id
            self.previous_gray = self._history[-1][1] if self._history else self.previous_gray
            self.points_2d = np.empty((0, 2), np.float32)
            self.points_3d = np.empty((0, 3), np.float32)
            self.point_ids = np.empty((0,), np.int64)
            self.diagnostics['floor_resets'] += 1
            self._floor_reset_this_step = True
        p2 = np.asarray(localization_result.get('_tracking_points_2d'), np.float32)
        p3 = np.asarray(localization_result.get('_tracking_points_3d'), np.float32)
        ids = np.asarray(localization_result.get('_tracking_mp_ids'), np.int64)
        if len(p2) < 4 or len(p2) != len(p3) or len(ids) != len(p2) or np.any(ids <= 0):
            self.diagnostics['seed_rejections']['invalid_correspondences'] = self.diagnostics['seed_rejections'].get('invalid_correspondences', 0) + 1
            return False

        self.localizer.camera_self_calibrator.submit(
            p2, p3, frame_token=('causal', result['frame']),
        )
        source_pose = self._solve_points(p2, p3)
        if source_pose is None or not source_pose[0].get('success'):
            self.diagnostics['seed_rejections']['source_pnp'] = self.diagnostics['seed_rejections'].get('source_pnp', 0) + 1
            return False
        keep = source_pose[0].get('_inlier_indices')
        if keep is not None:
            p2, p3, ids = p2[keep], p3[keep], ids[keep]

        past = [(idx, gray) for idx, gray in self._history if idx >= source_frame]
        if not past or past[0][0] != source_frame:
            self.diagnostics['localization_rejected_stale'] += 1
            return False
        for (_idx_a, gray_a), (_idx_b, gray_b) in zip(past, past[1:]):
            p2, p3, ids = self.track_step(gray_a, gray_b, p2, p3, ids, 1.0)
            if len(p2) < 4:
                self.diagnostics['seed_rejections']['catchup_tracks'] = self.diagnostics['seed_rejections'].get('catchup_tracks', 0) + 1
                return False

        items = [
            {'point_2d': a, 'point_3d': b, 'mp_id': int(c), 'track_error': 0.0}
            for a, b, c in zip(p2, p3, ids)
        ]
        items.extend(
            {'point_2d': a, 'point_3d': b, 'mp_id': int(c), 'track_error': 1.0}
            for a, b, c in zip(self.points_2d, self.points_3d, self.point_ids)
        )
        combined = self._dedupe(items)
        self.points_2d = combined['points_2d']
        self.points_3d = combined['points_3d']
        self.point_ids = combined['mp_ids']
        self._track_source_frame = source_frame
        self._track_source_timestamp = float(result['timestamp'])
        self._last_completed_source_wall_time = float(result.get('submitted_wall_time_s', time.time()))
        return True

    def _solve_points(self, points_2d, points_3d):
        saved_2d, saved_3d = self.points_2d, self.points_3d
        try:
            self.points_2d, self.points_3d = points_2d, points_3d
            return self._tracked_result()
        finally:
            self.points_2d, self.points_3d = saved_2d, saved_3d

    def step(self, frame, frame_index, timestamp, should_localize):
        if self._closed:
            return None, None
        gray = self._gray(frame)
        self._last_tracks_before = int(len(self.points_2d))
        if self.previous_gray is not None and len(self.points_2d) >= 4:
            self.points_2d, self.points_3d, self.point_ids = self.track_step(
                self.previous_gray, gray, self.points_2d, self.points_3d,
                self.point_ids, 1.0,
            )
        self._last_tracks_after = int(len(self.points_2d))
        self.previous_gray = gray
        self._history.append((int(frame_index), gray))
        refreshed = self._merge_completed_seed(frame_index)
        if self._floor_reset_this_step:
            # Each floor can have a different calibrated reference-image size.
            # Rebuild the current grayscale frame under the new floor's K and
            # discard pre-handoff history before the next LK call.
            gray = self._gray(frame)
            self.previous_gray = gray
            self._history.clear()
            self._history.append((int(frame_index), gray))
            self._floor_reset_this_step = False
        result, xy = self._tracked_result()
        if isinstance(result, dict) and result.get('success'):
            self._tracking_failure_streak = 0
            self._loss_relocalize_attempted = False
            result['method'] = 'PnP' if refreshed else 'KLT-PnP'
            result['causal_source_frame'] = self._track_source_frame
            result['causal_source_timestamp'] = self._track_source_timestamp
            result['current_tracking_frame'] = int(frame_index)
            result['tracking_status'] = 'tracked'
            result['async_localize_time'] = self._last_completed_work_s
            result['pose_age_s'] = 0.0
            result['source_to_current_video_s'] = (
                float(timestamp) - float(self._track_source_timestamp)
                if self._track_source_timestamp is not None else None
            )
            result['source_to_emit_wall_s'] = (
                time.time() - float(self._last_completed_source_wall_time)
                if self._last_completed_source_wall_time is not None else None
            )
        else:
            self._tracking_failure_streak += 1
            self.diagnostics['track_dropouts'] += 1
            result = {
                'success': False,
                'method': 'KLT-PnP',
                'num_matches': int(len(self.points_2d)),
                'num_inliers': 0,
                'tracking_status': (
                    'tracking_lost' if len(self.points_2d) < 4 else 'pose_rejected'
                ),
                'causal_source_frame': self._track_source_frame,
                'causal_source_timestamp': self._track_source_timestamp,
                'current_tracking_frame': int(frame_index),
                'async_localize_time': self._last_completed_work_s,
                'pose_age_s': None,
                'source_to_current_video_s': (
                    float(timestamp) - float(self._track_source_timestamp)
                    if self._track_source_timestamp is not None else None
                ),
                'source_to_emit_wall_s': (
                    time.time() - float(self._last_completed_source_wall_time)
                    if self._last_completed_source_wall_time is not None else None
                ),
            }

        force_relocalize = (
            self._tracking_failure_streak >= TRACKING_LOSS_RELOCALIZE_FRAMES
            and not self._loss_relocalize_attempted
        )
        if self._pending is None and (should_localize or force_relocalize):
            K = self.localizer.camera_self_calibrator.active_K()
            self._pending_source = int(frame_index)
            self._pending_generation = self._generation
            self._pending = self._worker.submit(
                self._seed, frame.copy(), frame_index, timestamp, K,
                self._pending_generation, time.time(), len(self.points_2d) < 4,
            )
            self.diagnostics['localization_submitted'] += 1
            if self._tracking_failure_streak:
                self._loss_relocalize_attempted = True
        return result, xy

# Central AR debug log — any server process running this code appends here, so
# it can be inspected regardless of where stdout is redirected.
AR_DEBUG_LOG = Path(__file__).resolve().parent.parent / 'ar_debug.log'


def _ar_debug(line: str, reset: bool = False) -> None:
    try:
        with open(AR_DEBUG_LOG, 'w' if reset else 'a', encoding='utf-8') as f:
            f.write(line + '\n')
            f.flush()
    except Exception:
        pass


def _get_pose_stabilizer(session, localizer_ref, floor_id, interval_seconds):
    """Per-session PoseStabilizer (EMA on raw PnP R/t), rebuilt on floor change.

    ``session.ar_pose_stabilizer`` was scaffolded for this in session.py but
    left unwired: every live/replay frame projected with the raw PnP pose,
    which is the measured cause of the "wobble" in
    poc_ar_arrow/out/DIAGNOSIS_ar_m21_walk.md (2-10 deg of unfiltered
    frame-to-frame rotation, occasional 100+ deg outliers). A naive constant-
    alpha EMA was tried and reverted before for lagging a real turn — but
    build_ar_world_v2 already has the fix for exactly that: if the stabilized
    pose yields zero visible carets, it retries once with the raw pose
    (ar_arrow_v2.py, "if not carets and stabilizer is not None"), so a lagged
    turn falls back to what ships today instead of freezing. turn_alpha/
    turn_follow_deg make it snap to a real turn once the measured rotation
    passes the noise floor; expected_interval_s scales the jump/turn gates to
    match how sparse this session's samples actually are.
    """
    if session.ar_pose_stabilizer is None or session.ar_pose_stabilizer_floor != floor_id:
        # Lazy, function-local import: matches ar_service.build_ar_world_poc's
        # own import of poc_ar_arrow, keeping app/ free of a module-level
        # dependency on the sibling PoC package.
        from poc_ar_arrow.ar_arrow_v2 import PoseStabilizer
        proj = ar_service.get_projector(floor_id, localizer_ref)
        metres_per_unit = proj.metres_per_unit if proj is not None else 1.0
        session.ar_pose_stabilizer = PoseStabilizer(
            alpha=0.24, max_jump_m=1.0, max_turn_deg=22.0,
            turn_follow_deg=6.0, turn_alpha=0.50,
            expected_interval_s=interval_seconds, metres_per_unit=metres_per_unit,
        )
        session.ar_pose_stabilizer_floor = floor_id
    return session.ar_pose_stabilizer


def _get_route_progress_tracker(session, path_coords):
    """Per-session RouteProgressTracker, reset when the route itself changes.

    Fixes a reported symptom: AR guidance sometimes kept showing a turn (or
    a station) the walker had already physically passed, as if it was not
    considering where they actually are. Root cause: chevron_anchors decides
    which stations are "ahead" from the raw camera-floor position each frame
    (needed so stations don't lag behind the real camera - see
    _get_pose_stabilizer above for why raw, not smoothed, pose is used here
    too), and that raw position was independently measured jumping several
    METRES between consecutive updates in places (DIAGNOSIS_ar_m21_walk.md).
    A single such jump backward along the route un-passes whatever the
    walker just walked through. See poc_ar_arrow/ar_arrow_v2.py's
    RouteProgressTracker for the actual fix (a monotonic ratchet on route
    arc-length); this only owns *when* to build a fresh one.

    `path_coords` is the identity `_sticky_route` already reuses/replaces
    per-route (new list object on reroute, same object while unchanged), so
    comparing identity is enough to detect "this is a different route" and
    reset the ratchet - an old route's arc-length has no meaning on a new one.
    """
    if session.ar_route_progress is None or session.ar_route_progress_path is not path_coords:
        from poc_ar_arrow.ar_arrow_v2 import RouteProgressTracker
        session.ar_route_progress = RouteProgressTracker()
        session.ar_route_progress_path = path_coords
    return session.ar_route_progress


def _ar_world(session, localizer_ref, floor_id, pose, x, y, path_coords, num_inliers,
              image_size=None, reproj_error=None, interval_seconds=1.5, timestamp=None):
    """Build the pixel-registered AR payload from the validated arrow PoC.

    Returns None whenever the frame should not carry world-registered geometry
    (weak pose, no usable route ahead, nothing surviving the near clip). Live
    clients may use their screen-fixed guidance for that case; strict replay
    clients hide the AR layer, matching render_poc.py.
    """
    try:
        # Pin route stations in world space: recentering them on each camera
        # fix makes the floor markings slide even with a perfect camera pose.
        # The camera pose itself IS filtered (see _get_pose_stabilizer) - the
        # stabilizer's own retry-with-raw-pose fallback covers the case a
        # smoothed pose would otherwise lag a real turn. `timestamp` lets the
        # stabilizer tell a real tracking dropout from ordinary sampling and
        # reacquire immediately instead of gating the pose that follows one
        # (see PoseStabilizer.reacquire_gap_s) - without it a dropout longer
        # than ~1.5s held a stale pre-dropout rotation over post-dropout video
        # for a few more updates, which read as the AR "tilting"/floating out
        # of sync exactly when tracking resumed.
        stabilizer = _get_pose_stabilizer(session, localizer_ref, floor_id, interval_seconds)
        progress_tracker = _get_route_progress_tracker(session, path_coords)
        payload, reason = ar_service.build_ar_world_poc_debug(
            localizer_ref, floor_id, pose, x, y, path_coords, num_inliers,
            image_size, reproj_error, stabilizer, pin_route=True, timestamp=timestamp,
            progress_tracker=progress_tracker,
        )
        session.last_ar_world_reason = reason
        return payload
    except Exception as exc:  # noqa: BLE001 - AR must never break the processing loop
        _ar_debug(f"[AR] poc_v2_error floor={floor_id}: {type(exc).__name__}: {exc}")
        session.last_ar_world_reason = f'exception:{type(exc).__name__}'
        return None


def _ar_image_size(localizer_ref, frame):
    """Return the image coordinate system used by PnP and the AR payload."""
    reference_size = localization_core.get_reference_image_size_from_intrinsics(
        getattr(localizer_ref, 'K', None)
    )
    return reference_size or (int(frame.shape[1]), int(frame.shape[0]))


def _ar_geometry_metrics(payload: dict | None) -> dict:
    """Measure serialized geometry against the payload's own camera projection.

    This is an offline/backend projection check, not a claim about pixels the
    browser renderer painted. Keeping it separate from ``ar_world_status``
    prevents a non-null JSON payload from being mislabeled as user-visible AR.
    """
    counts = {
        'carets': 0, 'ribbon_quads': 0, 'ribbon_edges': 0,
        'on_screen_carets': 0, 'on_screen_ribbon_quads': 0,
        'on_screen_ribbon_edges': 0, 'destination_marker': 0,
    }
    if not isinstance(payload, dict):
        return {'payload_ready': False, 'geometry_counts': counts, 'projected_geometry': False}
    counts['carets'] = len(payload.get('carets') or payload.get('chevrons') or [])
    counts['ribbon_quads'] = len(payload.get('ribbon_quads') or [])
    counts['ribbon_edges'] = len(payload.get('ribbon_edges') or [])
    counts['destination_marker'] = int(bool(payload.get('destination_marker')))
    try:
        K = np.asarray(payload['K'], dtype=float).reshape(3, 3) if len(payload['K']) == 9 else np.array([
            [payload['K'][0], 0.0, payload['K'][2]],
            [0.0, payload['K'][1], payload['K'][3]],
            [0.0, 0.0, 1.0],
        ], dtype=float)
        R = np.asarray(payload['R'], dtype=float).reshape(3, 3)
        t = np.asarray(payload['t'], dtype=float).reshape(3)
        image_size = payload.get('imgWH') or [0, 0]
        img_w, img_h = int(image_size[0]), int(image_size[1])
        if img_w <= 0 or img_h <= 0:
            raise ValueError('invalid image size')
        rvec, _ = cv2.Rodrigues(R)

        def projected(points):
            values = np.asarray(points, dtype=float).reshape(-1, 3)
            uv, _ = cv2.projectPoints(values, rvec, t, K, np.zeros(4))
            uv = uv.reshape(-1, 2)
            finite = np.isfinite(uv).all(axis=1)
            inside = ((uv[:, 0] >= 0) & (uv[:, 0] < img_w) &
                      (uv[:, 1] >= 0) & (uv[:, 1] < img_h))
            return bool(finite.any() and inside.any())

        for polygon in payload.get('carets') or payload.get('chevrons') or []:
            counts['on_screen_carets'] += int(projected(polygon))
        for item in payload.get('ribbon_quads') or []:
            counts['on_screen_ribbon_quads'] += int(projected(item[0] if isinstance(item, (list, tuple)) and len(item) == 2 else item))
        for edge in payload.get('ribbon_edges') or []:
            counts['on_screen_ribbon_edges'] += int(projected(edge))
    except (KeyError, TypeError, ValueError, IndexError, cv2.error):
        return {'payload_ready': True, 'geometry_counts': counts, 'projected_geometry': False}
    return {
        'payload_ready': True,
        'geometry_counts': counts,
        'projected_geometry': bool(
            counts['on_screen_carets'] or counts['on_screen_ribbon_quads'] or
            counts['on_screen_ribbon_edges']
        ),
    }


# A visual matcher can occasionally return a geometrically plausible PnP
# solution at a completely different map location.  The EKF already rejects
# many of these, but its uncertainty is deliberately wide during re-acquire,
# so a single bad pose can still move the route/AR cue by tens of map pixels.
# At 0.181 m/px, 28 px per sampled update is already about 3.4 m/s at the
# normal 1.5 s replay interval: faster than a person should walk indoors.
# Use a small floor so short intervals are not over-constrained, and scale the
# gate with elapsed video time so genuine movement after a dropped frame can
# still pass.
VISUAL_JUMP_MIN_PX = 28.0
VISUAL_MAX_SPEED_PX_PER_SECOND = 18.0


def _is_implausible_visual_jump(last_fix, raw_x, raw_y, timestamp):
    """Return True when a fresh PnP fix moves impossibly far in one update."""
    if not last_fix:
        return False
    dt = float(timestamp) - float(last_fix.get('timestamp', timestamp))
    if dt <= 0.0:
        return False
    previous_x = last_fix.get('raw_x', last_fix.get('x'))
    previous_y = last_fix.get('raw_y', last_fix.get('y'))
    if previous_x is None or previous_y is None:
        return False
    jump = math.hypot(float(raw_x) - float(previous_x), float(raw_y) - float(previous_y))
    allowed = max(VISUAL_JUMP_MIN_PX, VISUAL_MAX_SPEED_PX_PER_SECOND * dt)
    return jump > allowed


def _ar_world_or_hold(session, timestamp, fresh):
    """Replay has no motion estimate with which to reproject a missing pose.

    Keep the call signature for existing callers, but never draw a previous
    camera over a different video frame. Map/navigation may still hold a fix.
    """
    session.ar_hold = None
    return fresh


def _ar_arrival_only(payload):
    """Remove stale route geometry after arrival while keeping camera/marker data."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    out['carets'] = []
    out['chevrons'] = []
    out['alphas'] = []
    out['ribbon_quads'] = []
    out['ribbon_edges'] = []
    out['arState'] = 'arrived'
    return out


def _sticky_turn(session, x, y, nt):
    """Keep the turn locked to the corner the user is executing.

    next_turn_info re-evaluates every frame from the on-path projection, which
    sits *ahead* of the user (find_best_start_node), so it jumps to the NEXT
    corner while the user is still a few px BEFORE the current one — the turn
    signal then vanishes before the user has turned. This holds the current
    corner (with the real distance to it) until the user has clearly passed it.
    """
    # After completing a corner, deliberately expose a short straight segment
    # before announcing the next corner.  Without this gap, the next_turn_info
    # call sees the following corner immediately and the UI jumps from
    # "Turn Left" straight to "Turn Right" on the same walking beat.
    gap = getattr(session, 'turn_gap', None)
    if gap is not None:
        moved = math.hypot(x - gap['origin'][0], y - gap['origin'][1])
        if moved < gap['min_move']:
            return None
        session.turn_gap = None

    at = getattr(session, 'active_turn', None)
    if at is not None:
        d = math.hypot(x - at['at'][0], y - at['at'][1])
        at['min_dist'] = min(at['min_dist'], d)
        passed = at['min_dist'] < 28.0 and d > 45.0   # reached the corner then moved on
        stray = d > 110.0                             # never got close (reroute) → drop
        if passed or stray:
            session.active_turn = None
            if passed:
                session.turn_gap = {'origin': (float(x), float(y)),
                                    'min_move': 28.0}
                return None
        else:
            return {'dir': at['dir'], 'dist': float(d), 'angle': at['angle'], 'at': at['at']}
    if nt and nt['dist'] < 75.0:
        session.active_turn = {'at': nt['at'], 'dir': nt['dir'],
                               'angle': nt.get('angle', 0.0), 'min_dist': float(nt['dist'])}
    return nt


# A low-but-passable inlier count (10-20) reads as noise, not signal, when the
# walker is on a straight stretch: measured on the M21 walk, the raw PnP
# position in this band swung 2.5-9.7 m between consecutive 0.5s samples
# (poc_ar_arrow/out/DIAGNOSIS_ar_m21_walk.md) - the EKF's own confidence
# buckets already cut that by 3-10x, but treating 10-20 inliers as "normal"
# trust (R_scale 0.5-1.0) still let visible sideways drift through. The same
# band is also what a real corner delivers (motion blur drops inlier count
# during the turn itself), where the fast response is exactly what is needed
# - so the extra damping below applies only when `_sticky_turn` says no turn
# is currently being executed, using last frame's turn state (this frame's
# isn't known yet: route/turn lookup needs the smoothed position this call
# produces). One frame of lag on that signal does not matter at this update
# rate.
STRAIGHT_LOW_CONF_THRESHOLD = 20
# Capped below 5 so the EKF's own confidence buckets (smoothing.py) always
# land this in their heaviest damping tier (R_scale 4x, tightest n_sigma
# outlier gate) rather than the 10-20 range's near-normal-trust tier, which
# measurably only trimmed the M21 straight-stretch jerk a little (median
# 1.60->1.47px) when capped at 8.
STRAIGHT_LOW_CONF_CAP = 4


def _smoother_confidence(session, num_inliers):
    near_turn = getattr(session, 'active_turn', None) is not None
    if near_turn or num_inliers >= STRAIGHT_LOW_CONF_THRESHOLD:
        return num_inliers
    return min(num_inliers, STRAIGHT_LOW_CONF_CAP)


def _sticky_route(session, floor, x, y, dest, dest_floor, deviate_px=55.0):
    """Keep the resolved route locked instead of re-resolving it every frame.

    compute_navigation_route picks the route's start node fresh on every call
    via find_best_start_node, which minimizes (straight-line distance to node +
    remaining route cost) over the nearest few graph nodes. Near a corner this
    heuristic can flip: a node just past the turn has a short straight-line
    distance even though the user still has to physically walk there via the
    nearer, pre-turn node, so its total score can beat the node the user is
    actually standing next to. The route then silently starts past the turn —
    path_coords drops the corridor segment the user is still on — before the
    user has physically reached it, which is exactly why the AR direction can
    read as pointing through a wall/around a corner the user hasn't gotten to.
    Since this is re-evaluated every frame, a moving user can flip back and
    forth across that crossover point, making the displayed path unstable.
    Caching the resolved path and only re-resolving when the user has actually
    drifted off it keeps the route consistent with the ground the user has
    really covered.
    """
    cached = getattr(session, 'route_cache', None)
    if cached and cached['floor'] == floor and cached['dest'] == dest and cached['dest_floor'] == dest_floor:
        pc = cached['route_info']['path_coords']
        if pc:
            _, proj = nav._nearest_on_path(x, y, pc)
            if math.hypot(x - proj[0], y - proj[1]) <= deviate_px:
                return cached['route_info']
    route_info = compute_navigation_route(floor, x, y, dest, dest_floor)
    if route_info:
        session.route_cache = {'floor': floor, 'dest': dest, 'dest_floor': dest_floor, 'route_info': route_info}
    return route_info


# AR end-state thresholds (floor-plan pixels).
ARRIVE_RADIUS_PX = 18.0    # same arrival gate as poc_ar_arrow
ARRIVAL_EXIT_RADIUS_PX = 50.0
OVERSHOOT_MAX_PX = 110.0   # passed the destination but still this close ⇒ "turn around"
# Match poc_ar_arrow's target-pin gate: the Fire Exit/destination landmark is
# useful only as an approach cue, not as a permanent screen decoration.
DESTINATION_MARKER_RADIUS_PX = 90.0
POC_TURN_FAR_PX = 70.0


def _poc_nav_text(ar_state, next_turn):
    """Instruction wording used by poc_ar_arrow's direction card."""
    if ar_state == 'arrived':
        return 'YOU HAVE ARRIVED'
    if next_turn and next_turn.get('dist', float('inf')) < POC_TURN_FAR_PX:
        return 'TURN RIGHT' if next_turn.get('dir', 0) > 0 else 'TURN LEFT'
    return 'GO STRAIGHT'


def _compute_ar_endstate(x, y, destination_coords, dx_m, dy_m, move_dist):
    """Classify the AR end-state for friendly guidance.

    Returns ``(state, dist_to_dest)`` where state is one of
    'navigating' | 'arrived' | 'overshoot'. `dist_to_dest` is None when the
    destination is not on the current floor.
    """
    if not destination_coords:
        return 'navigating', None
    ddx = destination_coords['x'] - x
    ddy = destination_coords['y'] - y
    dist = math.hypot(ddx, ddy)
    if dist <= ARRIVE_RADIUS_PX:
        return 'arrived', dist
    # Overshoot: still near the destination but it now lies *behind* the
    # direction of travel (dot product of travel vector and user→dest < 0).
    if move_dist >= 3.0 and dist <= OVERSHOOT_MAX_PX and (dx_m * ddx + dy_m * ddy) < 0:
        return 'overshoot', dist
    return 'navigating', dist


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS


def _needs_transcode(video_path: Path) -> bool:
    """True for containers/codecs browsers commonly fail to preview: any
    non-mp4 container (.mov/.avi/.mkv), or HEVC video inside an mp4. HEVC has
    no decoder in stock Chromium, and even where a decoder exists (Edge via
    Windows Media Foundation) hardware-decoded video renders black over most
    remote-desktop tools since they can't capture the GPU overlay plane."""
    if video_path.suffix.lower() != '.mp4':
        return True
    capture = cv2.VideoCapture(str(video_path))
    try:
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
        codec = ''.join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)).strip().lower()
        return 'hev' in codec or 'hvc' in codec
    finally:
        capture.release()


def _video_duration_s(video_path: Path) -> float:
    capture = cv2.VideoCapture(str(video_path))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        return frames / fps if fps > 0 else 0.0
    finally:
        capture.release()


def transcode_to_h264(video_path: Path) -> Path:
    """Re-encode to H.264/AAC mp4 for universal browser preview support.
    Raises subprocess.CalledProcessError on ffmpeg failure, or RuntimeError if
    ffmpeg exits cleanly but the output is noticeably shorter than the source
    (observed once under heavy concurrent GPU/CPU load — the encode appears to
    finish normally but stops partway through). Caller decides the fallback
    (e.g. keep serving the original file)."""
    import subprocess
    import imageio_ffmpeg

    output_path = video_path.with_name(video_path.stem + '_h264.mp4')
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [ffmpeg_exe, '-y', '-i', str(video_path),
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
         '-c:a', 'aac', '-movflags', '+faststart',
         str(output_path)],
        check=True, capture_output=True,
    )

    src_duration = _video_duration_s(video_path)
    out_duration = _video_duration_s(output_path)
    if src_duration > 0 and out_duration < src_duration * 0.95:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"transcoded output is truncated ({out_duration:.1f}s of {src_duration:.1f}s source)"
        )

    if video_path != output_path:
        video_path.unlink(missing_ok=True)
    return output_path


def validate_video_file(video_path):
    video_path = Path(video_path)

    if not video_path.exists():
        return False, 'Video file not found', None

    try:
        if video_path.stat().st_size <= 0:
            return False, 'Uploaded video file is empty', None
    except OSError:
        return False, 'Unable to read uploaded video file', None

    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            return False, 'Uploaded video is invalid or incomplete. Please export the file fully before uploading.', None
        success, frame = capture.read()
        if not success or frame is None:
            return False, 'Uploaded video could not be decoded. Please try another file.', None
        fps = capture.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 1.0
        metadata = {
            'fps': float(fps),
            'frame_count': int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
            'width': int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            'height': int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        }
        return True, None, metadata
    finally:
        capture.release()


def extract_frames_from_video(video_path, interval_seconds: float = 1.5):
    """Yield (frame_index, frame, timestamp, read_time) at the given interval (timeline-based)."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 1.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    interval_seconds = max(0.05, float(interval_seconds))

    print(f"Video: {fps:.2f} FPS, {total_frames} frames")
    print(f"Extracting 1 frame every {interval_seconds} seconds (timeline-based sampling)")

    frame_number = 0
    extracted_count = 0
    next_sample_ts = 0.0

    while True:
        read_start = time.time()
        ret, frame = cap.read()
        read_time = time.time() - read_start

        if not ret:
            break

        timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        if timestamp_ms is not None and timestamp_ms >= 0:
            timestamp = float(timestamp_ms) / 1000.0
        else:
            timestamp = frame_number / fps
        timestamp = max(0.0, timestamp)

        if timestamp + 1e-6 >= next_sample_ts:
            yield (extracted_count, frame, timestamp, read_time)
            extracted_count += 1
            while next_sample_ts <= timestamp + 1e-6:
                next_sample_ts += interval_seconds

        frame_number += 1

    cap.release()
    print(f"Extracted {extracted_count} frames from video")


def iter_video_frames(video_path, interval_seconds: float = 1.5):
    """Yield a live-rate frame stream and whether it is a localization tick.

    KLT/PnP needs a continuous stream, but processing a 60 FPS phone clip at
    60 FPS doubles the work without improving the rendered overlay: the
    browser presents at roughly 30 FPS and interpolates the camera payload in
    between updates.  Downsample only high-rate videos to 30 FPS while keeping
    the original timestamps and frame numbers.  The expensive global localizer
    is still requested only at ``interval_seconds`` boundaries.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # Real camera navigation is normally delivered at <=30 FPS.  A number of
    # test clips are 59.94/60 FPS; processing every decoded frame there made
    # the backend fall behind the native clock, so the replay outran AR.
    sample_stride = max(1, int(round(float(fps) / 30.0)))
    interval_seconds = max(0.05, float(interval_seconds))
    frame_number = 0
    next_localize_ts = 0.0
    try:
        while True:
            read_start = time.time()
            ret, frame = cap.read()
            read_time = time.time() - read_start
            if not ret:
                break
            native_frame_number = frame_number
            frame_number += 1
            if sample_stride > 1 and native_frame_number % sample_stride:
                continue
            timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            timestamp = (
                float(timestamp_ms) / 1000.0
                if timestamp_ms is not None and timestamp_ms >= 0
                else frame_number / fps
            )
            timestamp = max(0.0, timestamp)
            should_localize = timestamp + 1e-6 >= next_localize_ts
            if should_localize:
                while next_localize_ts <= timestamp + 1e-6:
                    next_localize_ts += interval_seconds
            yield native_frame_number, frame, timestamp, read_time, should_localize
    finally:
        cap.release()


def build_debug_localization_entry(slot_name: str, result, xy_map, localize_time: float, floor_id: str, localizer_ref=None) -> dict:
    debug_info = result.get('debug_info', {}) if isinstance(result, dict) else {}
    pose = result.get('pose', {}) if isinstance(result, dict) else {}
    success = bool(result.get('success')) if isinstance(result, dict) else False

    position = [float(xy_map[0]), float(xy_map[1])] if xy_map is not None else None
    orientation = None
    if pose and xy_map is not None:
        projector = ar_service.get_projector(floor_id, localizer_ref) if localizer_ref is not None else None
        orientation = calculate_camera_heading(
            pose.get('R'), float(xy_map[0]), float(xy_map[1]), projector
        )
        if orientation is None and pose.get('theta') is not None:
            orientation = normalize_heading_deg(90 - float(pose['theta']))

    return {
        'slot': slot_name,
        'requested_mode': slot_name,
        'effective_mode': result.get('matching_mode', slot_name) if isinstance(result, dict) else slot_name,
        'success': success,
        'localize_time': float(localize_time),
        'position': position,
        'display_position': position,
        'raw_position': position,
        'orientation': orientation,
        'display_orientation': orientation,
        'num_matches': int(debug_info.get('num_matches', result.get('num_matches', 0) if isinstance(result, dict) else 0) or 0),
        'num_inliers': int(debug_info.get('num_inliers', result.get('num_inliers', 0) if isinstance(result, dict) else 0) or 0),
        'matched_keyframe': result.get('matched_keyframe') if isinstance(result, dict) else None,
        'method': result.get('method', 'Unknown') if isinstance(result, dict) else 'Unknown',
        'retrieved_keyframes': debug_info.get('retrieved_keyframes', []),
        'query_keypoints': debug_info.get('query_keypoints', []),
        'timing': debug_info.get('timing', result.get('timing', {}) if isinstance(result, dict) else {}),
        'floor_id': floor_id
    }


def _resolve_destination_coords(route_info: dict, selected_floor: str) -> dict | None:
    destination_node_id = route_info.get('destination_node')
    if not destination_node_id:
        return None
    if state.building_nodes and destination_node_id in state.building_nodes:
        destination_data = state.building_nodes[destination_node_id]
    elif state.nodes and destination_node_id in state.nodes:
        destination_data = state.nodes[destination_node_id]
    else:
        return None
    destination_floor_id = destination_data.get('floor_id', destination_data.get('floor'))
    if destination_floor_id == selected_floor:
        return {'x': float(destination_data['x']), 'y': float(destination_data['y'])}
    return None


def process_navigation(session: NavigationSession, video_path, interval_seconds: float):
    """Run navigation processing in a background thread; pushes events to session.queue."""
    q = session.queue

    _ar_debug(
        f"=== SESSION start dest={session.destination} dest_floor={session.destination_floor} "
        f"start_floor={session.start_floor} ===",
        reset=True,
    )

    continuous_tracker = None
    try:
        is_valid_video, video_error, _ = validate_video_file(video_path)
        if not is_valid_video:
            q.put({'type': 'error', 'message': video_error})
            session.active = False
            return

        total_start_time = time.time()
        frame_times = []
        yaw_bias_deg = 0.0
        last_xy_for_heading = None
        last_display_heading = None
        visual_hold_max_seconds = max(4.0, float(interval_seconds) * 2.5)
        last_visual_fix = None
        lost_streak = 0
        last_hold_warning_frame = -999

        # The floor the client sends is whatever its map happens to be showing
        # (the UI default), not a deliberate choice. Unless it pinned one with
        # auto_floor=false, let the video's own frames decide the start floor and
        # keep the client's floor only as a hypothesis seed — so a floor-5 clip
        # uploaded while the UI sits on floor 1 still localizes on floor 5.
        auto_floor_detection = session.auto_floor or session.start_floor is None
        if auto_floor_detection:
            q.put({'type': 'status', 'message': 'Detecting start floor from first video frame...'})
            selected_floor, inferred_candidates = infer_start_floor_from_video(video_path, return_candidates=True)
            seed_floor_candidates = list(inferred_candidates)
            if session.start_floor and session.start_floor not in seed_floor_candidates:
                seed_floor_candidates.append(session.start_floor)
            if session.start_floor and session.start_floor != selected_floor:
                print(f"[OK] Auto floor: video looks like {selected_floor}, client asked for {session.start_floor}")
        else:
            selected_floor = session.start_floor
            seed_floor_candidates = [selected_floor]

        selected_floor = set_active_floor(selected_floor)
        localizer_ref = state.localizer
        localizer_ref.reset_camera_calibration()
        # Every destination and floor uses the same causal tracker. Prepared
        # scenes under new_ar are offline artifacts and are never read by this
        # production path to select a route or a sample clip.
        continuous_tracker = _CausalPoseTracker(localizer_ref, selected_floor)
        session.current_floor = selected_floor
        if not session.destination_floor:
            session.destination_floor = selected_floor

        dest_node, dest_data = resolve_destination_node(
            session.destination,
            session.destination_floor,
            selected_floor
        )
        if not dest_node:
            q.put({'type': 'error', 'message': f'ไม่พบห้อง {session.destination}'})
            session.active = False
            return

        session.smoother = create_smoother(lc.SMOOTHER_CONFIG['position'])

        print(f"DEBUG: Start event sent for {session.destination}")
        q.put({
            'type': 'start',
            'destination': session.destination,
            'current_floor': selected_floor,
            'destination_floor': session.destination_floor,
            'retrieval_mode': state.retrieval_mode,
            'destination_coords': (
                {'x': dest_data['x'], 'y': dest_data['y']}
                if dest_data and dest_data.get('floor_id', selected_floor) == selected_floor
                else None
            )
        })

        localizer_ref.debug_mode = session.debug_mode
        print("DEBUG: Starting frame extraction...")
        # Replay the uploaded video on its native timeline. This keeps the
        # backend from racing far ahead of the frame visible in the browser and
        # makes every tracker update causal for both reference and generic
        # destinations.
        replay_clock_started = time.perf_counter()
        for frame_idx, frame, timestamp, read_time, should_localize in iter_video_frames(video_path, interval_seconds):
            if not session.active:
                print("DEBUG: Navigation stopped")
                break

            wait_seconds = replay_clock_started + float(timestamp) - time.perf_counter()
            if wait_seconds > 0:
                time.sleep(wait_seconds)

            print(f"DEBUG: Processing frame {frame_idx}")

            loop_start = time.time()
            # Localization is always submitted to the tracker's bounded
            # background worker. This foreground loop only tracks landmarks
            # through frames already received and consumes completed results.
            result, xy = continuous_tracker.step(
                frame, frame_idx, timestamp, should_localize,
            )
            localize_time = 0.0

            tracker_floor = getattr(continuous_tracker, 'floor_id', selected_floor)
            if tracker_floor != selected_floor:
                previous_floor = selected_floor
                selected_floor = tracker_floor
                localizer_ref = continuous_tracker.localizer
                session.current_floor = selected_floor
                session.route_cache = None
                session.active_turn = None
                session.ar_route_progress = None
                session.ar_route_progress_path = None
                session.smoother = create_smoother(lc.SMOOTHER_CONFIG['position'])
                q.put({
                    'type': 'floor_transition',
                    'frame': frame_idx,
                    'timestamp': timestamp,
                    'from_floor': previous_floor,
                    'to_floor': selected_floor,
                    'reason': 'visual_reacquire_current_frame',
                    'tracking_mode': 'causal_klt_pnp',
                })

            # Localizer implementations may return ``None`` on a hard miss.
            # Normalize that outcome before the per-frame navigation logic so a
            # failed keyframe cannot terminate the whole video session.
            if not isinstance(result, dict):
                result = {
                    'success': False,
                    'method': 'Unknown',
                    'num_matches': 0,
                    'num_inliers': 0,
                }
            async_localize_time = float(result.get('async_localize_time', 0.0) or 0.0)

            debug_comparisons = None
            if session.debug_mode and should_localize:
                # Do not run a second synchronous matcher for diagnostics. The
                # worker result is the production measurement and already has
                # source/current frame provenance.
                debug_comparisons = {
                    'orb': build_debug_localization_entry(
                        'production_async', result, xy, localize_time, selected_floor, localizer_ref
                    )
                }

            # Do this after collecting debug data so the rejected match is
            # still visible in diagnostics, but before smoothing/route logic
            # can let it move the displayed position.
            if result.get('success') and xy is not None and _is_implausible_visual_jump(
                last_visual_fix, xy[0], xy[1], timestamp
            ):
                previous_x = last_visual_fix.get('raw_x', last_visual_fix.get('x'))
                previous_y = last_visual_fix.get('raw_y', last_visual_fix.get('y'))
                jump = math.hypot(float(xy[0]) - float(previous_x), float(xy[1]) - float(previous_y))
                dt = max(0.0, float(timestamp) - float(last_visual_fix.get('timestamp', timestamp)))
                allowed = max(VISUAL_JUMP_MIN_PX, VISUAL_MAX_SPEED_PX_PER_SECOND * dt)
                print(
                    f"[WARN] Reject visual jump frame {frame_idx}: "
                    f"{jump:.1f}px in {dt:.2f}s (allowed {allowed:.1f}px)"
                )
                _ar_debug(
                    f"[LOCALIZATION] reject_jump f{frame_idx} "
                    f"jump={jump:.1f}px dt={dt:.2f}s allowed={allowed:.1f}px"
                )
                result = dict(result)
                result['success'] = False
                result['rejection_reason'] = 'implausible_visual_jump'

            if result['success']:
                raw_x, raw_y = xy
                num_inliers = result.get('num_inliers', 0)

                pose = result.get('pose') or {}
                projector = ar_service.get_projector(selected_floor, localizer_ref)
                move_dist = 0.0
                dx_m = dy_m = 0.0
                if last_xy_for_heading is not None:
                    dx_m = raw_x - last_xy_for_heading[0]
                    dy_m = raw_y - last_xy_for_heading[1]
                    move_dist = math.hypot(dx_m, dy_m)
                pnp_heading_deg = calculate_camera_heading(
                    pose.get('R'), raw_x, raw_y, projector
                )
                if pnp_heading_deg is None:
                    raw_orientation_deg = pose.get('theta', 0)
                    pnp_heading_deg = normalize_heading_deg(90 - float(raw_orientation_deg))

                # The camera heading is independent of the direction in which
                # the user happens to be walking. Do not use route/motion
                # displacement as a yaw correction: at a corner it would turn
                # the facing marker before the phone actually turns.
                measured_heading = pnp_heading_deg
                smooth_res = session.smoother.update(
                    raw_x, raw_y, timestamp, _smoother_confidence(session, num_inliers),
                    measured_heading=measured_heading,
                )
                if len(smooth_res) == 2:
                    x, y = smooth_res
                else:
                    x, y, _ = smooth_res
                target_orientation = measured_heading

                if x is None:
                    q.put({'type': 'status', 'message': 'Stabilizing localization...'})
                    print(f"Frame {frame_idx}: Stabilizing...")
                    continue

                if last_display_heading is None:
                    orientation = target_orientation
                else:
                    heading_delta = abs(((target_orientation - last_display_heading + 180.0) % 360.0) - 180.0)
                    if heading_delta >= 30.0:
                        heading_alpha = 0.85
                    elif heading_delta >= 15.0:
                        heading_alpha = 0.65
                    else:
                        heading_alpha = 0.45
                    orientation = blend_heading_deg(last_display_heading, target_orientation, heading_alpha)
                last_display_heading = orientation
                last_xy_for_heading = (raw_x, raw_y)

                last_visual_fix = {
                    'x': float(x), 'y': float(y),
                    'raw_x': float(raw_x), 'raw_y': float(raw_y),
                    'orientation': float(orientation),
                    'timestamp': float(timestamp),
                    'floor_id': selected_floor,
                    'yaw_bias': 0.0
                }
                lost_streak = 0
                print(
                    f"  [Smooth] Pos:({raw_x:.1f},{raw_y:.1f})->({x:.1f},{y:.1f}), "
                    f"Yaw:{pnp_heading_deg:.1f}->{orientation:.1f} bias={yaw_bias_deg:.1f} move={move_dist:.1f}"
                )

                if session.debug_mode and 'debug_info' in result:
                    frame_filename = f"query_{frame_idx:04d}.jpg"
                    cv2.imwrite(str(config.TEMP_FRAMES_FOLDER / frame_filename), frame)

                    if debug_comparisons and 'orb' in debug_comparisons:
                        debug_comparisons['orb']['display_position'] = [float(x), float(y)]
                        debug_comparisons['orb']['display_orientation'] = float(orientation)
                        debug_comparisons['orb']['smoothed_position'] = [float(x), float(y)]
                        debug_comparisons['orb']['smoothed_orientation'] = float(orientation)

                    frames_list = session.debug_data['frames']
                    if len(frames_list) < MAX_DEBUG_FRAMES:
                        frames_list.append({
                            'frame_idx': frame_idx, 'timestamp': timestamp,
                            'frame_path': frame_filename,
                            'localize_time': float(localize_time),
                            'position': (float(x), float(y)),
                            'raw_position': (float(raw_x), float(raw_y)),
                            'retrieved_keyframes': result['debug_info'].get('retrieved_keyframes', []),
                            'query_keypoints': result['debug_info'].get('query_keypoints', []),
                            'num_matches': result['debug_info'].get('num_matches', result.get('num_matches', 0)),
                            'num_inliers': result['debug_info'].get('num_inliers', num_inliers),
                            'inlier_ratio': result['debug_info'].get('inlier_ratio', result.get('inlier_ratio')),
                            'median_reproj_error': result['debug_info'].get('median_reproj_error', result.get('median_reproj_error')),
                            'matched_keyframe': result.get('matched_keyframe'),
                            'method': result.get('method', 'Unknown'),
                            'orientation': float(orientation), 'yaw_bias': float(yaw_bias_deg),
                            'current_floor': selected_floor,
                            'comparison_modes': ['orb', 'superpoint'],
                            'comparisons': debug_comparisons or {},
                            'localization': {'x': float(x), 'y': float(y), 'method': result.get('method', 'Unknown')}
                        })
                        session.debug_data['localization_history'].append((float(x), float(y)))

                session.current_position = {'x': x, 'y': y}
                session.current_orientation = orientation

                route_info = _sticky_route(
                    session, selected_floor, x, y, session.destination, session.destination_floor
                )

                if route_info:
                    path_coords = route_info['path_coords']
                    session.path = path_coords
                    session.path_segments = route_info['segments']
                    destination_coords = _resolve_destination_coords(route_info, selected_floor)
                    session.destination_coords = destination_coords

                    # Travel bearing = path tangent (projection → look-ahead),
                    # NOT user → look-ahead. Measuring from the on-path
                    # projection cancels the user's lateral offset, so the AR
                    # ribbon stays straight along a straight corridor instead of
                    # tilting left/right with position jitter.
                    seg = nav.lookahead_segment(x, y, path_coords) if path_coords else None
                    if seg and seg[0] != seg[1]:
                        direction_angle = calculate_direction(*seg[0], *seg[1])
                    else:
                        direction_angle = orientation

                    # AR ribbon steer = how the route bends ahead (pure geometry,
                    # independent of the noisy PnP yaw). Straight corridor → 0.
                    ar_bearing = nav.path_turn_angle(x, y, path_coords) if path_coords else 0.0
                    # Next real corner + true distance, held sticky through the turn.
                    next_turn = _sticky_turn(session, x, y, nav.next_turn_info(x, y, path_coords)) if path_coords else None
                    # Full route shape ahead in the user's local frame, so the
                    # ribbon renders straight-then-bend-at-the-corner instead of
                    # leaning the whole road early.
                    ar_path = nav.local_path_ahead(x, y, path_coords) if path_coords else []
                    # World-space chevrons + real camera, for the pixel-registered
                    # three.js layer. None on a weak pose ⇒ frontend keeps its
                    # screen-fixed cue, which never depends on the pose.
                    ar_world = _ar_world_or_hold(session, timestamp, _ar_world(
                        session, localizer_ref, selected_floor, result.get('pose'), x, y,
                        path_coords, num_inliers, image_size=_ar_image_size(localizer_ref, frame),
                        reproj_error=result.get('median_reproj_error'),
                        interval_seconds=interval_seconds, timestamp=timestamp,
                    ))
                    tracking_status = result.get('tracking_status', 'tracked')

                    # Arrival / overshoot handling for a user-friendly AR end-state.
                    ar_state, dist_to_dest = _compute_ar_endstate(
                        x, y, destination_coords, dx_m, dy_m, move_dist
                    )
                    # Match the PoC hysteresis: once arrived, keep that state
                    # until the user has clearly walked away from the target.
                    if (
                        getattr(session, 'reached_dest', False)
                        and dist_to_dest is not None
                        and dist_to_dest >= ARRIVAL_EXIT_RADIUS_PX
                    ):
                        session.reached_dest = False
                    if ar_state == 'arrived':
                        session.reached_dest = True
                    if getattr(session, 'reached_dest', False) and ar_state == 'navigating' \
                            and dist_to_dest is not None and dist_to_dest <= ARRIVE_RADIUS_PX * 2:
                        ar_state = 'arrived'
                    nav_text = _poc_nav_text(ar_state, next_turn)

                    if (
                        ar_world is not None
                        and destination_coords is not None
                        and dist_to_dest is not None
                        and dist_to_dest <= DESTINATION_MARKER_RADIUS_PX
                    ):
                        ar_world = ar_service.add_poc_destination_marker(
                            ar_world,
                            localizer_ref,
                            selected_floor,
                            (destination_coords['x'], destination_coords['y']),
                            session.destination,
                            arrived=ar_state == 'arrived',
                            distance_m=(dist_to_dest * ar_service.M_PER_PX)
                            if dist_to_dest is not None else None,
                        )
                    elif isinstance(ar_world, dict):
                        # A held v2 payload may still contain the marker from
                        # the last near-goal frame.  The PoC only draws that
                        # landmark while the current pose is inside its gate.
                        ar_world = dict(ar_world)
                        ar_world.pop('destination_marker', None)

                    # Once the route reaches its destination, never carry the
                    # previous turn/ribbon into the arrival state. Keep the
                    # camera payload so a destination marker can still render,
                    # but clear route geometry and the hold cache.
                    if ar_state == 'arrived':
                        session.ar_hold = None
                        ar_world = _ar_arrival_only(ar_world)

                    ar_metrics = _ar_geometry_metrics(ar_world)
                    if ar_metrics['projected_geometry']:
                        ar_world_status = 'payload_ready'
                    elif ar_world is not None:
                        ar_world_status = 'hidden:no_projected_geometry'
                    else:
                        ar_world_status = f"hidden:{getattr(session, 'last_ar_world_reason', 'unknown')}"

                    _maxlat = max((abs(l) for _f, l in ar_path), default=0.0)
                    _ar_debug(
                        f"[AR] f{frame_idx} VIS fl={selected_floor} pos=({x:.0f},{y:.0f}) "
                        f"start={str(route_info.get('start_node'))[-8:]} "
                        f"bend={ar_bearing:.0f} maxlat={_maxlat:.0f} npath={len(path_coords)} "
                        f"nextturn={next_turn} "
                        f"ar[:4]={[[round(a, 0), round(b, 0)] for a, b in ar_path[:4]]}"
                    )

                    frame_total_time = time.time() - loop_start
                    frame_times.append(frame_total_time)

                    session.history.append({
                        'frame': frame_idx, 'timestamp': timestamp,
                        'x': x, 'y': y, 'raw_x': raw_x, 'raw_y': raw_y,
                        'orientation': orientation, 'yaw_bias': float(yaw_bias_deg),
                        'path': path_coords, 'current_floor': selected_floor,
                        'destination_floor': session.destination_floor,
                        'destination_coords': destination_coords,
                        'path_segments': route_info['segments'],
                        'next_transition': route_info['next_transition'],
                         'method': result.get('method', 'unknown'),
                         'tracking_mode': 'causal_klt_pnp',
                         'tracking_status': tracking_status,
                         'causal_source_frame': result.get('causal_source_frame'),
                         'current_tracking_frame': result.get('current_tracking_frame', frame_idx),
                         'causal_source_timestamp': result.get('causal_source_timestamp'),
                         'async_localize_time': async_localize_time,
                         'pose_age_s': result.get('pose_age_s'),
                         'source_to_current_video_s': result.get('source_to_current_video_s'),
                         'source_to_emit_wall_s': result.get('source_to_emit_wall_s'),
                         'tracks_before': result.get('tracks_before'),
                         'tracks_after': result.get('tracks_after'),
                         'pnp_inliers': result.get('pnp_inliers', result.get('num_inliers')),
                         'pnp_inlier_ratio': result.get('pnp_inlier_ratio', result.get('inlier_ratio')),
                         'pnp_reproj_error': result.get('pnp_reproj_error', result.get('median_reproj_error')),
                         'ar_world': ar_world,
                         'ar_world_status': ar_world_status,
                         'ar_payload_ready': ar_metrics['payload_ready'],
                         'ar_geometry_counts': ar_metrics['geometry_counts'],
                         'ar_projected_geometry': ar_metrics['projected_geometry'],
                        'camera_calibration': localizer_ref.camera_self_calibrator.snapshot(),
                        'processing_time': frame_total_time
                    })

                    q.put({
                        'type': 'update',
                        'frame': frame_idx, 'timestamp': timestamp,
                        'server_timestamp': loop_start * 1000,
                        'position': {'x': x, 'y': y},
                        'raw_position': {'x': raw_x, 'y': raw_y},
                        'orientation': orientation, 'yaw_bias': float(yaw_bias_deg),
                        'current_floor': selected_floor,
                        'destination_floor': session.destination_floor,
                        'destination_coords': destination_coords,
                        'direction': direction_angle,
                        'relative_bearing': (direction_angle - orientation + 180) % 360 - 180,
                        'ar_bearing': ar_bearing,
                        'ar_state': ar_state,
                        'nav_text': nav_text,
                        'ar_path': ar_path,
                        'ar_world': ar_world,
                        'next_turn': next_turn,
                        'dist_to_dest': dist_to_dest,
                        'path': path_coords,
                        'path_segments': route_info['segments'],
                        'next_transition': route_info['next_transition'],
                        'camera_calibration': localizer_ref.camera_self_calibrator.snapshot(),
                        'extract_time': read_time, 'localize_time': localize_time,
                         'processing_time': frame_total_time,
                         'method': result.get('method', 'unknown'),
                         'tracking_mode': 'causal_klt_pnp',
                         'tracking_status': tracking_status,
                         'causal_source_frame': result.get('causal_source_frame'),
                         'current_tracking_frame': result.get('current_tracking_frame', frame_idx),
                         'causal_source_timestamp': result.get('causal_source_timestamp'),
                         'async_localize_time': async_localize_time,
                         'pose_age_s': result.get('pose_age_s'),
                         'source_to_current_video_s': result.get('source_to_current_video_s'),
                         'source_to_emit_wall_s': result.get('source_to_emit_wall_s'),
                         'tracks_before': result.get('tracks_before'),
                         'tracks_after': result.get('tracks_after'),
                         'pnp_inliers': result.get('pnp_inliers', result.get('num_inliers')),
                         'pnp_inlier_ratio': result.get('pnp_inlier_ratio', result.get('inlier_ratio')),
                         'pnp_reproj_error': result.get('pnp_reproj_error', result.get('median_reproj_error')),
                         'ar_world_status': ar_world_status,
                         'ar_payload_ready': ar_metrics['payload_ready'],
                         'ar_geometry_counts': ar_metrics['geometry_counts'],
                         'ar_projected_geometry': ar_metrics['projected_geometry'],
                         'history_length': len(session.history)
                    })
                else:
                    q.put({'type': 'warning', 'message': f'ไม่พบเส้นทางไปยัง {session.destination}'})

            else:
                lost_streak += 1
                hold_age = None
                can_hold = False
                if last_visual_fix is not None:
                    hold_age = float(timestamp) - float(last_visual_fix.get('timestamp', timestamp))
                    can_hold = hold_age <= visual_hold_max_seconds

                if can_hold:
                    held_x = float(last_visual_fix['x'])
                    held_y = float(last_visual_fix['y'])
                    held_orientation = float(last_visual_fix['orientation'])
                    held_floor = last_visual_fix.get('floor_id', selected_floor)
                    last_display_heading = held_orientation

                    session.current_position = {'x': held_x, 'y': held_y}
                    session.current_orientation = held_orientation
                    session.current_floor = held_floor

                    route_info = _sticky_route(
                        session, held_floor, held_x, held_y, session.destination, session.destination_floor
                    )

                    destination_coords = None
                    path_coords = []
                    segments = []
                    next_transition = None
                    direction_angle = held_orientation

                    if route_info:
                        path_coords = route_info['path_coords']
                        segments = route_info['segments']
                        next_transition = route_info['next_transition']
                        session.path = path_coords
                        session.path_segments = segments
                        destination_coords = _resolve_destination_coords(route_info, held_floor)
                        session.destination_coords = destination_coords
                        if path_coords:
                            seg = nav.lookahead_segment(held_x, held_y, path_coords)
                            if seg and seg[0] != seg[1]:
                                direction_angle = calculate_direction(*seg[0], *seg[1])

                    ar_bearing = nav.path_turn_angle(held_x, held_y, path_coords) if path_coords else 0.0
                    ar_path = nav.local_path_ahead(held_x, held_y, path_coords) if path_coords else []
                    next_turn = _sticky_turn(session, held_x, held_y, nav.next_turn_info(held_x, held_y, path_coords)) if path_coords else None
                    # This frame produced no pose, so there is no camera to
                    # register geometry against. Clear world AR immediately;
                    # a held map fix cannot reproject the moving video camera.
                    ar_world = _ar_world_or_hold(session, timestamp, None)
                    ar_world_status = 'hidden:tracking_lost'
                    ar_metrics = _ar_geometry_metrics(ar_world)
                    tracking_status = result.get('tracking_status', 'tracking_lost')
                    # No reliable motion vector while holding ⇒ no overshoot test.
                    ar_state, dist_to_dest = _compute_ar_endstate(
                        held_x, held_y, destination_coords, 0.0, 0.0, 0.0
                    )
                    if (
                        getattr(session, 'reached_dest', False)
                        and dist_to_dest is not None
                        and dist_to_dest >= ARRIVAL_EXIT_RADIUS_PX
                    ):
                        session.reached_dest = False
                    if ar_state == 'arrived':
                        session.reached_dest = True
                    if getattr(session, 'reached_dest', False) and ar_state == 'navigating' \
                            and dist_to_dest is not None and dist_to_dest <= ARRIVE_RADIUS_PX * 2:
                        ar_state = 'arrived'
                    nav_text = _poc_nav_text(ar_state, next_turn)

                    # HOLD_LAST_FIX has no fresh camera pose.  Match
                    # render_poc.py: keep the route state, but do not keep
                    # drawing a stale destination pin during the dropout.
                    if isinstance(ar_world, dict):
                        ar_world = dict(ar_world)
                        ar_world.pop('destination_marker', None)

                    if ar_state == 'arrived':
                        session.ar_hold = None
                        ar_world = _ar_arrival_only(ar_world)

                    _maxlat = max((abs(l) for _f, l in ar_path), default=0.0)
                    _ar_debug(
                        f"[AR] f{frame_idx} HOLD fl={held_floor} pos=({held_x:.0f},{held_y:.0f}) "
                        f"bend={ar_bearing:.0f} maxlat={_maxlat:.0f} npath={len(path_coords)} "
                        f"nextturn={next_turn} "
                        f"ar[:4]={[[round(a, 0), round(b, 0)] for a, b in ar_path[:4]]}"
                    )

                    frame_total_time = time.time() - loop_start
                    frame_times.append(frame_total_time)

                    session.history.append({
                        'frame': frame_idx, 'timestamp': timestamp,
                        'x': held_x, 'y': held_y, 'raw_x': None, 'raw_y': None,
                        'orientation': held_orientation,
                        'yaw_bias': float(last_visual_fix.get('yaw_bias', yaw_bias_deg)),
                        'path': path_coords, 'current_floor': held_floor,
                        'destination_floor': session.destination_floor,
                        'destination_coords': destination_coords,
                        'path_segments': segments, 'next_transition': next_transition,
                         'ar_world': ar_world,
                         'ar_world_status': ar_world_status,
                         'ar_payload_ready': ar_metrics['payload_ready'],
                         'ar_geometry_counts': ar_metrics['geometry_counts'],
                         'ar_projected_geometry': ar_metrics['projected_geometry'],
                         'method': 'HOLD_LAST_FIX', 'tracking_mode': 'causal_klt_pnp',
                         'tracking_status': tracking_status,
                         'causal_source_frame': result.get('causal_source_frame'),
                         'current_tracking_frame': result.get('current_tracking_frame', frame_idx),
                         'async_localize_time': async_localize_time,
                         'pose_age_s': result.get('pose_age_s'),
                         'source_to_current_video_s': result.get('source_to_current_video_s'),
                         'source_to_emit_wall_s': result.get('source_to_emit_wall_s'),
                         'tracks_before': result.get('tracks_before'),
                         'tracks_after': result.get('tracks_after'),
                         'pnp_inliers': result.get('pnp_inliers', result.get('num_inliers')),
                         'pnp_inlier_ratio': result.get('pnp_inlier_ratio', result.get('inlier_ratio')),
                         'pnp_reproj_error': result.get('pnp_reproj_error', result.get('median_reproj_error')),
                         'hold_age': hold_age, 'processing_time': frame_total_time
                    })

                    q.put({
                        'type': 'update',
                        'frame': frame_idx, 'timestamp': timestamp,
                        'server_timestamp': loop_start * 1000,
                        'position': {'x': held_x, 'y': held_y},
                        'raw_position': None,
                        'orientation': held_orientation,
                        'yaw_bias': float(last_visual_fix.get('yaw_bias', yaw_bias_deg)),
                        'current_floor': held_floor,
                        'destination_floor': session.destination_floor,
                        'destination_coords': destination_coords,
                        'direction': direction_angle,
                        'relative_bearing': (direction_angle - held_orientation + 180) % 360 - 180,
                        'ar_bearing': ar_bearing,
                        'ar_state': ar_state,
                        'nav_text': nav_text,
                        'ar_path': ar_path,
                        'ar_world': ar_world,
                        'next_turn': next_turn,
                        'dist_to_dest': dist_to_dest,
                        'path': path_coords,
                        'path_segments': segments, 'next_transition': next_transition,
                        'camera_calibration': localizer_ref.camera_self_calibrator.snapshot(),
                        'extract_time': read_time, 'localize_time': localize_time,
                         'processing_time': frame_total_time,
                         'method': 'HOLD_LAST_FIX', 'tracking_mode': 'hold_last_fix',
                         'tracking_status': tracking_status,
                         'causal_source_frame': result.get('causal_source_frame'),
                         'current_tracking_frame': result.get('current_tracking_frame', frame_idx),
                         'async_localize_time': async_localize_time,
                         'pose_age_s': result.get('pose_age_s'),
                         'source_to_current_video_s': result.get('source_to_current_video_s'),
                         'source_to_emit_wall_s': result.get('source_to_emit_wall_s'),
                         'tracks_before': result.get('tracks_before'),
                         'tracks_after': result.get('tracks_after'),
                         'pnp_inliers': result.get('pnp_inliers', result.get('num_inliers')),
                         'pnp_inlier_ratio': result.get('pnp_inlier_ratio', result.get('inlier_ratio')),
                         'pnp_reproj_error': result.get('pnp_reproj_error', result.get('median_reproj_error')),
                         'ar_world_status': ar_world_status,
                         'ar_payload_ready': ar_metrics['payload_ready'],
                         'ar_geometry_counts': ar_metrics['geometry_counts'],
                         'ar_projected_geometry': ar_metrics['projected_geometry'],
                         'hold_age': hold_age,
                        'history_length': len(session.history)
                    })

                    if frame_idx - last_hold_warning_frame >= 5:
                        q.put({
                            'type': 'warning',
                            'message': 'กำลังใช้ตำแหน่งล่าสุดชั่วคราว กรุณายกกล้องขึ้นมาอีกครั้งเพื่อยืนยันตำแหน่ง'
                        })
                        last_hold_warning_frame = frame_idx

                    print(f"Frame {frame_idx}: hold-last-fix age={hold_age:.1f}s streak={lost_streak}")
                    session.frame_count = frame_idx + 1
                    print(f"Frame {frame_idx}: Processed in {time.time() - loop_start:.4f}s")
                    continue

                if session.debug_mode and 'debug_info' in result:
                    frame_filename = f"query_{frame_idx:04d}.jpg"
                    cv2.imwrite(str(config.TEMP_FRAMES_FOLDER / frame_filename), frame)
                    frames_list = session.debug_data['frames']
                    if len(frames_list) < MAX_DEBUG_FRAMES:
                        frames_list.append({
                            'frame_idx': frame_idx, 'timestamp': timestamp,
                            'frame_path': frame_filename,
                            'localize_time': float(localize_time),
                            'position': None, 'raw_position': None,
                            'retrieved_keyframes': result['debug_info'].get('retrieved_keyframes', []),
                            'query_keypoints': result['debug_info'].get('query_keypoints', []),
                            'num_matches': result['debug_info'].get('num_matches', result.get('num_matches', 0)),
                            'num_inliers': result['debug_info'].get('num_inliers', result.get('num_inliers', 0)),
                            'inlier_ratio': result['debug_info'].get('inlier_ratio', result.get('inlier_ratio')),
                            'median_reproj_error': result['debug_info'].get('median_reproj_error', result.get('median_reproj_error')),
                            'matched_keyframe': result.get('matched_keyframe'),
                            'method': result.get('method', 'Unknown'),
                            'orientation': None, 'current_floor': selected_floor,
                            'comparison_modes': ['orb', 'superpoint'],
                            'comparisons': debug_comparisons or {},
                            'localization': None
                        })

                q.put({
                    'type': 'error', 'frame': frame_idx,
                    'message': 'Localization failed', 'tracking_mode': 'causal_klt_pnp',
                    'tracking_status': result.get('tracking_status', 'tracking_lost'),
                    'reason': result.get('rejection_reason', 'tracking_lost'),
                    'ar_world_status': 'hidden:tracking_lost',
                })

            session.frame_count = frame_idx + 1
            print(f"Frame {frame_idx}: Processed in {time.time() - loop_start:.4f}s")

        total_time = time.time() - total_start_time
        avg_frame_time = sum(frame_times) / len(frame_times) if frame_times else 0

        session.tracking_diagnostics = dict(getattr(continuous_tracker, 'diagnostics', {}) or {})
        q.put({
            'type': 'complete',
            'total_frames': session.frame_count,
            'total_time': total_time,
            'avg_frame_time': avg_frame_time,
            'fps': len(frame_times) / total_time if total_time > 0 else 0,
            'tracking_diagnostics': getattr(continuous_tracker, 'diagnostics', {}),
            'history_limit': session.history.maxlen,
        })

    except Exception as exc:
        _ar_debug(f"[SESSION_ERROR] {type(exc).__name__}: {exc}")
        print(f"[ERROR] Navigation session failed: {type(exc).__name__}: {exc}", flush=True)
        print(traceback.format_exc(), flush=True)
        q.put({'type': 'error', 'message': f'Error: {str(exc)}'})
    finally:
        if continuous_tracker is not None:
            session.tracking_diagnostics = dict(getattr(continuous_tracker, 'diagnostics', {}) or {})
        if continuous_tracker is not None and hasattr(continuous_tracker, 'close'):
            continuous_tracker.close()
        session.active = False
