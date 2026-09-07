"""Floors, rooms, map image, video upload + serving.

FastAPI port of navigate_indoor/api/floors.py. Route paths, response shapes and
logic follow upstream; only the framework glue differs (APIRouter instead of a
Flask Blueprint, streamed UploadFile instead of werkzeug's file.save).
"""
import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from werkzeug.utils import secure_filename

import app.config as config
import app.core.navigation as nav
from app.services.state import state
from app.services.floor_service import get_floor_list, get_floor_map_image
from app.services.nav_service import normalize_place_name
from app.services.video_processor import (
    allowed_file,
    validate_video_file,
    _needs_transcode,
    transcode_to_h264,
)
from app.utils.server import log_status

router = APIRouter()


@router.get('/api/floors')
def get_floors():
    return {
        'floors': get_floor_list(),
        'default_floor': state.default_floor_id,
    }


@router.get('/api/rooms')
def get_rooms(floor_id: str | None = Query(None), all: str = Query('')):
    if state.nodes is None and state.building_nodes is None:
        return {'rooms': [], 'error': 'System not initialized'}

    requested_floor = floor_id or state.current_floor_id or state.default_floor_id
    include_all = all.lower() in {'1', 'true', 'yes'}

    if state.building_nodes and include_all:
        source_nodes = state.building_nodes
    elif state.building_nodes:
        source_nodes = nav.get_nodes_for_floor(state.building_nodes, requested_floor)
    else:
        source_nodes = state.nodes

    grouped_rooms = {}
    for node_id, data in source_nodes.items():
        node_floor = data.get('floor_id', data.get('floor', requested_floor))
        node_type = data.get('type', 'unknown')
        raw_name = data.get('name', '')
        display_name = normalize_place_name(raw_name)
        key = (str(node_floor), str(node_type), str(display_name))

        if key not in grouped_rooms:
            grouped_rooms[key] = {
                'id': node_id,
                'name': display_name,
                'type': node_type,
                'floor_id': node_floor,
                'x_sum': float(data['x']),
                'y_sum': float(data['y']),
                'count': 1,
            }
        else:
            grouped_rooms[key]['x_sum'] += float(data['x'])
            grouped_rooms[key]['y_sum'] += float(data['y'])
            grouped_rooms[key]['count'] += 1

    rooms = []
    for info in grouped_rooms.values():
        count = max(1, int(info['count']))
        rooms.append({
            'id': info['id'],
            'name': info['name'],
            'type': info['type'],
            'floor_id': info['floor_id'],
            'x': info['x_sum'] / count,
            'y': info['y_sum'] / count,
        })

    print(f"DEBUG: Returning {len(rooms)} rooms to frontend")
    return {'rooms': rooms}


@router.get('/api/map-image')
def get_map_image(floor_id: str | None = Query(None)):
    fid = floor_id or state.current_floor_id or state.default_floor_id
    map_image = get_floor_map_image(fid)
    if not map_image.exists():
        return JSONResponse({'error': 'Map image not found'}, status_code=404)
    return FileResponse(str(map_image), media_type='image/jpeg')


@router.get('/api/map')
def serve_map_image(floor_id: str | None = Query(None)):
    """Alias kept for the existing frontend; upstream only exposes /api/map-image."""
    return get_map_image(floor_id)


@router.post('/api/upload-video')
async def upload_video(video: UploadFile = File(...)):
    filename = (video.filename or '').strip()
    if not filename:
        return JSONResponse({'error': 'No selected file'}, status_code=400)
    if not allowed_file(filename):
        return JSONResponse({'error': 'Invalid file type'}, status_code=400)

    safe_name = secure_filename(Path(filename).name)
    if not safe_name:
        return JSONResponse({'error': 'Invalid filename'}, status_code=400)

    config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    file_path = config.UPLOAD_FOLDER / safe_name
    log_status('UPLOAD', f'Receiving upload: {safe_name}')

    # Stream to disk in chunks — phone captures are routinely hundreds of MB and
    # reading the whole body into memory first would spike RSS per upload.
    # UploadFile is already a multipart spool; copy it in one worker-thread
    # operation instead of hundreds of awaited 1 MB reads.
    try:
        await video.seek(0)
        with file_path.open('wb') as output:
            await asyncio.to_thread(
                shutil.copyfileobj,
                video.file,
                output,
                16 * 1024 * 1024,
            )
    except Exception as exc:
        return JSONResponse({'error': f'Failed to save upload: {exc}'}, status_code=500)
    finally:
        await video.close()

    if _needs_transcode(file_path):
        try:
            file_path = transcode_to_h264(file_path)
            safe_name = file_path.name
        except Exception as exc:
            print(f"[WARN] Transcode to H.264 failed, keeping original file ({exc})")

    is_valid, error_message, metadata = validate_video_file(file_path)
    if not is_valid:
        log_status('UPLOAD', f'Upload rejected: {safe_name} ({error_message})')
        try:
            file_path.unlink()
        except OSError:
            pass
        return JSONResponse({'error': error_message or 'Uploaded video is invalid'}, status_code=400)

    file_size_mb = file_path.stat().st_size / (1024 * 1024) if file_path.exists() else 0.0
    log_status('UPLOAD', f'Upload stored: {safe_name} ({file_size_mb:.1f} MB, '
                         f'{metadata.get("frame_count", 0)} frames @ {metadata.get("fps", 0.0):.2f} FPS)')

    return {'success': True, 'filename': safe_name, 'path': str(file_path), 'video_info': metadata}


@router.get('/uploads/{filename:path}')
def serve_video(filename: str):
    file_path = config.UPLOAD_FOLDER / filename
    if not file_path.exists():
        return JSONResponse({'error': 'File not found'}, status_code=404)
    return FileResponse(str(file_path))


@router.get('/api/demo-video')
def serve_demo_video():
    """Serve the pre-rendered AR video used by the local demo mode."""
    if not config.DEMO_VIDEO_PATH.exists():
        return JSONResponse({'error': 'Pre-rendered AR demo video not found'}, status_code=404)
    return FileResponse(str(config.DEMO_VIDEO_PATH), media_type='video/mp4')
