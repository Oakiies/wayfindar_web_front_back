"""Video I/O and per-frame navigation orchestration."""
from __future__ import annotations
import math
import time
from pathlib import Path

import cv2
import numpy as np

import app.config as config
from app.services.state import state
from app.services.session import NavigationSession
from app.services.floor_service import set_active_floor
from app.services.localizer_service import get_or_create_comparison_localizer
from app.services.floor_detection import (
    infer_start_floor_from_video,
    rank_floor_candidates_for_frame,
    build_floor_hypothesis_candidates,
    evaluate_floor_hypotheses,
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


def _ar_world(session, localizer_ref, floor_id, pose, x, y, path_coords, num_inliers,
              image_size=None, reproj_error=None):
    """Build the pixel-registered AR payload from the validated arrow PoC.

    Returns None whenever the frame should not carry world-registered geometry
    (weak pose, no usable route ahead, nothing surviving the near clip). Live
    clients may use their screen-fixed guidance for that case; strict replay
    clients hide the AR layer, matching render_poc.py.
    """
    try:
        if getattr(session, 'ar_pose_stabilizer_floor', None) != floor_id:
            from poc_ar_arrow.ar_arrow_v2 import PoseStabilizer

            projector = ar_service.get_projector(floor_id, localizer_ref)
            if projector is None:
                return None
            session.ar_pose_stabilizer = PoseStabilizer(
                alpha=0.24,
                max_jump_m=1.0,
                max_turn_deg=22.0,
                turn_follow_deg=6.0,
                turn_alpha=0.50,
                metres_per_unit=projector.metres_per_unit,
            )
            session.ar_pose_stabilizer_floor = floor_id

        return ar_service.build_ar_world_poc(
            localizer_ref, floor_id, pose, x, y, path_coords, num_inliers,
            image_size, reproj_error, session.ar_pose_stabilizer
        )
    except Exception as exc:  # noqa: BLE001 - AR must never break the processing loop
        _ar_debug(f"[AR] poc_v2_error floor={floor_id}: {type(exc).__name__}: {exc}")
        return None


def _ar_image_size(localizer_ref, frame):
    """Return the image coordinate system used by PnP and the AR payload."""
    reference_size = localization_core.get_reference_image_size_from_intrinsics(
        getattr(localizer_ref, 'K', None)
    )
    return reference_size or (int(frame.shape[1]), int(frame.shape[0]))


# Match the live localization endpoint and offline PoC: keep the last valid
# world payload while a new visual fix is being reacquired. `heldAge` is sent
# with the payload so the frontend can fade confidence instead of clearing all
# carets on a single failed request. A four-frame cutoff made the AR blink at
# exactly the turn where the matcher is most likely to drop a frame.
AR_HOLD_MAX_SECONDS = 3.0

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
    """`fresh` if there is one, else the previous frame while it is still young.

    "Young" is measured against the gap between updates this session is actually
    running at, learned from the timestamps rather than assumed. The held
    payload carries its age so the overlay fades as the hold stretches instead
    of presenting stale geometry as confidently as a live fix.
    """
    ts = float(timestamp)
    prev_ts = getattr(session, 'ar_last_ts', None)
    if prev_ts is not None:
        step = ts - prev_ts
        if 0.01 < step < 10.0:
            known = getattr(session, 'ar_step_s', None)
            session.ar_step_s = step if known is None else (known * 0.7 + step * 0.3)
    session.ar_last_ts = ts

    if fresh is not None:
        session.ar_hold = {'payload': fresh, 'ts': ts}
        return fresh

    held = getattr(session, 'ar_hold', None)
    if not held:
        return None
    budget = AR_HOLD_MAX_SECONDS
    age = ts - held['ts']
    if age > budget:
        session.ar_hold = None
        return None
    out = dict(held['payload'])
    out['heldAge'] = round(min(1.0, age / budget), 3)
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
        seed_floor_candidates = build_floor_hypothesis_candidates(selected_floor, [], seed_floor_candidates, limit=2)
        auto_floor_vote_streak = {}
        auto_floor_rechecks = 0
        selected_floor_probe_succeeded = False
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
        comparison_localizer_ref = None
        if session.debug_mode:
            comparison_localizer_ref = get_or_create_comparison_localizer(selected_floor)
            comparison_localizer_ref.debug_mode = True

        print("DEBUG: Starting frame extraction...")
        for frame_idx, frame, timestamp, read_time in extract_frames_from_video(video_path, interval_seconds):
            if not session.active:
                print("DEBUG: Navigation stopped")
                break

            print(f"DEBUG: Processing frame {frame_idx}")

            loop_start = time.time()
            prefetched_localization = None

            if auto_floor_detection and auto_floor_rechecks < 3:
                rankings = rank_floor_candidates_for_frame(frame)
                hypothesis_candidates = build_floor_hypothesis_candidates(
                    selected_floor, rankings, seed_floor_candidates, limit=2
                )
                if len(hypothesis_candidates) > 1:
                    # Probe the already-selected floor first.  In the common
                    # case this produces the first visual fix without loading
                    # a second floor's full keyframe database.  Only evaluate
                    # alternate floors when the selected floor cannot localize
                    # this frame (for example, after a real floor transition).
                    if selected_floor_probe_succeeded:
                        # Keep the selected floor during EKF warm-up. A single
                        # weak frame must not trigger loading another floor's
                        # full database before the first stable update exists.
                        best_hypothesis = None
                        evaluated_hypotheses = {}
                    else:
                        probe_start = time.time()
                        probe_result, probe_xy = localizer_ref.localize(frame)
                        probe_time = time.time() - probe_start
                        if (
                            isinstance(probe_result, dict)
                            and probe_result.get('success')
                            and probe_xy is not None
                        ):
                            prefetched_localization = {
                                'result': probe_result,
                                'xy': probe_xy,
                                'localize_time': probe_time,
                            }
                            selected_floor_probe_succeeded = True
                            print(
                                f"[OK] Selected-floor fast path: {selected_floor} localized "
                                f"frame {frame_idx} without loading alternate floors"
                            )
                            best_hypothesis = None
                            evaluated_hypotheses = {}
                        else:
                            best_hypothesis, evaluated_hypotheses = evaluate_floor_hypotheses(
                                frame, rankings, hypothesis_candidates
                            )
                    if best_hypothesis is not None:
                        preferred_floor = best_hypothesis['floor_id']
                        preferred_score = best_hypothesis['hypothesis_score']
                        current_hypothesis = evaluated_hypotheses.get(selected_floor)
                        current_score = current_hypothesis['hypothesis_score'] if current_hypothesis else float('-inf')
                        score_margin = preferred_score - current_score

                        if preferred_floor != selected_floor and score_margin >= 15.0:
                            auto_floor_vote_streak[preferred_floor] = auto_floor_vote_streak.get(preferred_floor, 0) + 1
                            print(f"[WARN] Early top-2 check prefers {preferred_floor} over {selected_floor} (margin={score_margin:.2f}, streak={auto_floor_vote_streak[preferred_floor]})")
                            if auto_floor_vote_streak[preferred_floor] >= 2:
                                selected_floor = set_active_floor(preferred_floor)
                                localizer_ref = state.localizer
                                seed_floor_candidates = build_floor_hypothesis_candidates(selected_floor, rankings, seed_floor_candidates, limit=2)
                                if session.debug_mode:
                                    comparison_localizer_ref = get_or_create_comparison_localizer(selected_floor)
                                    comparison_localizer_ref.debug_mode = True
                                session.current_floor = selected_floor
                                auto_floor_vote_streak = {}
                                print(f"[OK] Auto-corrected start floor to {selected_floor}")
                        else:
                            auto_floor_vote_streak = {}

                        prefetched_localization = evaluated_hypotheses.get(selected_floor)
                auto_floor_rechecks += 1

            if prefetched_localization is not None:
                result = prefetched_localization['result']
                xy = prefetched_localization['xy']
                localize_time = prefetched_localization['localize_time']
            else:
                result, xy = localizer_ref.localize(frame)
                localize_time = time.time() - loop_start

            if isinstance(result, dict) and result.get('success') and xy is not None:
                selected_floor_probe_succeeded = True

            debug_comparisons = None
            if session.debug_mode:
                debug_comparisons = {
                    'orb': build_debug_localization_entry(
                        'orb', result, xy, localize_time, selected_floor, localizer_ref
                    )
                }
                if comparison_localizer_ref is not None:
                    comparison_start = time.time()
                    comparison_result, comparison_xy = comparison_localizer_ref.localize(frame)
                    comparison_time = time.time() - comparison_start
                    debug_comparisons['superpoint'] = build_debug_localization_entry(
                        'superpoint', comparison_result, comparison_xy, comparison_time,
                        selected_floor, comparison_localizer_ref
                    )

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
                smooth_res = session.smoother.update(raw_x, raw_y, timestamp, num_inliers, measured_heading=measured_heading)
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
                    ))

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
                        'tracking_mode': 'visual_fix', 'processing_time': frame_total_time
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
                        'extract_time': read_time, 'localize_time': localize_time,
                        'processing_time': frame_total_time,
                        'method': result.get('method', 'unknown'),
                        'tracking_mode': 'visual_fix',
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
                    # register geometry against. Redraw the last AR frame for a
                    # short while (see AR_HOLD_MAX_SECONDS) so brief dropouts do not
                    # read as the overlay flickering; past that it fades and the
                    # screen-fixed guidance carries on alone.
                    ar_world = _ar_world_or_hold(session, timestamp, None)
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
                        'method': 'HOLD_LAST_FIX', 'tracking_mode': 'hold_last_fix',
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
                        'extract_time': read_time, 'localize_time': localize_time,
                        'processing_time': frame_total_time,
                        'method': 'HOLD_LAST_FIX', 'tracking_mode': 'hold_last_fix',
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
                    time.sleep(0.01)
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
                    'message': 'Localization failed', 'tracking_mode': 'lost'
                })

            session.frame_count = frame_idx + 1
            print(f"Frame {frame_idx}: Processed in {time.time() - loop_start:.4f}s")
            time.sleep(0.01)

        total_time = time.time() - total_start_time
        avg_frame_time = sum(frame_times) / len(frame_times) if frame_times else 0

        q.put({
            'type': 'complete',
            'total_frames': session.frame_count,
            'total_time': total_time,
            'avg_frame_time': avg_frame_time,
            'fps': len(frame_times) / total_time if total_time > 0 else 0
        })

    except Exception as exc:
        _ar_debug(f"[SESSION_ERROR] {type(exc).__name__}: {exc}")
        print(f"[ERROR] Navigation session failed: {type(exc).__name__}: {exc}", flush=True)
        q.put({'type': 'error', 'message': f'Error: {str(exc)}'})
    finally:
        session.active = False
