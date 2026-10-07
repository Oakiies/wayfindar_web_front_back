"""Render the FIXED AR overlay onto the real camera frames for the m21 walk,
using the exact same pipeline diagnose_new_walk.py measures (post-fix
ar_arrow_v2.py + the wired-up PoseStabilizer).

Two passes so the output plays as continuous video instead of a slideshow of
localization samples:
  1. Localize at `--interval` seconds (matches the real backend cadence) and
     record one AR "keyframe" per accepted fix: its stabilized camera (R, t)
     and the world-space payload (carets/ribbon) it produced.
  2. Walk the video at its NATIVE frame rate. Every native frame is written;
     frames that fall between two keyframes get an INTERPOLATED camera pose
     (Slerp on rotation, linear on translation) reprojecting the nearer
     keyframe's payload, so the overlay glides between updates the way a
     phone's continuous camera feed would, instead of holding one frame per
     localization sample. This is a rendering choice for this preview video
     only - it is not a change to the live backend, which cannot interpolate
     toward a pose it has not received yet.

Run from backend/:
    .venv/Scripts/python.exe poc_ar_arrow/render_walk_video.py \
        --video "D:/video/video_from_iphone_oak_wide/IMG_6955.MOV" \
        --dest m21 --floor floor1 --duration 60 --interval 0.5 \
        --out poc_ar_arrow/out/walk_m21_fixed_smooth.mp4
"""
import argparse
import math
import subprocess
import sys
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from scipy.spatial.transform import Rotation, Slerp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.localization_config as lc                                   # noqa: E402
from app.core.smoothing import create_smoother                         # noqa: E402
from app.services.floor_service import initialize_system, set_active_floor  # noqa: E402
from app.services.state import state                                   # noqa: E402
from app.services.nav_service import resolve_destination_node          # noqa: E402
from app.services.video_processor import (                             # noqa: E402
    extract_frames_from_video, _sticky_route, _sticky_turn, _smoother_confidence,
    _get_route_progress_tracker, _is_implausible_visual_jump,
)
from app.core import navigation as nav                                  # noqa: E402
from app.services import ar_service                                    # noqa: E402
from app.utils.heading import (                                        # noqa: E402
    calculate_camera_heading, normalize_heading_deg, blend_heading_deg,
)
from poc_ar_arrow.ar_arrow_v2 import build_ar_world_v2, render_v2, PoseStabilizer  # noqa: E402

# Beyond this gap between two accepted fixes, interpolating a pose is
# fabricating motion, not showing it: the production backend's own
# `_ar_world_or_hold` clears the world overlay the instant a frame fails to
# localize (app/services/video_processor.py) rather than holding or
# extrapolating it, precisely because a stale/guessed 3D registration reads as
# worse than nothing. A gap much longer than the sampling interval means
# tracking was actually LOST for that stretch (commonly: motion blur while the
# phone pans through a real turn) - the exact moment a turn cue matters most,
# and the exact moment neither this preview nor the live app has any pose to
# draw from. Interpolating smoothly across it looks like the AR "floating,
# out of sync with the real walk"; hiding it, like production does, is the
# honest picture of what tracking actually had at that instant.
MAX_INTERP_GAP_FACTOR = 1.5  # multiples of the sampling interval
MAX_INTERP_TURN_DEG = 20.0  # snap to nearer keyframe past this much rotation


class _Session:
    active_turn = None
    turn_gap = None
    route_cache = None
    ar_route_progress = None
    ar_route_progress_path = None


def _collect_keyframes(video_path, dest, floor_id, duration_s, interval_s):
    initialize_system()
    selected_floor = set_active_floor(floor_id)
    localizer_ref = state.localizer

    dest_node, dest_data = resolve_destination_node(dest, selected_floor, selected_floor)
    if not dest_node:
        raise SystemExit(f"destination '{dest}' not found on floor {selected_floor}")
    print(f"[OK] destination '{dest}' -> {dest_node} on {selected_floor}")

    smoother = create_smoother(lc.SMOOTHER_CONFIG['position'])
    session = _Session()
    proj0 = ar_service.get_projector(selected_floor, localizer_ref)
    stabilizer = PoseStabilizer(
        alpha=0.24, max_jump_m=1.0, max_turn_deg=22.0,
        turn_follow_deg=6.0, turn_alpha=0.50,
        expected_interval_s=interval_s,
        metres_per_unit=proj0.metres_per_unit if proj0 is not None else 1.0,
    )

    last_display_heading = None
    last_visual_fix = None
    keyframes = []  # each: {t, R, t_vec, payload, guidance_mode, n_carets, num_inliers}

    for frame_idx, frame, timestamp, read_time in extract_frames_from_video(video_path, interval_s):
        if timestamp > duration_s:
            break
        result, xy = localizer_ref.localize(frame)
        if result.get('success') and xy is not None and _is_implausible_visual_jump(
            last_visual_fix, xy[0], xy[1], timestamp
        ):
            result = dict(result)
            result['success'] = False
        if not (result.get('success') and xy is not None):
            print(f"  t={timestamp:6.2f}s LOST")
            continue

        raw_x, raw_y = xy
        num_inliers = result.get('num_inliers', 0)
        pose = result.get('pose') or {}
        R = pose.get('R')
        projector = ar_service.get_projector(selected_floor, localizer_ref)
        pnp_heading_deg = calculate_camera_heading(R, raw_x, raw_y, projector)
        if pnp_heading_deg is None:
            pnp_heading_deg = normalize_heading_deg(90 - float(pose.get('theta', 0)))

        smooth_res = smoother.update(
            raw_x, raw_y, timestamp, _smoother_confidence(session, num_inliers),
            measured_heading=pnp_heading_deg,
        )
        x, y = (smooth_res[0], smooth_res[1])
        if x is None:
            continue

        target_orientation = pnp_heading_deg
        orientation = (target_orientation if last_display_heading is None else
                       blend_heading_deg(last_display_heading, target_orientation,
                                          0.85 if abs(((target_orientation - last_display_heading + 180) % 360) - 180) >= 30
                                          else 0.65 if abs(((target_orientation - last_display_heading + 180) % 360) - 180) >= 15
                                          else 0.45))
        last_display_heading = orientation
        last_visual_fix = {'x': float(x), 'y': float(y), 'raw_x': float(raw_x), 'raw_y': float(raw_y),
                            'orientation': float(orientation), 'timestamp': float(timestamp)}

        route_info = _sticky_route(session, selected_floor, x, y, dest, selected_floor)
        if route_info:
            _sticky_turn(session, x, y, nav.next_turn_info(x, y, route_info['path_coords']))
        payload, ar_reason, n_carets, guidance_mode = None, 'no_route', 0, None
        if route_info:
            path_coords = route_info['path_coords']
            image_size = (frame.shape[1], frame.shape[0])
            progress_tracker = _get_route_progress_tracker(session, path_coords)
            payload, ar_reason = build_ar_world_v2(
                localizer_ref, selected_floor, pose, x, y, path_coords, num_inliers,
                image_size=image_size, reproj_error=result.get('median_reproj_error'),
                stabilizer=stabilizer, pin_route=True, timestamp=timestamp,
                progress_tracker=progress_tracker,
            )
            if payload:
                n_carets = len(payload['carets'])
                guidance_mode = payload.get('guidance_mode')

        print(f"  t={timestamp:6.2f}s inl={num_inliers} ar={ar_reason} carets={n_carets} guid={guidance_mode}")
        if payload is not None:
            keyframes.append({
                't': timestamp, 'R': np.asarray(payload['R'], float),
                't_vec': np.asarray(payload['t'], float).reshape(3),
                'payload': payload,
            })

    return keyframes, (frame.shape[1], frame.shape[0]) if keyframes else None


def _interp_pose(keyframes, t, interval_s):
    """Return (payload_to_reproject, R, t_vec) for native frame time `t`, or
    None when the surrounding gap is a real tracking dropout rather than
    ordinary sampling - matching production's "no pose, no overlay" policy.
    """
    if not keyframes:
        return None
    # Never back-fill the first successful localization into earlier camera
    # frames. Production cannot draw a world-locked overlay before that pose
    # exists, and doing so would leak future information into the preview.
    if t < keyframes[0]['t']:
        return None
    if t == keyframes[0]['t']:
        kf = keyframes[0]
        return kf['payload'], kf['R'], kf['t_vec']
    if t >= keyframes[-1]['t']:
        kf = keyframes[-1]
        return kf['payload'], kf['R'], kf['t_vec']

    lo, hi = 0, len(keyframes) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if keyframes[mid]['t'] <= t:
            lo = mid
        else:
            hi = mid
    a, b = keyframes[lo], keyframes[hi]
    gap = b['t'] - a['t']
    if gap > interval_s * MAX_INTERP_GAP_FACTOR:
        # A real dropout, not just the normal sampling cadence: tracking had
        # nothing to draw for this stretch, so neither do we.
        return None
    if gap <= 1e-6:
        nearer = a if (t - a['t']) <= (b['t'] - t) else b
        return nearer['payload'], nearer['R'], nearer['t_vec']

    # A real turn can rotate the phone far enough between two fixes that
    # Slerp-ing between them passes through camera orientations the walker
    # never actually held. The RIBBON GEOMETRY at each keyframe is only valid
    # for the pose it was built with (see build_ar_world_v2's own sanitize
    # pass) - reprojecting it through one of these never-real in-between
    # poses produced a correctly-computed but meaningless projection (long
    # streaks across the frame), confirmed to appear ONLY on interpolated
    # frames and never on a real fix. Snap to the nearer keyframe's pose AND
    # payload together instead of blending past this threshold - matching,
    # not guessing between, an actual tracked orientation.
    turn_deg = float(Rotation.from_matrix(b['R'] @ a['R'].T).magnitude() * 180.0 / math.pi)
    if turn_deg > MAX_INTERP_TURN_DEG:
        nearer = a if (t - a['t']) <= (b['t'] - t) else b
        return nearer['payload'], nearer['R'], nearer['t_vec']

    frac = (t - a['t']) / gap
    rots = Rotation.from_matrix(np.stack([a['R'], b['R']]))
    slerp = Slerp([0.0, 1.0], rots)
    R = slerp(frac).as_matrix()
    t_vec = (1 - frac) * a['t_vec'] + frac * b['t_vec']
    # Reproject the payload whose keyframe is temporally closer - carets/
    # ribbon are anchored in world space so a small pose blend does not
    # distort them, but which SET of stations is "current" should still
    # switch at the midpoint rather than always using the earlier one.
    payload = a['payload'] if frac < 0.5 else b['payload']
    return payload, R, t_vec


def render(video_path, keyframes, out_path, duration_s, interval_s):
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    writer = None
    n = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if timestamp > duration_s:
            break

        result = _interp_pose(keyframes, timestamp, interval_s)
        display = frame
        label = f"t={timestamp:5.1f}s"
        if result is not None:
            payload, R, t_vec = result
            live_payload = dict(payload)
            live_payload['R'] = R
            live_payload['t'] = t_vec
            display = render_v2(frame, live_payload)
        else:
            label += "  [NO TRACKING - matches what production shows here]"

        cv2.putText(display, label, (14, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(display, label, (14, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)

        if writer is None:
            h, w = display.shape[:2]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            writer = subprocess.Popen([
                ffmpeg, '-y',
                '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                '-s:v', f'{w}x{h}', '-r', f'{fps:.8f}', '-i', 'pipe:0',
                '-i', str(video_path),
                '-map', '0:v:0', '-map', '1:a:0?',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '160k',
                '-t', f'{duration_s:.6f}', '-movflags', '+faststart',
                str(out_path),
            ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL)
        writer.stdin.write(np.ascontiguousarray(display).tobytes())
        n += 1
        if n % 150 == 0:
            print(f"  ...{timestamp:.1f}s written")

    cap.release()
    if writer is not None:
        writer.stdin.close()
        return_code = writer.wait()
        if return_code != 0:
            raise RuntimeError(f'ffmpeg failed with exit code {return_code}')
    print(f"[OK] wrote {n} native frames @ {fps:.2f}fps -> {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', required=True)
    ap.add_argument('--dest', required=True)
    ap.add_argument('--floor', required=True)
    ap.add_argument('--duration', type=float, default=60.0)
    ap.add_argument('--interval', type=float, default=0.5)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    # initialize_system() changes the process working directory to app/, so
    # resolve user paths before loading the backend to keep outputs where the
    # command requested them.
    video_path = Path(args.video).resolve()
    output_path = Path(args.out).resolve()
    keyframes, _ = _collect_keyframes(video_path, args.dest, args.floor, args.duration, args.interval)
    print(f"[OK] {len(keyframes)} AR keyframes collected")
    render(video_path, keyframes, output_path, args.duration, args.interval)


if __name__ == '__main__':
    main()
