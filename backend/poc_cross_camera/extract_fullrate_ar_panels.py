from pathlib import Path

import cv2


source = Path(r"D:\wayfindar\WebNav_front_back\backend\poc_cross_camera\out\non_imu_fullrate_ar_90s_comparison.mp4")
out_dir = source.parent
cap = cv2.VideoCapture(str(source))
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
panel_w = width // 2
panel_h = height // 2
names = {
    "raw_pnp": (0, 0),
    "ema_interpolated": (1, 0),
    "jump_gated_hold": (0, 1),
    "klt_soft_pnp": (1, 1),
}
writers = {
    name: cv2.VideoWriter(
        str(out_dir / f"non_imu_fullrate_ar_90s_{name}.mp4"),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (panel_w, panel_h),
    )
    for name in names
}

try:
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        for name, (column, row) in names.items():
            panel = frame[row * panel_h:(row + 1) * panel_h, column * panel_w:(column + 1) * panel_w]
            writers[name].write(panel)
finally:
    cap.release()
    for writer in writers.values():
        writer.release()

print("created", len(names), "full-rate AR clips")
