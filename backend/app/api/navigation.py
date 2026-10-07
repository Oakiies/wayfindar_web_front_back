"""Navigation session endpoints and the SSE stream.

FastAPI port of navigate_indoor/api/navigation.py, on upstream's per-session
model (`state.sessions` + `NavigationSession.queue`) rather than the single
global navigation_state this backend used before.

Two endpoints go beyond upstream because the existing frontend depends on them:
`/api/navigation-state` (1 Hz poll used as a fallback when SSE is blocked) and
`?replay=` on the stream (backfill after a reconnect). Both are derived from the
session, so they add no state of their own.
"""
import asyncio
import json
import queue
import threading
import time

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

import app.config as config
from app.services.state import state
from app.services.session import NavigationSession
from app.services.floor_service import set_active_floor
from app.services.video_processor import validate_video_file, process_navigation
from app.utils.server import log_status

router = APIRouter()


def _as_bool(value, default: bool = False) -> bool:
    """JSON booleans arrive as bool, but older clients send '1'/'true' strings."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _resolve_session(session_id):
    """Session lookup that tolerates the id arriving as a string over a query param."""
    if session_id is None or session_id == '':
        return state.get_latest_session()
    try:
        key = float(session_id)
    except (TypeError, ValueError):
        return None
    session = state.sessions.get(key)
    if session is not None:
        return session

    # Older runs used ``time.time()`` directly, so clients which stringify the
    # JSON number with fewer decimal places can differ by a few microseconds.
    # Keep those reconnects working while new runs use integer milliseconds.
    return next(
        (candidate for sid, candidate in state.sessions.items() if abs(float(sid) - key) < 0.05),
        None,
    )


def _session_event(event: dict, session_id: int) -> dict:
    """Attach the owning session id without mutating the queue/history item."""
    return {**event, 'session_id': session_id}


@router.post('/api/start-navigation')
def start_navigation(payload: dict = Body(default={})):
    data = payload or {}

    # The HTTP server binds before heavy GPU/model initialization finishes.
    # Refuse to start a session until /healthz says ready so frame zero never
    # pays model-loading cost or races a partially initialized localizer.
    if state.localizer is None or state.graph is None:
        return JSONResponse(
            {'success': False, 'error': 'Navigation backend is still preparing',
             'ready': False, 'retry_after_ms': 250},
            status_code=503,
        )

    video_filename = data.get('video_filename')
    destination = data.get('destination')
    # Global localization is a keyframe operation. Native video frames are
    # propagated by the KLT/PnP tracker in video_processor between these
    # requests, matching the real camera cadence without uploading 30 FPS to
    # the backend.
    interval = float(data.get('interval') or 1.5)
    debug_mode = bool(data.get('debug_mode', False))
    requested_start_floor = data.get('start_floor') or data.get('floor_id')
    start_floor = requested_start_floor or None
    # The frontend always sends the floor it happens to be showing, which is the
    # UI default (floor1) rather than a deliberate choice. Treat that as a hint:
    # unless the client explicitly pins the floor with auto_floor=false, the
    # video's own frames decide the start floor (see process_navigation).
    auto_floor = _as_bool(data.get('auto_floor'), default=True)
    destination_floor = (
        data.get('destination_floor')
        or requested_start_floor
        or state.current_floor_id
        or state.default_floor_id
    )

    if not video_filename or not destination:
        return JSONResponse({'error': 'Missing required parameters'}, status_code=400)

    # The built-in demo is stored outside uploads so it is never overwritten
    # by a user upload. All other values continue to resolve inside uploads.
    if str(video_filename) == config.DEMO_VIDEO_FILENAME:
        video_path = config.DEMO_VIDEO_PATH
    else:
        video_path = config.UPLOAD_FOLDER / str(video_filename)
    if not video_path.exists():
        return JSONResponse({'error': 'Video file not found'}, status_code=404)

    is_valid_video, video_error, _ = validate_video_file(video_path)
    if not is_valid_video:
        return JSONResponse({'error': video_error}, status_code=400)

    if start_floor:
        start_floor = set_active_floor(start_floor)
        destination_floor = destination_floor or start_floor

    # Integer epoch milliseconds round-trip exactly through JSON/JavaScript and
    # query strings. A fractional epoch timestamp could be rounded by clients,
    # causing polling and SSE reconnects to miss the session they just started.
    session_id = int(time.time() * 1000)

    # Deactivate and drain the previous worker before touching the global
    # floor/localizer again. Merely flipping ``active`` allowed its in-flight
    # localization to publish one stale frame into the next run.
    prev_session = state.get_latest_session()
    if prev_session:
        prev_session.active = False
        prev_worker = getattr(prev_session, 'worker_thread', None)
        if prev_worker is not None and prev_worker.is_alive():
            prev_worker.join(timeout=5.0)
            if prev_worker.is_alive():
                return JSONResponse(
                    {'error': 'Previous navigation is still stopping; try again in a moment'},
                    status_code=409,
                )
        state.sessions.pop(prev_session.session_id, None)

    session = NavigationSession(
        session_id=session_id,
        destination=destination,
        destination_floor=destination_floor,
        video_filename=str(video_filename),
        retrieval_mode=state.retrieval_mode,
        debug_mode=debug_mode,
        start_floor=start_floor,
        auto_floor=auto_floor,
    )
    state.sessions[session_id] = session

    thread = threading.Thread(
        target=process_navigation,
        args=(session, video_path, interval),
        daemon=True,
    )
    session.worker_thread = thread
    thread.start()

    log_status('NAV', f'Navigation started -> {destination} (session={session_id})')

    return {
        'success': True,
        'message': 'Navigation started',
        'session_id': session_id,
        'start_floor': start_floor,
        'auto_floor': auto_floor,
        'destination_floor': destination_floor,
        'retrieval_mode': state.retrieval_mode,
    }


@router.post('/api/stop-navigation')
def stop_navigation(payload: dict = Body(default={})):
    session = _resolve_session((payload or {}).get('session_id'))
    if session:
        session.active = False
        worker = getattr(session, 'worker_thread', None)
        if worker is not None and worker.is_alive():
            worker.join(timeout=0.5)
        still_stopping = worker is not None and worker.is_alive()
        if not still_stopping and session.tracking_diagnostics is None:
            state.sessions.pop(session.session_id, None)
        return {'success': True, 'stopping': still_stopping}
    return {'success': True, 'stopping': False}


@router.get('/api/navigation-state')
def navigation_state(session_id: str | None = Query(None)):
    """
    Snapshot of the current run, for clients polling instead of reading the SSE
    stream. Not part of upstream — derived here from the session so the two
    views can never disagree.
    """
    session = _resolve_session(session_id)
    if session is None:
        return {
            'active': False,
            'session_id': None,
            'position': None,
            'orientation': None,
            'current_floor': None,
            'destination': None,
            'destination_floor': None,
            'path': [],
            'path_segments': [],
            'frame_count': 0,
            'history_length': 0,
            'method': None,
            'tracking_mode': None,
            'last_update': None,
            'retrieval_mode': state.retrieval_mode,
        }

    last = session.history[-1] if session.history else {}
    last_update = next(
        (event for event in reversed(session.queue.recent(64)) if event.get('type') == 'update'),
        None,
    )
    if last_update is not None:
        last_update = _session_event(last_update, session.session_id)
    return {
        'active': session.active,
        'session_id': session.session_id,
        'position': session.current_position,
        'orientation': session.current_orientation,
        'current_floor': session.current_floor or None,
        'destination': session.destination,
        'destination_floor': session.destination_floor,
        'path': session.path,
        'path_segments': session.path_segments,
        'destination_coords': session.destination_coords,
        'frame_count': session.frame_count,
        'history_length': len(session.history),
        'method': last.get('method'),
        'tracking_mode': last.get('tracking_mode'),
        'last_update': last_update,
        'video_filename': session.video_filename,
        'retrieval_mode': session.retrieval_mode,
        'debug_mode': session.debug_mode,
        'reached_dest': session.reached_dest,
        'tracking_diagnostics': session.tracking_diagnostics,
    }


@router.get('/api/navigation-stream')
async def navigation_stream(
    request: Request,
    session_id: str | None = Query(None),
    replay: int = Query(0),
):
    session = _resolve_session(session_id)
    if session is None:
        return JSONResponse({'error': 'No active navigation session'}, status_code=404)

    q = session.queue
    sid = session.session_id
    backlog = q.recent(replay)

    async def event_stream():
        finished = False
        try:
            for event in backlog:
                yield f"data: {json.dumps(_session_event(event, sid))}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # get() blocks, so it runs off the event loop; otherwise a
                    # single stream would stall every other request on the server.
                    update = await asyncio.to_thread(q.get, True, 1)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue

                yield f"data: {json.dumps(_session_event(update, sid))}\n\n"
                utype = update.get('type')
                if utype == 'complete':
                    finished = True
                    break
                # Per-frame localization misses carry a 'frame' key and are
                # transient (video often starts on a bad frame). They must NOT
                # close the stream. Only fatal errors (no 'frame') terminate.
                if utype == 'error' and 'frame' not in update:
                    finished = True
                    break
        finally:
            # Upstream drops the session whenever the generator exits. Here the
            # client is allowed to reconnect with ?replay=, so only a run that
            # actually ended releases it — a dropped connection must not delete
            # the state the client is about to come back for.
            if finished:
                state.sessions.pop(sid, None)

    return StreamingResponse(
        event_stream(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@router.get('/api/export-trajectory')
def export_trajectory(session_id: str | None = Query(None)):
    session = _resolve_session(session_id)

    if session is None or not session.history:
        return JSONResponse({'error': 'No trajectory data available'}, status_code=404)

    return {
        'video': session.video_filename,
        'destination': session.destination,
        'current_floor': session.current_floor,
        'destination_floor': session.destination_floor,
        'path_segments': session.path_segments,
        'history': list(session.history),
    }
