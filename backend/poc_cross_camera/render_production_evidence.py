"""Render manual-inspection sheets for the production cross-camera sweep."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import matplotlib.pyplot as plt


def read_rows(path: Path, config: str) -> dict[int, dict]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return {
            int(row["frame"]): row for row in csv.DictReader(handle)
            if row["config"] == config
        }


def video_frame(cap: cv2.VideoCapture, frame_id: int):
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
    ok, image = cap.read()
    return image if ok else None


def keyframe_image(root: Path, keyframe_id: str):
    if not keyframe_id:
        return None
    folder = root / f"{int(keyframe_id):04d}"
    for name in ("image.png", "image.jpg"):
        image = cv2.imread(str(folder / name), cv2.IMREAD_COLOR)
        if image is not None:
            return image
    return None


def sharpness(image) -> float:
    if image is None:
        return 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def render_sheet(path: Path, title: str, items: list[tuple[dict, str]], cap, keyframes: Path):
    if not items:
        return
    fig, axes = plt.subplots(len(items), 2, figsize=(14, 3.5 * len(items)), dpi=130)
    if len(items) == 1:
        axes = [axes]
    for axis_pair, (row, reference_field) in zip(axes, items):
        query = video_frame(cap, int(row["frame"]))
        reference_id = row.get(reference_field) or row.get("retrieval_top1") or ""
        reference = keyframe_image(keyframes, reference_id)
        for axis, image in zip(axis_pair, (query, reference)):
            axis.axis("off")
            if image is not None:
                axis.imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        axis_pair[0].set_title(
            f"query t={float(row['time_s']):.1f}s frame={row['frame']} "
            f"sharp={sharpness(query):.0f}"
        )
        axis_pair[1].set_title(
            f"map KF={reference_id or 'none'} | matches={row['max_candidate_matches']} "
            f"raw inliers={row['max_raw_pnp_inliers']} | sharp={sharpness(reference):.0f}"
        )
    fig.suptitle(title, fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topk4", type=Path, required=True)
    parser.add_argument("--topk20", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--keyframes", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", default="raw_production")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    low = read_rows(args.topk4, args.config)
    high = read_rows(args.topk20, args.config)
    recovered = [
        (high[frame], "matched_keyframe") for frame in sorted(high)
        if int(low[frame]["success"]) == 0 and int(high[frame]["success"]) == 1
    ]
    failed_rows = [high[frame] for frame in sorted(high) if int(high[frame]["success"]) == 0]
    if len(failed_rows) > 10:
        indices = [round(i * (len(failed_rows) - 1) / 9) for i in range(10)]
        failed_rows = [failed_rows[i] for i in indices]
    remaining = [(row, "retrieval_top1") for row in failed_rows]

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(args.video)
    render_sheet(
        args.out / "floor1_wide_topk20_recovered_evidence.png",
        "Recovered by MegaLoc shortlist k=20 (same map, matcher, and PnP gates)",
        recovered, cap, args.keyframes,
    )
    render_sheet(
        args.out / "floor1_wide_topk20_remaining_failures_evidence.png",
        "Representative remaining failures at k=20 (top-1 retrieved keyframe)",
        remaining, cap, args.keyframes,
    )
    cap.release()


if __name__ == "__main__":
    main()
