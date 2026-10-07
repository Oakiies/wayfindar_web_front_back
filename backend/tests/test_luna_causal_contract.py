"""Small contract tests for the live-camera/video navigation boundary."""

from concurrent.futures import Future
from unittest.mock import patch

import numpy as np

from app.services.session import NavigationSession
from app.services.session import ReplayQueue
from app.services import video_processor


def _session() -> NavigationSession:
    return NavigationSession(
        session_id=1,
        destination="Room A",
        destination_floor="floor1",
        video_filename="sample.mp4",
        retrieval_mode="megaloc",
        debug_mode=False,
    )


def test_navigation_history_is_bounded():
    session = _session()
    for frame in range(7000):
        session.history.append({"frame": frame})

    assert len(session.history) == 6000
    assert session.history[0]["frame"] == 1000


def test_route_geometry_is_always_resolved_from_current_pose():
    session = _session()
    session.route_cache = None

    expected = {
        "path_coords": [(10.0, 20.0), (30.0, 40.0)],
        "segments": [],
        "next_transition": None,
    }
    with patch.object(video_processor, "compute_navigation_route", return_value=expected):
        route = video_processor._sticky_route(
            session, "floor1", 10.0, 20.0, "Room A", "floor1"
        )

    assert route["path_coords"] == expected["path_coords"]
    assert not hasattr(session, "reference_route_path")


def test_async_seed_uses_a_camera_matrix_snapshot_without_calibration_callback():
    class FakeLocalizer:
        class Calibrator:
            def active_K(self):
                return np.eye(3)

        camera_self_calibrator = Calibrator()

        def localize(self, frame, **kwargs):
            self.kwargs = kwargs
            return {"success": False}, None

    tracker = object.__new__(video_processor._CausalPoseTracker)
    tracker.localizer = FakeLocalizer()
    matrix = np.eye(3, dtype=np.float64)

    result = tracker._seed(np.zeros((4, 4, 3), dtype=np.uint8), 7, 0.25, matrix, 3)

    assert result["frame"] == 7
    assert result["generation"] == 3
    assert np.array_equal(tracker.localizer.kwargs["camera_K"], matrix)
    assert tracker.localizer.kwargs["calibration_callback"] is not None


def test_stale_worker_result_is_rejected_after_generation_change():
    tracker = object.__new__(video_processor._CausalPoseTracker)
    tracker._pending = Future()
    tracker._pending.set_result({"generation": 1, "frame": 0, "timestamp": 0.0, "work_s": 0.1})
    tracker._generation = 2
    tracker._closed = False
    tracker.diagnostics = {
        "localization_completed": 0,
        "localization_rejected_session": 0,
        "localization_rejected_stale": 0,
        "localization_errors": 0,
    }

    assert tracker._merge_completed_seed(1) is False
    assert tracker.diagnostics["localization_rejected_session"] == 1


def test_ar_geometry_metrics_separates_payload_from_projected_geometry():
    visible = {
        'K': [100.0, 100.0, 50.0, 50.0], 'R': np.eye(3).tolist(),
        't': [0.0, 0.0, 5.0], 'imgWH': [100, 100],
        'carets': [], 'ribbon_quads': [([
            [-0.4, -0.4, 0.0], [0.4, -0.4, 0.0],
            [0.4, 0.4, 0.0], [-0.4, 0.4, 0.0],
        ], 5.0)], 'ribbon_edges': [],
    }
    offscreen = {
        **visible,
        'ribbon_quads': [([
            [100.0, -0.4, 0.0], [101.0, -0.4, 0.0],
            [101.0, 0.4, 0.0], [100.0, 0.4, 0.0],
        ], 5.0)],
    }

    visible_metrics = video_processor._ar_geometry_metrics(visible)
    offscreen_metrics = video_processor._ar_geometry_metrics(offscreen)

    assert visible_metrics['payload_ready'] is True
    assert visible_metrics['projected_geometry'] is True
    assert offscreen_metrics['payload_ready'] is True
    assert offscreen_metrics['projected_geometry'] is False


def test_replay_queue_adds_monotonic_emit_provenance():
    queue = ReplayQueue()
    queue.put({'type': 'update', 'frame': 1})
    queue.put({'type': 'update', 'frame': 2})
    events = queue.recent(2)

    assert events[0]['event_seq'] < events[1]['event_seq']
    assert all(isinstance(event['emit_wall_time_s'], float) for event in events)
