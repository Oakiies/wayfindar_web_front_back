"""Live-localize and retrieval-mode endpoints.

FastAPI port of navigate_indoor/api/localization.py — same logic, same response
shape; only request parsing differs (Form/UploadFile instead of request.files /
request.form).
"""
import math
import time

import cv2
import numpy as np
from fastapi import APIRouter, Body, File, Form, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import app.config as config
import app.core.localization as localization_core
from app.services.state import state
from app.services.floor_service import set_active_floor
from app.services.ar_service import get_projector
from app.services.floor_detection import (
    infer_start_floor_from_frame,
    rank_floor_candidates_for_frame,
    get_top_floor_candidates,
    evaluate_floor_hypotheses,
)
from app.services.localizer_service import switch_retrieval_mode
from app.services.nav_service import compute_navigation_route
from app.utils.heading import normalize_heading_deg, calculate_direction, calculate_camera_heading

# poc_ar_arrow/ar_arrow_v2.py is a candidate replacement for the shipping AR
# overlay (continuous floor ribbon + carets, PoseStabilizer for jitter) — it
# was previously only wired into the offline video-replay path
# (app/services/video_processor.py). Reusing it here, unmodified, so the live
# camera loop can serve the same geometry; this only ADDS an optional
# `ar_world_v2` field to the response, nothing existing changes shape.
from poc_ar_arrow.ar_arrow_v2 import (
    build_ar_world_v2,
    PoseStabilizer,
    route_guidance_mode,
)

router = APIRouter()


def _finite_or(value, fallback=None):
    """Keep failed-localization responses JSON-compliant when a solver returns inf/NaN."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if math.isfinite(numeric) else fallback

# One stabilizer per process, not per-session — this endpoint has no session
# concept today (state.localizer etc. are already process-global), so this
# matches the existing pattern rather than introducing a new one.
_ar_stabilizer = None
_ar_stabilizer_floor = None
# Live localization can succeed while the stricter floor-AR gates reject the
# same frame. Keep the last trustworthy world payload briefly so one weak frame
# does not make the AR scene disappear between otherwise valid fixes.
AR_WORLD_HOLD_SECONDS = 3.0
_ar_world_holds = {}
# Keep the complete navigation state together with the world payload. A failed
# localization request must not make the browser clear the last registered AR
# scene; it should receive the same last-fix state used by the streaming path.
_live_state_holds = {}


def _ar_world_hold_key(floor_id, destination, destination_floor):
    return (str(floor_id or ''), str(destination or ''), str(destination_floor or ''))


def _get_held_ar_world(key):
    held = _ar_world_holds.get(key)
    if not held:
        return None
    age = time.monotonic() - held['timestamp']
    if age > AR_WORLD_HOLD_SECONDS:
        _ar_world_holds.pop(key, None)
        return None
    payload = dict(held['payload'])
    payload['heldAge'] = round(min(1.0, max(0.0, age / AR_WORLD_HOLD_SECONDS)), 3)
    return payload


def _remember_ar_world(key, payload):
    _ar_world_holds[key] = {
        'payload': dict(payload),
        'timestamp': time.monotonic(),
    }
    return payload


def _get_held_live_state(key):
    held = _live_state_holds.get(key)
    if not held:
        return None
    age = time.monotonic() - held['timestamp']
    if age > AR_WORLD_HOLD_SECONDS:
        _live_state_holds.pop(key, None)
        return None
    payload = dict(held['payload'])
    payload['hold_age'] = round(min(AR_WORLD_HOLD_SECONDS, max(0.0, age)), 3)
    return payload


def _remember_live_state(key, payload):
    _live_state_holds[key] = {
        'payload': dict(payload),
        'timestamp': time.monotonic(),
    }
    return payload


def _get_ar_stabilizer(floor_id, localizer):
    global _ar_stabilizer, _ar_stabilizer_floor
    projector = get_projector(floor_id, localizer)
    metres_per_unit = projector.metres_per_unit if projector is not None else 1.0
    if _ar_stabilizer is None or _ar_stabilizer_floor != floor_id:
        _ar_stabilizer = PoseStabilizer(
            alpha=0.24,
            max_jump_m=1.0,
            max_turn_deg=22.0,
            turn_follow_deg=6.0,
            turn_alpha=0.50,
            expected_interval_s=1.0,
            metres_per_unit=metres_per_unit,
        )
        _ar_stabilizer_floor = floor_id
    return _ar_stabilizer


def _point3(p) -> list:
    # ar_geometry.FloorProjector.floor_point/direction return full 3D world
    # points (floor plane has a Z), not 2D — ArFloorThreeOverlay's
    # buildWorldChevronGeometry indexes points[0..2] as [x,y,z] triples.
    arr = np.asarray(p, float).reshape(-1)
    return [float(arr[0]), float(arr[1]), float(arr[2])]


def _serialize_ar_world_v2(payload: dict) -> dict:
    """Match frontend-v3's ArWorldPayload shape exactly (navigationTestService.ts)
    — ArFloorThreeOverlay already has a complete, dormant renderer for this
    exact payload (ribbon_quads/ribbon_edges/carets, arVersion check), built
    for this integration but never fed real data until now."""
    K = payload['K']
    return {
        'arVersion': 'poc_ar_arrow_v2',
        'K': [float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])],
        'R': [[float(v) for v in row] for row in payload['R']],
        't': [float(v) for v in np.asarray(payload['t']).reshape(3)],
        'imgWH': [int(payload['imgWH'][0]), int(payload['imgWH'][1])],
        'metres_per_unit': float(payload['metres_per_unit']),
        'pdr_anchor_map': [float(v) for v in payload['pdr_anchor_map']],
        'pdr_map_x_axis_world': [float(v) for v in payload['pdr_map_x_axis_world']],
        'pdr_map_y_axis_world': [float(v) for v in payload['pdr_map_y_axis_world']],
        'chevrons': [],  # worldCarets prefers `carets` when present, see ARFloorThreeOverlay.tsx
        'marker': False,
        'ribbon_quads': [
            [[_point3(p) for p in quad], float(depth)]
            for quad, depth in payload['ribbon_quads']
        ],
        'ribbon_edges': [
            [_point3(p) for p in payload['ribbon_edges'][0]],
            [_point3(p) for p in payload['ribbon_edges'][1]],
        ],
        'carets': [[_point3(p) for p in poly] for poly in payload['carets']],
        'alphas': [float(a) for a in payload['alphas']],
        # Guidance metadata is intentionally additive. The frontend can use
        # this to label/debug the difference between a shallow corridor bend
        # and a discrete directional turn; geometry remains backward-compatible.
        'guidance_mode': payload.get('guidance_mode', 'directional'),
        'local_bend_deg': float(payload.get('local_bend_deg', 0.0)),
    }


def _serialize_tracking_seed(result: dict, localizer, image) -> dict | None:
    """Expose the current server fix as a browser-side KLT/PnP seed.

    The seed is produced only from the frame that was just localized.  It is
    never a future frame or a pre-rendered trajectory.  Map-point IDs are
    retained so the browser can keep each 2D track attached to the same 3D
    point while the camera moves.
    """
    points_2d = result.get('_tracking_points_2d')
    points_3d = result.get('_tracking_points_3d')
    point_ids = result.get('_tracking_mp_ids')
    if points_2d is None or points_3d is None:
        return None

    points_2d = np.asarray(points_2d, dtype=np.float64).reshape(-1, 2)
    points_3d = np.asarray(points_3d, dtype=np.float64).reshape(-1, 3)
    if point_ids is None:
        point_ids = np.full((len(points_2d),), -1, dtype=np.int64)
    point_ids = np.asarray(point_ids, dtype=np.int64).reshape(-1)
    count = min(len(points_2d), len(points_3d), len(point_ids))
    if count < 6:
        return None

    finite = (
        np.isfinite(points_2d[:count]).all(axis=1)
        & np.isfinite(points_3d[:count]).all(axis=1)
        & (point_ids[:count] >= 0)
    )
    if int(finite.sum()) < 6:
        return None
    points_2d = points_2d[:count][finite]
    points_3d = points_3d[:count][finite]
    point_ids = point_ids[:count][finite]

    try:
        K = np.asarray(localizer.camera_self_calibrator.active_K(), dtype=np.float64)
    except Exception:
        K = np.asarray(localizer.K, dtype=np.float64)
    img_wh = localization_core.get_reference_image_size_from_intrinsics(K)
    if img_wh is None:
        img_wh = (int(image.shape[1]), int(image.shape[0]))

    floor_projection = None
    floor_config = getattr(localizer, 'floor_config', None)
    H_matrix = getattr(localizer, 'H_matrix', None)
    if isinstance(floor_config, dict) and H_matrix is not None:
        try:
            floor_projection = {
                'traj_center': [float(v) for v in floor_config['traj_center']],
                'floor_v1': [float(v) for v in floor_config['floor_v1']],
                'floor_v2': [float(v) for v in floor_config['floor_v2']],
                'H': [[float(v) for v in row] for row in np.asarray(H_matrix, dtype=np.float64)],
            }
        except (KeyError, TypeError, ValueError):
            floor_projection = None

    return {
        'points_2d': [[float(v) for v in p] for p in points_2d],
        'points_3d': [[float(v) for v in p] for p in points_3d],
        'map_point_ids': [int(v) for v in point_ids],
        'K': [float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])],
        'imgWH': [int(img_wh[0]), int(img_wh[1])],
        'floor_projection': floor_projection,
        'quality': {
            'num_points': int(len(points_2d)),
            'num_inliers': int(result.get('num_inliers', 0) or 0),
            'inlier_ratio': _finite_or(result.get('inlier_ratio', 0.0), 0.0),
            'median_reproj_error': _finite_or(result.get('median_reproj_error')),
        },
    }


@router.post('/api/live-localize')
async def api_live_localize(
    frame: UploadFile = File(None),
    floor_id: str = Form(''),
    destination: str = Form(''),
    destination_floor: str = Form(''),
    auto_floor: str = Form('1'),
    frame_id: str = Form(''),
    capture_time_ms: str = Form(''),
):
    if state.localizer is None:
        return JSONResponse(
            {'success': False, 'error': 'Navigation backend is still preparing',
             'ready': False, 'retry_after_ms': 250},
            status_code=503,
        )
    if frame is None:
        return JSONResponse({'success': False, 'error': 'Missing frame file'}, status_code=400)

    frame_bytes = await frame.read()
    if not frame_bytes:
        return JSONResponse({'success': False, 'error': 'Empty frame payload'}, status_code=400)

    np_buffer = np.frombuffer(frame_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if image is None:
        return JSONResponse({'success': False, 'error': 'Failed to decode frame'}, status_code=400)

    requested_floor = (floor_id or '').strip() or None
    # The client sends the floor its map is showing, which is usually the UI
    # default rather than where the user actually is. auto_floor keeps that as a
    # hint: if it fails to localize there, re-rank the floors from this frame.
    auto_floor_enabled = str(auto_floor).strip().lower() in ('1', 'true', 'yes', 'on')
    destination = (destination or '').strip() or None
    destination_floor = (destination_floor or '').strip() or None

    # This whole block is CPU/GPU-bound (image retrieval, feature matching, PnP,
    # sometimes a cold model load for a not-yet-cached floor) and used to run
    # synchronously inside this `async def` handler, blocking the single asyncio
    # event loop — every other request (even a plain GET like /api/map-image)
    # would queue up and stall for as long as this took. run_in_threadpool moves
    # it off the event loop so the server stays responsive to concurrent requests.
    try:
        if requested_floor:
            selected_floor = await run_in_threadpool(set_active_floor, requested_floor)
        else:
            inferred_floor = await run_in_threadpool(infer_start_floor_from_frame, image)
            selected_floor = await run_in_threadpool(set_active_floor, inferred_floor)
    except Exception as exc:
        return JSONResponse({'success': False, 'error': f'Failed to set active floor: {exc}'},
                            status_code=500)

    localizer_ref = state.localizer
    if localizer_ref is None:
        return JSONResponse({'success': False, 'error': 'Localizer is not initialized'},
                            status_code=500)
    localizer_ref.debug_mode = False

    localize_start = time.time()
    result, xy = await run_in_threadpool(
        localizer_ref.localize, image, True,
    )
    localize_time = time.time() - localize_start

    if auto_floor_enabled and requested_floor and not (result.get('success') and xy is not None):
        rankings = await run_in_threadpool(rank_floor_candidates_for_frame, image)
        # The requested floor was already tried and failed. Evaluate the best
        # other floor first, and only cold-load a second candidate if needed.
        # This keeps the normal cross-floor recovery to one Localizer load.
        candidates = [
            floor_id for floor_id in get_top_floor_candidates(rankings, limit=2)
            if floor_id != selected_floor
        ]
        if not candidates:
            candidates = [selected_floor]
        best = None
        for candidate_floor_id in candidates:
            candidate_best, _evaluated = await run_in_threadpool(
                evaluate_floor_hypotheses, image, rankings, [candidate_floor_id]
            )
            if candidate_best is not None:
                best = candidate_best
            if best is not None and best['success']:
                break
        if best is not None and best['success'] and best['floor_id'] != selected_floor:
            print(f"[OK] Auto floor: switched {selected_floor} -> {best['floor_id']} "
                  f"(inliers={best['num_inliers']}, ret={best['retrieval_score']:.4f})")
            selected_floor = await run_in_threadpool(set_active_floor, best['floor_id'])
            localizer_ref = state.localizer
            localizer_ref.debug_mode = False
            # Re-run the winning floor with correspondences enabled.  The
            # candidate ranking path is intentionally lightweight and does not
            # retain the 2D-3D pairs needed to seed browser tracking.
            result, xy = await run_in_threadpool(
                localizer_ref.localize, image, True,
            )
        localize_time = time.time() - localize_start

    if not result.get('success') or xy is None:
        hold_key = _ar_world_hold_key(selected_floor, destination, destination_floor)
        held_state = _get_held_live_state(hold_key)
        if held_state is not None:
            held_state['success'] = True
            held_state['method'] = 'HOLD_LAST_FIX'
            held_state['tracking_mode'] = 'hold_last_fix'
            held_state['ar_world_status'] = 'held_last_world_pose'
            held_state['localize_time'] = _finite_or(localize_time, 0.0)
            held_state['num_inliers'] = int(result.get('num_inliers', 0) or 0)
            held_state['num_matches'] = int(result.get('num_matches', 0) or 0)
            held_state['inlier_ratio'] = _finite_or(result.get('inlier_ratio', 0.0), 0.0)
            held_state['median_reproj_error'] = _finite_or(result.get('median_reproj_error'))
            held_state['message'] = 'Localization failed; holding last valid fix'
            held_ar_world = _get_held_ar_world(hold_key)
            if held_ar_world is not None:
                held_state['ar_world'] = held_ar_world
            return held_state
        return {
            'success': False,
            'floor_id': selected_floor,
            'localize_time': _finite_or(localize_time, 0.0),
            'method': result.get('method', 'unknown'),
            'num_inliers': int(result.get('num_inliers', 0) or 0),
            'num_matches': int(result.get('num_matches', 0) or 0),
            'inlier_ratio': _finite_or(result.get('inlier_ratio', 0.0), 0.0),
            'median_reproj_error': _finite_or(result.get('median_reproj_error')),
            'message': 'Localization failed',
        }

    x, y = float(xy[0]), float(xy[1])
    pose = result.get('pose') or {}
    projector = get_projector(selected_floor, localizer_ref)
    orientation = calculate_camera_heading(
        pose.get('R'), x, y, projector
    )
    if orientation is None:
        # Compatibility fallback for legacy pose records without R/projector.
        raw_orientation = pose.get('theta', 0)
        orientation = normalize_heading_deg(90 - float(raw_orientation))

    route_info = None
    path_coords = []
    path_segments = []
    destination_coords = None
    direction_angle = orientation

    if destination:
        route_info = compute_navigation_route(selected_floor, x, y, destination, destination_floor)
        if route_info:
            path_coords = route_info.get('path_coords') or []
            path_segments = route_info.get('segments') or []

            destination_node_id = route_info.get('destination_node')
            if destination_node_id:
                if state.building_nodes and destination_node_id in state.building_nodes:
                    destination_data = state.building_nodes[destination_node_id]
                elif state.nodes and destination_node_id in state.nodes:
                    destination_data = state.nodes[destination_node_id]
                else:
                    destination_data = None

                if destination_data is not None:
                    destination_floor_id = destination_data.get('floor_id', destination_data.get('floor'))
                    if destination_floor_id == selected_floor:
                        destination_coords = {
                            'x': float(destination_data['x']),
                            'y': float(destination_data['y']),
                        }

            if len(path_coords) > 0:
                target_x, target_y = path_coords[0]
                for point in path_coords:
                    if len(point) < 2:
                        continue
                    candidate_x, candidate_y = float(point[0]), float(point[1])
                    if math.hypot(candidate_x - x, candidate_y - y) > 1.0:
                        target_x, target_y = candidate_x, candidate_y
                        break
                direction_angle = calculate_direction(x, y, target_x, target_y)

    # v2 AR geometry (ribbon + carets) needs a route to draw along, so it's
    # only attempted when a destination was given and resolved — same
    # precondition build_ar_world_v2 itself checks via len(anchors) < 2.
    ar_world_v2 = None
    ar_world_reason = 'no_destination_or_route'
    ar_hold_key = _ar_world_hold_key(selected_floor, destination, destination_floor)
    if path_coords and result.get('pose') and result['pose'].get('R') is not None:
        try:
            # PnP feature points are resized to the camera calibration's
            # reference image size inside localize_image(). AR must use that
            # same image coordinate system. Passing the uploaded camera frame
            # size here (often 1280x720) while K is calibrated for 1920x1080
            # shifts/scales the world overlay, especially with object-cover.
            ar_image_size = localization_core.get_reference_image_size_from_intrinsics(localizer_ref.K)
            if ar_image_size is None:
                ar_image_size = (image.shape[1], image.shape[0])
            payload, ar_world_reason = build_ar_world_v2(
                localizer_ref, selected_floor, result['pose'], x, y, path_coords,
                int(result.get('num_inliers', 0) or 0),
                image_size=ar_image_size,
                reproj_error=result.get('median_reproj_error'),
                stabilizer=_get_ar_stabilizer(selected_floor, localizer_ref),
            )
            if payload:
                ar_world_v2 = _remember_ar_world(ar_hold_key, _serialize_ar_world_v2(payload))
        except Exception as exc:  # noqa: BLE001 — AR geometry is best-effort, never break localization
            ar_world_reason = f'exception:{type(exc).__name__}'
            print(f"[WARN] ar_world_v2 build failed: {exc}")

    if ar_world_v2 is None:
        held_ar_world = _get_held_ar_world(ar_hold_key)
        if held_ar_world is not None:
            # A weak AR frame must not resurrect a stale turn caret after the
            # user has entered a shallow corridor bend.  The held pose can be
            # useful for the ribbon, but its old directional cue is no longer
            # semantically valid at the current route position.
            if path_coords:
                guidance_mode, local_bend_deg = route_guidance_mode(x, y, path_coords)
                if guidance_mode == 'gentle_corridor':
                    held_ar_world['carets'] = []
                    held_ar_world['alphas'] = []
                    held_ar_world['guidance_mode'] = guidance_mode
                    held_ar_world['local_bend_deg'] = float(local_bend_deg)
            ar_world_v2 = held_ar_world
            ar_world_reason = 'held_last_world_pose'

    relative_bearing = (direction_angle - orientation + 180) % 360 - 180
    if relative_bearing > 20:
        nav_text = 'Turn Right'
    elif relative_bearing < -20:
        nav_text = 'Turn Left'
    else:
        nav_text = 'Straight'

    response_payload = {
        'success': True,
        'floor_id': selected_floor,
        'position': {'x': x, 'y': y},
        'orientation': float(orientation),
        'direction': float(direction_angle),
        'relative_bearing': float(relative_bearing),
        'nav_text': nav_text,
        'path': path_coords,
        'path_segments': path_segments,
        # key is `ar_world` (not `ar_world_v2`) — matches frontend-v3's
        # existing LiveLocalizeResponse.ar_world field exactly, so this needs
        # no new frontend type/plumbing beyond what already existed for it.
        'ar_world': ar_world_v2,
        'ar_world_status': 'ready' if ar_world_v2 is not None else ar_world_reason,
        'destination_coords': destination_coords,
        'map_image_url': f"/api/map-image?floor_id={selected_floor}",
        'localize_time': _finite_or(localize_time, 0.0),
        'method': result.get('method', 'unknown'),
        'num_inliers': int(result.get('num_inliers', 0) or 0),
        'num_matches': int(result.get('num_matches', 0) or 0),
        'inlier_ratio': _finite_or(result.get('inlier_ratio', 0.0), 0.0),
        'median_reproj_error': _finite_or(result.get('median_reproj_error')),
        'tracking_seed': _serialize_tracking_seed(result, localizer_ref, image),
        'tracking_seed_frame_id': str(frame_id or '') or None,
        'tracking_seed_capture_time_ms': str(capture_time_ms or '') or None,
    }
    hold_key = _ar_world_hold_key(selected_floor, destination, destination_floor)
    return _remember_live_state(hold_key, response_payload)


@router.get('/api/retrieval-mode')
def get_retrieval_mode():
    return {
        'mode': state.retrieval_mode,
        'supported': sorted(config.SUPPORTED_RETRIEVAL_MODES),
    }


@router.post('/api/retrieval-mode')
def set_retrieval_mode(payload: dict = Body(default={})):
    requested_mode = (payload or {}).get('mode')
    if requested_mode is None:
        return JSONResponse({'error': "Missing required field 'mode'"}, status_code=400)

    if str(requested_mode).strip().lower() not in config.SUPPORTED_RETRIEVAL_MODES:
        return JSONResponse({
            'error': f"Unsupported retrieval mode: {requested_mode}",
            'supported': sorted(config.SUPPORTED_RETRIEVAL_MODES),
        }, status_code=400)

    active_mode = switch_retrieval_mode(requested_mode)
    return {
        'success': True,
        'mode': active_mode,
        'supported': sorted(config.SUPPORTED_RETRIEVAL_MODES),
        'message': f"Retrieval mode switched to {active_mode}",
    }
