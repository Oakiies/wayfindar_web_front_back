"""Export the right-hand v2 pane from a completed comparison render.

This is useful for presentation clips: it avoids rerunning the localizer when
only the comparison layout or a small map styling detail changes.
"""
from pathlib import Path

import cv2
import numpy as np


HERE = Path(__file__).resolve().parent
INPUT = HERE / 'out' / 'ar_poc_poc37_density_hold_full_111s.avi'
OUTPUT = HERE / 'out' / 'ar_poc_v2_right_radar_soft_full_111s.avi'
OUTPUT_CLEAN = HERE / 'out' / 'ar_poc_v2_right_radar_soft_clean_full_111s.avi'
OUTPUT_30FPS = HERE / 'out' / 'ar_poc_v2_right_radar_soft_clean_full_111s_30fps.mp4'
DEBUG_STRIP_HEIGHT = 47


def soften_radar(pane):
    """Soften only the large blue radar component in the popup map."""
    # render_poc places the 238 px popup at x=644, y=112 in a 900 px pane.
    x0, y0, x1, y1 = 644, 112, 882, 350
    roi = pane[y0:y1, x0:x1]
    b, g, r = cv2.split(roi)
    mask = ((b > 185) & (g > 45) & (g < 195) &
            ((b.astype(np.int16) - g.astype(np.int16)) > 42) &
            ((b.astype(np.int16) - r.astype(np.int16)) > 90) &
            (r < 135)).astype(np.uint8)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    radar = np.zeros_like(mask)
    for index in range(1, count):
        # Route dots are small isolated components; the radar sector is the
        # large connected blue component beside the user's position.
        if stats[index, cv2.CC_STAT_AREA] >= 20:
            radar[labels == index] = 1
    if not np.any(radar):
        return pane

    # Blend 20% toward white: same accent hue, lower visual weight.
    pixels = roi[radar.astype(bool)].astype(np.float32)
    roi[radar.astype(bool)] = np.clip(pixels * 0.80 + 255.0 * 0.20,
                                     0, 255).astype(np.uint8)
    return pane


def main():
    cap = cv2.VideoCapture(str(INPUT))
    if not cap.isOpened():
        raise SystemExit(f'input video not found: {INPUT}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width < 2:
        raise SystemExit('input video has invalid dimensions')
    split = width // 2
    pane_width = width - split
    writer = cv2.VideoWriter(
        str(OUTPUT_CLEAN), cv2.VideoWriter_fourcc(*'MJPG'), fps,
        (pane_width, height - DEBUG_STRIP_HEIGHT),
    )
    if not writer.isOpened():
        raise SystemExit(f'could not open output video: {OUTPUT}')

    written = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        pane = frame[:, split:].copy()
        pane = soften_radar(pane)
        writer.write(pane[DEBUG_STRIP_HEIGHT:, :])
        written += 1

    cap.release()
    writer.release()
    print(f'frames={written} fps={fps:.2f} size={pane_width}x{height}')
    print(f'video={OUTPUT_CLEAN}')


def export_30fps():
    """Write a browser-friendly 30 FPS copy without interpolating pixels."""
    cap = cv2.VideoCapture(str(OUTPUT_CLEAN))
    if not cap.isOpened():
        raise SystemExit(f'clean video not found: {OUTPUT_CLEAN}')
    source_fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    target_fps = 30.0
    target_total = int(round(total * target_fps / source_fps))
    writer = cv2.VideoWriter(
        str(OUTPUT_30FPS), cv2.VideoWriter_fourcc(*'mp4v'), target_fps,
        (width, height),
    )
    if not writer.isOpened():
        raise SystemExit(f'could not open output video: {OUTPUT_30FPS}')

    current = None
    source_index = -1
    written = 0
    for output_index in range(target_total):
        wanted_source = min(total - 1, int(round(output_index * source_fps / target_fps)))
        while source_index < wanted_source:
            ok, current = cap.read()
            if not ok:
                break
            source_index += 1
        if current is None:
            break
        writer.write(current)
        written += 1

    cap.release()
    writer.release()
    print(f'30fps_frames={written} fps={target_fps:.2f} size={width}x{height}')
    print(f'video={OUTPUT_30FPS}')


if __name__ == '__main__':
    main()
    export_30fps()
