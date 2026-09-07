"""Debug inspection endpoints.

FastAPI port of navigate_indoor/api/debug.py — same routes and logic; only the
response construction differs (JSONResponse/StreamingResponse instead of
jsonify/send_file).
"""
import io
import json

import cv2
import numpy as np
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse, Response

import app.config as config
import app.core.localization as loc
from app.services.state import state
from app.services.floor_service import get_keyframes_dir
from app.services.localizer_service import (
    get_or_create_localizer,
    get_or_create_comparison_localizer,
)

router = APIRouter()


def _make_serializable(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.float32, np.float64)):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def _json(payload, status_code: int = 200) -> Response:
    """Encode with the numpy fallback — debug payloads carry raw numpy scalars."""
    return Response(
        content=json.dumps(payload, default=_make_serializable),
        media_type='application/json',
        status_code=status_code,
    )


def _resolve_session(session_id):
    if session_id is None or session_id == '':
        return state.get_latest_session()
    try:
        return state.sessions.get(float(session_id))
    except (TypeError, ValueError):
        return None


@router.get('/api/debug/data')
def get_debug_data(session_id: str | None = Query(None)):
    session = _resolve_session(session_id)
    if session is None or not session.debug_mode:
        return JSONResponse({'error': 'Debug mode not enabled'}, status_code=400)
    return _json(session.debug_data)


@router.get('/api/debug/history')
def get_debug_history(session_id: str | None = Query(None)):
    session = _resolve_session(session_id)
    if session is None or not session.debug_mode:
        return JSONResponse({'error': 'Debug mode was not enabled'}, status_code=400)
    return _json({'history': session.history})


@router.get('/api/debug/frames/{frame_id}')
def get_debug_frame_info(frame_id: int, session_id: str | None = Query(None)):
    session = _resolve_session(session_id)
    if session is None or not session.debug_mode:
        return JSONResponse({'error': 'Debug mode not enabled'}, status_code=400)
    frames = session.debug_data.get('frames', [])
    if frame_id < 0 or frame_id >= len(frames):
        return JSONResponse({'error': 'Frame not found'}, status_code=404)
    return _json(frames[frame_id])


@router.get('/api/debug/match-viz/{frame_id}/{keyframe_id}')
def get_match_visualization(
    frame_id: int,
    keyframe_id: int,
    session_id: str | None = Query(None),
    mode: str = Query('orb'),
    floor_id: str | None = Query(None),
):
    session = _resolve_session(session_id)
    frames = session.debug_data.get('frames', []) if session else []
    if frame_id < 0 or frame_id >= len(frames):
        return JSONResponse({'error': 'Frame not found'}, status_code=404)

    frame_info = frames[frame_id]
    query_filename = frame_info.get('frame_filename') or frame_info.get('frame_path')
    query_path = config.TEMP_FRAMES_FOLDER / query_filename

    if not query_path.exists():
        if 'query_' not in query_filename:
            query_path = config.TEMP_FRAMES_FOLDER / f"query_{frame_id:04d}.jpg"

    if not query_path.exists():
        return JSONResponse({'error': f'Query image file {query_filename} missing'}, status_code=404)

    viz_mode = (mode or 'orb').lower()
    viz_floor = floor_id or state.current_floor_id or state.default_floor_id
    keyframes_dir = get_keyframes_dir(viz_floor, viz_mode)

    kf_path = None
    for p in [
        keyframes_dir / f"{keyframe_id:04d}" / "image.png",
        keyframes_dir / f"{keyframe_id:04d}" / "image.jpg",
        keyframes_dir / str(keyframe_id) / "image.png",
        keyframes_dir / str(keyframe_id) / "image.jpg"
    ]:
        if p.exists():
            kf_path = p
            break

    if not kf_path:
        return JSONResponse({'error': f'Keyframe {keyframe_id} image not found'}, status_code=404)

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from hloc.utils.viz import cm_RdGn, plot_images, plot_matches, add_text

        img0 = cv2.imread(str(query_path))
        img1 = cv2.imread(str(kf_path))
        if img0 is None or img1 is None:
            return JSONResponse({'error': 'Failed to read images'}, status_code=500)

        img0 = cv2.cvtColor(img0, cv2.COLOR_BGR2RGB)
        img1 = cv2.cvtColor(img1, cv2.COLOR_BGR2RGB)

        if viz_mode == 'superpoint':
            viz_localizer = get_or_create_comparison_localizer(viz_floor)
        else:
            viz_localizer = get_or_create_localizer(viz_floor)

        query_target_size = loc.get_reference_image_size_from_intrinsics(viz_localizer.K)
        if query_target_size is not None:
            img0 = loc.resize_query_image(img0, query_target_size)

        try:
            kf_ids = viz_localizer.database['keyframe_ids']
            if keyframe_id not in kf_ids:
                return JSONResponse({'error': f'Keyframe ID {keyframe_id} not in database'},
                                    status_code=404)
            kf_idx = kf_ids.index(keyframe_id)
            kf_kpts = viz_localizer.database['keypoints'][kf_idx]
            kf_desc = viz_localizer.database['descriptors'][kf_idx]
            kf_mp_ids = viz_localizer.database['mappoint_ids'][kf_idx]
            if 'keypoint_scores' in viz_localizer.database and kf_idx < len(viz_localizer.database['keypoint_scores']):
                kf_scores = viz_localizer.database['keypoint_scores'][kf_idx]
            else:
                kf_scores = np.ones(len(kf_kpts), dtype=np.float32)
        except Exception as exc:
            return JSONResponse({'error': f'Database lookup failed: {str(exc)}'}, status_code=500)

        gray0 = cv2.cvtColor(img0, cv2.COLOR_RGB2GRAY)
        q_kpts, q_desc, q_scores, _ = loc.extract_features(gray0, viz_localizer.superpoint_extractor)
        if q_desc is None:
            return JSONResponse({'error': 'Feature extraction failed'}, status_code=500)

        mkpts0, mkpts1, mappoints_3d = [], [], []
        use_superglue = viz_localizer.superglue_matcher is not None

        if use_superglue:
            match_indices, match_conf = viz_localizer.superglue_matcher.match(
                q_kpts, q_desc, q_scores,
                kf_kpts, kf_desc, kf_scores,
                image0_shape=gray0.shape,
                image1_shape=(img1.shape[0], img1.shape[1])
            )
            valid = match_conf > 0.0
            match_indices = match_indices[valid]
            for q_idx, k_idx in match_indices:
                mp_id = int(kf_mp_ids[k_idx])
                if mp_id > 0 and mp_id in viz_localizer.mappoint_dict:
                    mkpts0.append(q_kpts[q_idx])
                    mkpts1.append(kf_kpts[k_idx])
                    mappoints_3d.append(viz_localizer.mappoint_dict[mp_id])
        else:
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            try:
                matches = bf.knnMatch(q_desc.astype(np.uint8), kf_desc.astype(np.uint8), k=2)
                for m, n in matches:
                    if m.distance < 0.85 * n.distance:
                        mp_id = int(kf_mp_ids[m.trainIdx])
                        if mp_id > 0 and mp_id in viz_localizer.mappoint_dict:
                            mkpts0.append(q_kpts[m.queryIdx])
                            mkpts1.append(kf_kpts[m.trainIdx])
                            mappoints_3d.append(viz_localizer.mappoint_dict[mp_id])
            except Exception as exc:
                print(f"ORB Match Error: {exc}")

        mkpts0 = np.array(mkpts0)
        mkpts1 = np.array(mkpts1)
        mappoints_3d = np.array(mappoints_3d)

        inliers_indices = []
        if len(mappoints_3d) >= 4:
            success, rvec, tvec, inliers = cv2.solvePnPRansac(
                mappoints_3d, mkpts0, viz_localizer.K, np.zeros(4),
                reprojectionError=12.0, iterationsCount=1000, flags=cv2.SOLVEPNP_P3P
            )
            if success and inliers is not None:
                inliers_indices = inliers.flatten()

        color = np.zeros(len(mkpts0))
        if len(inliers_indices) > 0:
            color[inliers_indices] = 1.0

        plot_images([img0, img1], dpi=300)
        cols = cm_RdGn(color)
        if len(mkpts0) > 0:
            plot_matches(mkpts0, mkpts1, color=cols.tolist(), lw=1.5, a=0.1)

        add_text(0, f"inliers: {len(inliers_indices)}/{len(mkpts0)}")
        opts = dict(pos=(0.01, 0.01), fs=12, lcolor='k', lwidth=2, va="bottom")
        add_text(0, f"Query: {query_filename}", **opts)
        add_text(1, f"Train: {keyframe_id}", **opts)

        buf = io.BytesIO()
        plt.savefig(buf, format='jpeg', bbox_inches='tight', pad_inches=0)
        buf.seek(0)
        plt.close(plt.gcf())

        return Response(
            content=buf.getvalue(),
            media_type='image/jpeg',
            headers={
                'X-Num-Inliers': str(len(inliers_indices)),
                'X-Num-Matches': str(len(mkpts0)),
            },
        )

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return JSONResponse({'error': str(exc)}, status_code=500)


@router.get('/api/keyframe/{keyframe_id}')
def serve_keyframe(
    keyframe_id: str,
    mode: str = Query('orb'),
    floor_id: str | None = Query(None),
):
    keyframes_dir = get_keyframes_dir(floor_id, (mode or 'orb').lower())
    try:
        kf_id = int(keyframe_id)
        paths_to_check = [
            keyframes_dir / f"{kf_id:04d}" / "image.png",
            keyframes_dir / f"{kf_id:04d}" / "image.jpg",
            keyframes_dir / str(kf_id) / "image.png",
            keyframes_dir / str(kf_id) / "image.jpg"
        ]
    except ValueError:
        paths_to_check = [
            keyframes_dir / str(keyframe_id) / "image.png",
            keyframes_dir / str(keyframe_id) / "image.jpg"
        ]

    keyframe_path = next((p for p in paths_to_check if p.exists()), None)
    if not keyframe_path:
        return JSONResponse({'error': f'Keyframe {keyframe_id} not found'}, status_code=404)

    mime = 'image/jpeg' if keyframe_path.suffix.lower() == '.jpg' else 'image/png'
    return FileResponse(str(keyframe_path), media_type=mime)


@router.get('/api/query-frame/{filename:path}')
def serve_query_frame(filename: str):
    frame_path = config.TEMP_FRAMES_FOLDER / filename
    if not frame_path.exists():
        return JSONResponse({'error': f'Frame {filename} not found'}, status_code=404)
    return FileResponse(str(frame_path), media_type='image/jpeg')
