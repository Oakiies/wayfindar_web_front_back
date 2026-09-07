"""Non-blocking, image-only camera self-calibration for live localization.

The first localization is allowed to use the map K.  Good 2D-3D matches are
sent to a one-worker background solver; a new focal is committed only after
several consistent P4Pf estimates pass inlier and reprojection gates.  This
keeps calibration out of the request's critical path and has no dependency on
ARCore, ARKit, or device camera metadata.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from collections import deque
import threading
from typing import Callable

import numpy as np

try:
    import poselib
except ImportError:  # pragma: no cover - exercised only on minimal installs
    poselib = None


def _score_pose(pose, focal: float, points_2d: np.ndarray, points_3d: np.ndarray,
                cx: float, cy: float, threshold: float):
    camera_points = (pose.R @ points_3d.T + pose.t.reshape(3, 1)).T
    valid = camera_points[:, 2] > 1e-8
    errors = np.full(len(points_2d), np.inf, dtype=np.float64)
    centered = points_2d - np.array([cx, cy], dtype=np.float64)
    projected = focal * camera_points[:, :2] / np.maximum(camera_points[:, 2:3], 1e-8)
    errors[valid] = np.linalg.norm(projected[valid] - centered[valid], axis=1)
    inliers = np.flatnonzero(errors <= threshold)
    median_error = float(np.median(errors[inliers])) if len(inliers) else float("inf")
    return len(inliers), median_error


def _solve_p4pf(points_2d: np.ndarray, points_3d: np.ndarray, cx: float, cy: float,
                iterations: int, threshold: float, seed: int):
    if poselib is None or len(points_2d) < 4:
        return None
    centered = points_2d - np.array([cx, cy], dtype=np.float64)
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(iterations):
        sample = rng.choice(len(points_2d), size=4, replace=False)
        try:
            poses, focals = poselib.p4pf(centered[sample], points_3d[sample], True)
        except Exception:
            continue
        for pose, focal in zip(poses, focals):
            if not np.isfinite(focal) or focal <= 0:
                continue
            count, median_error = _score_pose(
                pose, float(focal), points_2d, points_3d, cx, cy, threshold
            )
            key = (count, -median_error)
            if best is None or key > best["key"]:
                best = {"key": key, "focal_px": float(focal),
                        "inliers": count, "median_reproj_error_px": median_error}
    if best is None:
        return None
    best.pop("key", None)
    return best


class CameraSelfCalibrator:
    """Session-level focal estimator whose submit path never waits for solving."""

    def __init__(
        self,
        initial_K: np.ndarray,
        on_commit: Callable[[np.ndarray], None] | None = None,
        min_estimates: int = 3,
        min_inliers: int = 10,
        max_reproj_error_px: float = 8.0,
        max_dispersion: float = 0.12,
        ransac_iterations: int = 200,
    ) -> None:
        self._initial_K = np.asarray(initial_K, dtype=np.float64).copy()
        self._active_K = self._initial_K.copy()
        self._on_commit = on_commit
        self._min_estimates = int(min_estimates)
        self._min_inliers = int(min_inliers)
        self._max_reproj = float(max_reproj_error_px)
        self._max_dispersion = float(max_dispersion)
        self._iterations = int(ransac_iterations)
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="camera-calib")
        self._pending = False
        self._committed = False
        self._status = "provisional" if poselib is not None else "unavailable"
        self._estimates: list[dict] = []
        self._last_error: str | None = None
        self._seen_tokens: deque[object] = deque(maxlen=64)

    def active_K(self) -> np.ndarray:
        with self._lock:
            return self._active_K.copy()

    def submit(self, points_2d, points_3d, frame_token=None) -> bool:
        """Queue one candidate without blocking the localization request."""
        if poselib is None or points_2d is None or points_3d is None:
            return False
        points_2d = np.asarray(points_2d, dtype=np.float64).copy()
        points_3d = np.asarray(points_3d, dtype=np.float64).copy()
        if len(points_2d) < 4 or len(points_2d) != len(points_3d):
            return False
        with self._lock:
            if self._committed or self._pending:
                return False
            if frame_token is not None and frame_token in self._seen_tokens:
                return False
            if frame_token is not None:
                self._seen_tokens.append(frame_token)
            self._pending = True
            self._status = "estimating"
            cx, cy = float(self._initial_K[0, 2]), float(self._initial_K[1, 2])
            future = self._executor.submit(
                _solve_p4pf, points_2d, points_3d, cx, cy,
                self._iterations, self._max_reproj, len(self._estimates) + 17,
            )
            future.add_done_callback(self._finish)
            return True

    def _finish(self, future: Future) -> None:
        try:
            estimate = future.result()
        except Exception as exc:  # pragma: no cover - defensive background boundary
            estimate = None
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
        commit_K = None
        with self._lock:
            self._pending = False
            if estimate is not None and estimate["inliers"] >= self._min_inliers:
                self._estimates.append(estimate)
            if len(self._estimates) >= self._min_estimates:
                focal_values = np.array([item["focal_px"] for item in self._estimates], dtype=np.float64)
                median_focal = float(np.median(focal_values))
                mad = float(np.median(np.abs(focal_values - median_focal)))
                dispersion = mad / max(median_focal, 1e-9)
                if dispersion <= self._max_dispersion:
                    commit_K = self._active_K.copy()
                    commit_K[0, 0] = median_focal
                    commit_K[1, 1] = median_focal
                    self._active_K = commit_K.copy()
                    self._committed = True
                    self._status = "calibrated"
                else:
                    self._status = "provisional"
            elif self._status != "unavailable":
                self._status = "provisional"
        if commit_K is not None and self._on_commit is not None:
            self._on_commit(commit_K)

    def snapshot(self) -> dict:
        with self._lock:
            focal = float(self._active_K[0, 0])
            initial_focal = float(self._initial_K[0, 0])
            values = [float(item["focal_px"]) for item in self._estimates]
            return {
                "status": self._status,
                "committed": self._committed,
                "estimated_parameters": ["fx", "fy"],
                "fixed_parameters": ["cx", "cy"],
                "distortion_model": "not_estimated_in_fast_path",
                "estimates": len(values),
                "pending": self._pending,
                "focal_px": focal,
                "focal_ratio_to_initial": focal / initial_focal if initial_focal else None,
                "focal_mad_px": float(np.median(np.abs(np.asarray(values) - np.median(values)))) if values else None,
                "last_error": self._last_error,
                "blocking_budget_ms": 0.0,
            }

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
