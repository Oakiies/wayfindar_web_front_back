"""Render the query frames used by the map-vs-estimated-K comparison.

The generated JPEGs are intentionally separate files so the static viewer can
load only the selected frame instead of embedding video or base64 data.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2


DEFAULT_VIDEO = Path(r"D:\wayfindar\floor1_wide_pare.MOV")
DEFAULT_CSV = Path(__file__).resolve().parent / "out" / "floor1_wide_map_vs_estimated_k_pare.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--csv", dest="comparison_csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=960)
    return parser.parse_args()


def render_frame(capture: cv2.VideoCapture, frame_number: int, width: int):
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ok, frame = capture.read()
    if not ok or frame is None:
        return None

    height, current_width = frame.shape[:2]
    if current_width != width:
        target_height = round(height * width / current_width)
        frame = cv2.resize(frame, (width, target_height), interpolation=cv2.INTER_AREA)
    return frame


def main() -> None:
    args = parse_args()
    if not args.video.exists():
        raise FileNotFoundError(f"Video not found: {args.video}")
    if not args.comparison_csv.exists():
        raise FileNotFoundError(f"Comparison CSV not found: {args.comparison_csv}")

    with args.comparison_csv.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {args.video}")

    manifest = []
    try:
        for row in rows:
            frame_number = int(row["frame"])
            rendered = render_frame(capture, frame_number, args.width)
            if rendered is None:
                row["image"] = None
                continue

            filename = f"frame_{frame_number:04d}.jpg"
            output_path = args.out_dir / filename
            if not cv2.imwrite(
                str(output_path), rendered, [cv2.IMWRITE_JPEG_QUALITY, 82]
            ):
                raise RuntimeError(f"Could not write image: {output_path}")
            row["image"] = filename
            manifest.append(
                {
                    "frame": frame_number,
                    "time_s": float(row["time_s"]),
                    "image": filename,
                }
            )
    finally:
        capture.release()

    manifest_path = args.out_dir.parent / "frames-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Rendered {len(manifest)}/{len(rows)} frames to {args.out_dir}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
