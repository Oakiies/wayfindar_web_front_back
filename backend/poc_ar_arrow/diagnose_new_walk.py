"""Diagnostic-only harness for a NEW walk video, mirroring the exact live-path
logic in app/services/video_processor.py::process_navigation (same localizer,
same smoother config, same build_ar_world_poc(..., stabilizer=None,
pin_route=True) call) so what this prints is what the shipping app actually
does — not the tuned poc_ar_arrow/render_poc.py harness, which runs at a
different update rate and a different pose-stabilizer setting.

No video output. Writes one CSV row per sampled frame with enough columns to
tell apart three candidate causes of "ค้างตอนเลี้ยว" / "แกว่งซ้ายขวา-หน้าหลัง":
  1. update-rate starvation (interval_seconds too coarse to track a turn)
  2. raw-PnP pose noise reaching the AR payload unfiltered (stabilizer=None)
  3. dropped/held frames during the turn (visual-jump reject, low inliers,
     outlier-gated smoother, or v2's own 'no route ahead' gates)

Run from backend/:
    .venv/Scripts/python.exe poc_ar_arrow/diagnose_new_walk.py \
        --video "D:/video/video_from_iphone_oak_wide/IMG_6955.MOV" \
        --dest m21 --floor floor1 --duration 60 --interval 1.5 \
        --out poc_ar_arrow/out/walk_m21_interval1.5.csv
"""
import argparse
import csv
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.localization_config as lc                                   # noqa: E402
from app.core import navigation as nav                                 # noqa: E402
from app.core.smoothing import create_smoother                         # noqa: E402
from app.services.floor_service import initialize_system, set_active_floor  # noqa: E402
from app.services.state import state                                   # noqa: E402
from app.services.nav_service import resolve_destination_node, compute_navigation_route  # noqa: E402
from app.services.video_processor import (                             # noqa: E402
    extract_frames_from_video, _sticky_route, _sticky_turn, _smoother_confidence,
    _get_route_progress_tracker,
    _is_implausible_visual_jump, VISUAL_JUMP_MIN_PX, VISUAL_MAX_SPEED_PX_PER_SECOND,
)
from app.services import ar_service                                    # noqa: E402
from app.utils.heading import (                                        # noqa: E402
    calculate_camera_heading, normalize_heading_deg, blend_heading_deg, calculate_direction,
)
from poc_ar_arrow.ar_arrow_v2 import build_ar_world_v2, PoseStabilizer  # noqa: E402


class _Session:
    """Same minimal stand-in _sticky_route/_sticky_turn/_get_route_progress_tracker expect."""
    active_turn = None
    turn_gap = None
    route_cache = None
    ar_route_progress = None
    ar_route_progress_path = None


def _rel_rotation_deg(R_prev, R_cur):
    if R_prev is None or R_cur is None:
        return None
    R_rel = np.asarray(R_cur, float) @ np.asarray(R_prev, float).T
    tr = np.clip((np.trace(R_rel) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(tr)))


def run(video_path, dest, floor_id, duration_s, interval_s, out_csv):
    initialize_system()
    selected_floor = set_active_floor(floor_id)
    localizer_ref = state.localizer

    dest_node, dest_data = resolve_destination_node(dest, selected_floor, selected_floor)
    if not dest_node:
        print(f"[FATAL] destination '{dest}' not found on floor {selected_floor}")
        return
    print(f"[OK] destination '{dest}' -> {dest_node} ({dest_data.get('name')}) on {selected_floor}")

    smoother = create_smoother(lc.SMOOTHER_CONFIG['position'])
    session = _Session()
    proj0 = ar_service.get_projector(selected_floor, localizer_ref)
    stabilizer = PoseStabilizer(
        alpha=0.24, max_jump_m=1.0, max_turn_deg=22.0,
        turn_follow_deg=6.0, turn_alpha=0.50,
        expected_interval_s=interval_s,
        metres_per_unit=proj0.metres_per_unit if proj0 is not None else 1.0,
    )

    last_xy_for_heading = None
    last_display_heading = None
    last_visual_fix = None
    last_R = None
    last_R_stab = None
    rows = []

    for frame_idx, frame, timestamp, read_time in extract_frames_from_video(video_path, interval_s):
        if timestamp > duration_s:
            break

        t0 = time.time()
        result, xy = localizer_ref.localize(frame)
        localize_time = time.time() - t0

        row = {
            't_sec': round(timestamp, 3), 'frame_idx': frame_idx,
            'success': bool(result.get('success')) if isinstance(result, dict) else False,
            'rejection_reason': None, 'tracking_mode': None,
            'num_inliers': None, 'reproj_err': None,
            'raw_x': None, 'raw_y': None, 'x': None, 'y': None, 'heading': None,
            'rel_rot_deg': None, 'tx': None, 'ty': None, 'tz': None,
            'ar_reason': None, 'n_carets': None, 'n_ribbon': None,
            'guidance_mode': None, 'local_bend_deg': None,
            'rel_rot_deg_stabilized': None,
            'localize_time': round(localize_time, 3),
        }

        if result.get('success') and xy is not None and _is_implausible_visual_jump(
            last_visual_fix, xy[0], xy[1], timestamp
        ):
            row['rejection_reason'] = 'implausible_visual_jump'
            result = dict(result)
            result['success'] = False

        if result.get('success') and xy is not None:
            raw_x, raw_y = xy
            num_inliers = result.get('num_inliers', 0)
            pose = result.get('pose') or {}
            R = pose.get('R')
            t = pose.get('t')
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
                row['tracking_mode'] = 'stabilizing'
                rows.append(row)
                continue

            target_orientation = pnp_heading_deg
            if last_display_heading is None:
                orientation = target_orientation
            else:
                delta = abs(((target_orientation - last_display_heading + 180.0) % 360.0) - 180.0)
                alpha = 0.85 if delta >= 30.0 else (0.65 if delta >= 15.0 else 0.45)
                orientation = blend_heading_deg(last_display_heading, target_orientation, alpha)
            last_display_heading = orientation
            last_xy_for_heading = (raw_x, raw_y)

            last_visual_fix = {
                'x': float(x), 'y': float(y), 'raw_x': float(raw_x), 'raw_y': float(raw_y),
                'orientation': float(orientation), 'timestamp': float(timestamp),
                'floor_id': selected_floor,
            }

            route_info = _sticky_route(session, selected_floor, x, y, dest, selected_floor)
            n_carets = None
            ar_reason = 'no_route'
            if route_info:
                path_coords = route_info['path_coords']
                # Updates session.active_turn for the NEXT iteration's
                # _smoother_confidence call - mirrors production's ordering
                # (video_processor.py calls this after route resolution too,
                # one frame after the smoother already ran for this frame).
                _sticky_turn(session, x, y, nav.next_turn_info(x, y, path_coords))
                image_size = (
                    localizer_ref.K[0, 2] * 2, localizer_ref.K[1, 2] * 2
                ) if getattr(localizer_ref, 'K', None) is not None else None
                progress_tracker = _get_route_progress_tracker(session, path_coords)
                payload, ar_reason = build_ar_world_v2(
                    localizer_ref, selected_floor, pose, x, y, path_coords, num_inliers,
                    image_size=image_size, reproj_error=result.get('median_reproj_error'),
                    stabilizer=stabilizer, pin_route=True, timestamp=timestamp,
                    progress_tracker=progress_tracker,
                )
                n_carets = len(payload['carets']) if payload else 0
                n_ribbon = len(payload['ribbon_quads']) if payload else 0
                guidance_mode = payload.get('guidance_mode') if payload else None
                local_bend_deg = payload.get('local_bend_deg') if payload else None
                R_stab = payload.get('R') if payload else None
                rel_rot_stab = _rel_rotation_deg(last_R_stab, R_stab) if R_stab is not None else None
                if R_stab is not None:
                    last_R_stab = R_stab

            row.update({
                'tracking_mode': 'visual_fix',
                'num_inliers': num_inliers,
                'reproj_err': result.get('median_reproj_error'),
                'raw_x': round(float(raw_x), 1), 'raw_y': round(float(raw_y), 1),
                'x': round(float(x), 1), 'y': round(float(y), 1),
                'heading': round(float(orientation), 1),
                'rel_rot_deg': round(_rel_rotation_deg(last_R, R), 2) if _rel_rotation_deg(last_R, R) is not None else None,
                'tx': round(float(t[0]), 3) if t is not None else None,
                'ty': round(float(t[1]), 3) if t is not None else None,
                'tz': round(float(t[2]), 3) if t is not None else None,
                'ar_reason': ar_reason, 'n_carets': n_carets, 'n_ribbon': n_ribbon,
                'guidance_mode': guidance_mode,
                'local_bend_deg': round(float(local_bend_deg), 1) if local_bend_deg is not None else None,
                'rel_rot_deg_stabilized': round(rel_rot_stab, 2) if rel_rot_stab is not None else None,
            })
            last_R = R
        else:
            row['tracking_mode'] = 'lost_or_held'
            if row['rejection_reason'] is None:
                row['rejection_reason'] = result.get('rejection_reason', 'localize_failed')

        rows.append(row)
        print(f"  t={timestamp:6.2f}s f{frame_idx:4d} {row['tracking_mode']:>12} "
              f"inliers={row['num_inliers']} ar={row['ar_reason']} carets={row['n_carets']} "
              f"rot={row['rel_rot_deg']}")

    fieldnames = list(rows[0].keys()) if rows else []
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"[OK] wrote {len(rows)} rows -> {out_csv}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', required=True)
    ap.add_argument('--dest', required=True)
    ap.add_argument('--floor', required=True)
    ap.add_argument('--duration', type=float, default=60.0)
    ap.add_argument('--interval', type=float, default=1.5)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    run(args.video, args.dest, args.floor, args.duration, args.interval, args.out)


if __name__ == '__main__':
    main()
