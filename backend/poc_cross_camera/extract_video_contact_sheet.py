from pathlib import Path

import cv2
import numpy as np


video_path = Path(r"D:\wayfindar\WebNav_front_back\backend\poc_cross_camera\out\non_imu_fullrate_ar_90s_comparison.mp4")
output_path = video_path.with_name("non_imu_fullrate_ar_90s_contact_sheet.png")
cap = cv2.VideoCapture(str(video_path))
count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
picks = [0, int(count * 0.25), int(count * 0.5), int(count * 0.75), count - 1]
wanted = set(picks)
frames = []
index = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    if index in wanted:
        frames.append(frame.copy())
    index += 1
cap.release()

frames = [cv2.resize(frame, (960, 540), interpolation=cv2.INTER_AREA) for frame in frames]
rows = (len(frames) + 1) // 2
canvas = np.zeros((rows * 540, 1920, 3), dtype=np.uint8)
for i, frame in enumerate(frames):
    row, column = divmod(i, 2)
    canvas[row * 540:(row + 1) * 540, column * 960:(column + 1) * 960] = frame
cv2.imwrite(str(output_path), canvas)
print(output_path)
