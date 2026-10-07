"""Extract the corrected AFTER pane from the full replay comparison video."""
from pathlib import Path
import cv2


SOURCE = Path(__file__).resolve().parent / "out/replay_registration_1p5s/comparison_realtime.mp4"
OUTPUT = SOURCE.with_name("m21_full_replay_after.mp4")

cap = cv2.VideoCapture(str(SOURCE))
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
panel_width = width // 2
writer = cv2.VideoWriter(
    str(OUTPUT), cv2.VideoWriter_fourcc(*"mp4v"), fps, (panel_width, height)
)
if not cap.isOpened() or not writer.isOpened():
    raise RuntimeError("Could not open replay comparison video")

frames = 0
try:
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(frame[:, panel_width:])
        frames += 1
finally:
    cap.release()
    writer.release()

print({"output": str(OUTPUT), "frames": frames, "fps": fps})
