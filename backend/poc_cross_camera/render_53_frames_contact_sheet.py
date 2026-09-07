"""Contact sheet of the 53 canonical benchmark timestamps used throughout EXPERIMENT-REPORT.md.

Pulls success/failure status from the latest sharpest-policy baseline CSV
(top-k20) so the sheet doubles as a visual index into which timestamps are
failing and roughly why (blur, flat wall, repetitive corridor -- eyeballing
this is what motivated round 1 finding #7 and round 4's blur experiments).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for path in (BACKEND_DIR, BACKEND_DIR / "app", SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_floor1_wide_production_sweep import DEFAULT_VIDEO  # noqa: E402

STATUS_CSV = SCRIPT_DIR / "out" / "floor1_wide_sharpest_policy_topk20.csv"
OUT_PATH = SCRIPT_DIR / "out" / "floor1_wide_53_frames_contact_sheet.png"

THUMB_W, THUMB_H = 240, 135
COLS = 8
PAD = 4
LABEL_H = 18


def main() -> None:
    status_by_frame = {}
    if STATUS_CSV.exists():
        with STATUS_CSV.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                status_by_frame[int(row["target_frame"])] = int(row["baseline_success"])

    cap = cv2.VideoCapture(str(DEFAULT_VIDEO))
    if not cap.isOpened():
        raise RuntimeError(DEFAULT_VIDEO)
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(10.0 * fps)))
    frame_indices = list(range(0, frame_count, step))[:53]

    rows = (len(frame_indices) + COLS - 1) // COLS
    cell_w, cell_h = THUMB_W + PAD, THUMB_H + LABEL_H + PAD
    sheet = np.full((rows * cell_h + PAD, COLS * cell_w + PAD, 3), 30, dtype=np.uint8)

    for i, frame_index in enumerate(frame_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        thumb = cv2.resize(frame, (THUMB_W, THUMB_H))
        r, c = divmod(i, COLS)
        x0, y0 = PAD + c * cell_w, PAD + r * cell_h
        sheet[y0:y0 + THUMB_H, x0:x0 + THUMB_W] = thumb

        status = status_by_frame.get(frame_index)
        color = (60, 200, 60) if status == 1 else (60, 60, 220) if status == 0 else (150, 150, 150)
        cv2.rectangle(sheet, (x0, y0), (x0 + THUMB_W, y0 + THUMB_H), color, 2)
        label = f"#{i+1} t={frame_index/fps:.0f}s"
        cv2.putText(sheet, label, (x0 + 2, y0 + THUMB_H + LABEL_H - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (230, 230, 230), 1, cv2.LINE_AA)
    cap.release()

    legend_y = sheet.shape[0] - 2
    cv2.imwrite(str(OUT_PATH), sheet)
    print(f"wrote {OUT_PATH} ({sheet.shape[1]}x{sheet.shape[0]}), "
          f"green=success/red=fail (baseline, top-k20) per floor1_wide_sharpest_policy_topk20.csv")


if __name__ == "__main__":
    main()
