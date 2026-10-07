"""NavigationSession — per-session state for one navigation run.

Ported from navigate_indoor/services/session.py. Two local additions on top of
upstream, both needed by the existing frontend contract:

  * `session_id` is numeric (integer epoch milliseconds) rather than upstream's
    str, so it round-trips exactly through JSON/query strings and the frontend
    can reject stale events without precision loss.
  * `queue` is a `ReplayQueue`, which mirrors every published event into a
    bounded deque so `/api/navigation-stream?replay=N` can hand a reconnecting
    client the events it missed. Producers still see a plain Queue API, so
    video_processor is untouched.
"""
from __future__ import annotations
import queue
import time
from collections import deque
from dataclasses import dataclass, field

# Events kept for replay. The frontend asks for at most 128 on reconnect; 512
# leaves headroom without letting a long run grow this without bound.
REPLAY_BUFFER_SIZE = 512


class ReplayQueue(queue.Queue):
    """Queue that also keeps the last REPLAY_BUFFER_SIZE published events."""

    def __init__(self, maxsize: int = 0):
        super().__init__(maxsize)
        self.published: deque = deque(maxlen=REPLAY_BUFFER_SIZE)
        self._event_seq = 0

    def put(self, item, *args, **kwargs):
        if isinstance(item, dict):
            item = dict(item)
            self._event_seq += 1
            item.setdefault('event_seq', self._event_seq)
            item.setdefault('emit_wall_time_s', time.time())
        self.published.append(item)
        return super().put(item, *args, **kwargs)

    def recent(self, count: int) -> list:
        if count <= 0:
            return []
        events = list(self.published)
        return events[-count:] if count < len(events) else events


@dataclass
class NavigationSession:
    session_id: int
    destination: str
    destination_floor: str
    video_filename: str
    retrieval_mode: str
    debug_mode: bool
    start_floor: str | None = None  # None = auto-detect
    # True = the floor the client sent is only a hint; the video's own frames
    # decide the real start floor. False = the client pinned that floor.
    auto_floor: bool = True

    active: bool = True
    current_floor: str = ''
    current_position: dict | None = None
    current_orientation: float | None = None
    path: list = field(default_factory=list)
    path_segments: list = field(default_factory=list)
    destination_coords: dict | None = None
    reached_dest: bool = False
    active_turn: dict | None = None  # sticky turn locked to the corner being executed
    route_cache: dict | None = None  # resolved route, held until the user leaves it
    ar_hold: dict | None = None      # retained only for compatibility; stale AR is never rendered
    ar_last_ts: float | None = None  # timestamp of the last AR decision
    ar_step_s: float | None = None   # learned gap between updates, for the hold budget
    last_ar_world_reason: str = 'not_evaluated'
    ar_pose_stabilizer: object = None  # poc_ar_arrow v2 pose filter
    ar_pose_stabilizer_floor: str | None = None
    ar_route_progress: object = None   # poc_ar_arrow v2 RouteProgressTracker
    ar_route_progress_path: object = None  # path_coords identity it was built for
    worker_thread: object = None       # processing thread, used to prevent overlapping runs
    frame_count: int = 0
    # Export/debug history must not grow with a long camera session.
    history: deque = field(default_factory=lambda: deque(maxlen=6000))
    debug_data: dict = field(default_factory=lambda: {
        'frames': [],
        'localization_history': [],
        'comparison_modes': ['orb', 'superpoint'],
        'baseline_mode': 'orb'
    })
    smoother: object = None  # KalmanSmoother, initialized in process_navigation
    queue: ReplayQueue = field(default_factory=ReplayQueue)
    tracking_diagnostics: dict | None = None
