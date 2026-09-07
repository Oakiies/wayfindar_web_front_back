"""Render manual-audit evidence for temporal propagation gains/losses."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import matplotlib.pyplot as plt


def read_config(path: Path, config: str) -> dict[int, dict]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return {int(row["frame"]): row for row in csv.DictReader(handle) if row["config"] == config}


def read_frame(cap: cv2.VideoCapture, frame: int):
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, image = cap.read()
    return image if ok else None


def number(row: dict, key: str):
    value = row.get(key, "")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def draw_pose(axis, floor_plan, row: dict | None, color: str, label: str):
    axis.imshow(cv2.cvtColor(floor_plan, cv2.COLOR_BGR2RGB))
    axis.axis("off")
    if row is None:
        axis.set_title(f"{label}: no pose")
        return
    x, y = number(row, "x_px"), number(row, "y_px")
    if x is not None and y is not None:
        axis.scatter([x], [y], s=100, c=color, edgecolors="white", linewidths=1.5)
        axis.set_title(
            f"{label}: ({x:.1f}, {y:.1f}) | inliers={number(row, 'num_inliers') or 0:.0f} "
            f"| heading={number(row, 'heading_deg') or 0:.1f}°"
        )
    else:
        axis.set_title(f"{label}: no map coordinate")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--baseline-config", default="raw_exact_1920x1080")
    parser.add_argument("--experiment-config", default="direct_plus_past")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--floor-plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--filename", default="floor1_wide_temporal_discordant_evidence.png")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    baseline = read_config(args.baseline, args.baseline_config)
    experiment = read_config(args.experiment, args.experiment_config)
    discordant = sorted(frame for frame in baseline if frame in experiment and baseline[frame]["success"] != experiment[frame]["success"])
    if not discordant:
        print("No discordant frames")
        return

    cap = cv2.VideoCapture(str(args.video))
    floor_plan = cv2.imread(str(args.floor_plan), cv2.IMREAD_COLOR)
    if not cap.isOpened() or floor_plan is None:
        raise RuntimeError("Cannot open video or floor plan")

    fig, axes = plt.subplots(len(discordant), 3, figsize=(18, max(4, 4 * len(discordant))), dpi=130)
    if len(discordant) == 1:
        axes = axes[None, :]
    for row_axes, frame in zip(axes, discordant):
        b = baseline[frame]
        e = experiment[frame]
        query = read_frame(cap, frame)
        row_axes[0].axis("off")
        if query is not None:
            row_axes[0].imshow(cv2.cvtColor(query, cv2.COLOR_BGR2RGB))
        row_axes[0].set_title(
            f"frame={frame}, t={float(e['time_s']):.1f}s\n"
            f"baseline success={b['success']} | experiment success={e['success']}"
        )
        draw_pose(row_axes[1], floor_plan, b if b["success"] == "1" else None, "tab:blue", "baseline")
        draw_pose(row_axes[2], floor_plan, e if e["success"] == "1" else None, "tab:orange", "direct+past")
    fig.suptitle("Temporal landmark propagation — manual audit of discordant frames", fontsize=16)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    output = args.out / args.filename
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    cap.release()
    print(f"frames={discordant}")
    print(output)


if __name__ == "__main__":
    main()
