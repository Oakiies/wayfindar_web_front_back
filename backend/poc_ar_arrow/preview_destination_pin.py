# -*- coding: utf-8 -*-
"""Restyle the destination marker without re-running the walk.

`render_poc.py` writes one real camera pose and its frame to
`out/pin_pose.npz` / `out/pin_pose_frame.png` the first time it draws the pin.
This script replays that single pose, so a change to the marker can be seen in
a second instead of after a localization pass over 2352 keyframes.

It also shows the approach state, which the floor5 clip barely reaches: on that
walk the pin only becomes visible once `arrived` is already true, so the red
"N m away" styling never appears in the A/B video.

    cd backend
    .venv/Scripts/python.exe poc_ar_arrow/preview_destination_pin.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.floor_service import initialize_system, set_active_floor  # noqa: E402
from app.services.state import state                                       # noqa: E402
from app.services import ar_service                                        # noqa: E402

from poc_ar_arrow.render_poc import (                                      # noqa: E402
    FLOOR, OUT_DIR, PANE_W, render_destination_pin, _font,
)

OUT = OUT_DIR / 'destination_pin_preview.png'

STATES = [
    ('Approaching', 'ระหว่างเดินไป · #e5484d', False, 24.0),
    ('Closer', 'ใกล้แล้ว · ระยะอัปเดตทุกเฟรม', False, 6.0),
    ('Arrived', 'ถึงแล้ว · #22c55e + lucide check', True, None),
]


def _projector():
    """Same construction as render_poc's - the projector reads H_matrix and
    floor_config off the localizer, nothing else."""
    initialize_system()
    set_active_floor(FLOOR)
    return ar_service.get_projector(FLOOR, state.localizer)


def main():
    pose_path = OUT_DIR / 'pin_pose.npz'
    frame_path = OUT_DIR / 'pin_pose_frame.png'
    if not pose_path.exists() or not frame_path.exists():
        raise SystemExit(
            f'No captured pose. Run render_poc.py once first - it writes\n'
            f'  {pose_path}\n  {frame_path}\n'
            f'the first time the destination pin is drawn.')

    data = np.load(pose_path)
    payload = {'K': data['K'], 'R': data['R'], 't': data['t']}
    destination_xy = tuple(float(v) for v in data['destination'])

    frame = cv2.imread(str(frame_path))
    scale = PANE_W / frame.shape[1]
    pane = cv2.resize(frame, (PANE_W, int(round(frame.shape[0] * scale))))

    # The pose was solved against the full-resolution frame, so K has to follow
    # the same resize or the marker lands in the wrong place.
    payload['K'] = payload['K'].copy()
    payload['K'][:2, :] *= scale

    proj = _projector()

    tiles = []
    for _, _, arrived, distance in STATES:
        tiles.append(render_destination_pin(
            pane, payload, proj, destination_xy, 'FIRE EXIT 1',
            arrived=arrived, screen_filter=None, distance_m=distance))

    h, w = tiles[0].shape[:2]
    pad, cap = 20, 54
    sheet = np.full((pad + h + cap + pad, pad + len(tiles) * (w + pad), 3), 242, np.uint8)
    for i, tile in enumerate(tiles):
        x = pad + i * (w + pad)
        sheet[pad:pad + h, x:x + w] = tile

    im = cv2.cvtColor(sheet, cv2.COLOR_BGR2RGB)
    from PIL import Image, ImageDraw
    pil = Image.fromarray(im)
    draw = ImageDraw.Draw(pil)
    for i, (name, note, _, _) in enumerate(STATES):
        x = pad + i * (w + pad)
        draw.text((x, pad + h + 12), name, font=_font(16, True), fill=(17, 19, 21))
        draw.text((x, pad + h + 32), note, font=_font(12), fill=(85, 89, 95))
    sheet = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)

    cv2.imwrite(str(OUT), sheet)
    print(f'wrote {OUT}  ({sheet.shape[1]}x{sheet.shape[0]})')


if __name__ == '__main__':
    main()
