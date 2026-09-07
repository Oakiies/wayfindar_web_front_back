"""Restore the original-resolution camera layer under an existing AR render.

The expensive localization pass has already produced the AR/UI overlay at
900 px.  This exporter transfers only pixels changed by that overlay onto the
matching 1920x1080 source frame, so the camera background keeps its original
detail instead of being enlarged from the small comparison pane.
"""
from pathlib import Path

import cv2
import numpy as np


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2] / 'navigate_indoor' / 'uploads' / 'floor5_2.mp4'
RENDERED = HERE / 'out' / 'ar_poc_v2_right_radar_soft_full_111s.avi'
OUTPUT = HERE / 'out' / 'ar_poc_v2_right_native_quality_full_111s_30fps.avi'


def main():
    source = cv2.VideoCapture(str(SOURCE))
    rendered = cv2.VideoCapture(str(RENDERED))
    if not source.isOpened() or not rendered.isOpened():
        raise SystemExit('source or rendered video could not be opened')

    source_fps = source.get(cv2.CAP_PROP_FPS) or 59.94
    render_fps = rendered.get(cv2.CAP_PROP_FPS) or 20.0
    total = int(rendered.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT))
    target_fps = 30.0
    target_total = int(round(total * target_fps / render_fps))

    writer = cv2.VideoWriter(
        str(OUTPUT), cv2.VideoWriter_fourcc(*'MJPG'), target_fps,
        (width, height),
    )
    if not writer.isOpened():
        raise SystemExit(f'could not open output video: {OUTPUT}')

    rendered_frame = None
    source_frame = None
    rendered_index = -1
    source_index = -1
    written = 0
    for output_index in range(target_total):
        wanted_render = min(total - 1, int(round(output_index * render_fps / target_fps)))
        while rendered_index < wanted_render:
            ok, rendered_frame = rendered.read()
            if not ok:
                break
            rendered_index += 1
        if rendered_frame is None:
            break

        # render_poc samples source frames 0, 3, 6, ... at 20 FPS.
        wanted_source = min(int(source.get(cv2.CAP_PROP_FRAME_COUNT)) - 1,
                            wanted_render * 3)
        while source_index < wanted_source:
            ok, source_frame = source.read()
            if not ok:
                break
            source_index += 1
        if source_frame is None:
            break

        base = cv2.resize(source_frame, (900, 506), interpolation=cv2.INTER_LINEAR)
        delta = rendered_frame.astype(np.float32) - base.astype(np.float32)
        magnitude = np.max(np.abs(delta), axis=2)
        mask = (magnitude > 10.0).astype(np.uint8)
        # The first 47 rows of the comparison render are its debug label bar;
        # leave the original camera pixels there instead of transferring it.
        mask[:47, :] = 0
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

        delta_hi = cv2.resize(delta, (width, height), interpolation=cv2.INTER_LINEAR)
        mask_hi = cv2.resize(mask.astype(np.float32) * 255.0, (width, height),
                             interpolation=cv2.INTER_LINEAR) / 255.0
        output = source_frame.astype(np.float32) + delta_hi * mask_hi[:, :, None]
        writer.write(np.clip(output, 0, 255).astype(np.uint8))
        written += 1

    source.release()
    rendered.release()
    writer.release()
    print(f'frames={written} fps={target_fps:.2f} size={width}x{height}')
    print(f'video={OUTPUT}')


if __name__ == '__main__':
    main()
