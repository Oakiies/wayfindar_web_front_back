"""Make a native-size presentation copy without changing the AR composition."""
from pathlib import Path

import cv2


HERE = Path(__file__).resolve().parent
INPUT = HERE / 'out' / 'ar_poc_v2_right_radar_soft_clean_full_111s_30fps.mp4'
OUTPUT = HERE / 'out' / 'ar_poc_v2_right_1920x1080_30fps.mp4'


def main():
    cap = cv2.VideoCapture(str(INPUT))
    if not cap.isOpened():
        raise SystemExit(f'input video not found: {INPUT}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    writer = cv2.VideoWriter(
        str(OUTPUT), cv2.VideoWriter_fourcc(*'mp4v'), fps, (1920, 1080)
    )
    if not writer.isOpened():
        raise SystemExit(f'could not open output video: {OUTPUT}')

    written = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        enlarged = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_LANCZOS4)
        # A very light unsharp pass recovers edge definition after enlargement
        # without inventing motion or smearing the AR caret edges.
        softened = cv2.GaussianBlur(enlarged, (0, 0), 0.8)
        enlarged = cv2.addWeighted(enlarged, 1.08, softened, -0.08, 0)
        writer.write(enlarged)
        written += 1

    cap.release()
    writer.release()
    print(f'frames={written}/{total} fps={fps:.2f} size=1920x1080')
    print(f'video={OUTPUT}')


if __name__ == '__main__':
    main()
