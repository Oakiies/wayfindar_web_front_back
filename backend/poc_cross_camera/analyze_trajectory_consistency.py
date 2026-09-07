"""Post-hoc consistency check on already-produced sweep CSVs.

We have no ground truth and no known map scale (meters-per-pixel), so an
absolute "max walking speed" gate is not available. Instead this applies a
robust, self-normalizing outlier test in the spirit of sequence-consistency
checks used in sequence-based localization (SeqSLAM, Milford & Wyeth, ICRA
2012, already cited in EXPERIMENT-REPORT.md): consecutive accepted poses
~10s apart should not jump by an amount wildly larger than the typical jump
for that run, and heading should not flip by an amount wildly larger than
typical either. Frames flagged this way are not proven wrong -- a real
doorway turn can look like an outlier too -- but the flag rate itself is a
second, cheap number to report next to raw "gate-passes", per the reminder
that PnP-gate-pass != accuracy.

Usage: point at any CSV produced by run_floor1_wide_production_sweep.py
(needs frame, time_s, config, success, x_px, y_px, heading_deg columns).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def mad_outliers(values: np.ndarray, k: float = 3.5) -> np.ndarray:
    """Median-absolute-deviation based outlier flags (robust to non-normal, skewed jump distributions)."""
    if len(values) == 0:
        return np.zeros(0, dtype=bool)
    median = np.median(values)
    mad = np.median(np.abs(values - median)) or 1e-6
    modified_z = 0.6745 * (values - median) / mad
    return np.abs(modified_z) > k


def angular_diff_deg(a: np.ndarray) -> np.ndarray:
    return (a + 180.0) % 360.0 - 180.0


def analyze(rows: list[dict], config_name: str) -> dict:
    selected = sorted(
        (r for r in rows if r["config"] == config_name and int(r["success"]) == 1),
        key=lambda r: float(r["time_s"]),
    )
    total = sum(1 for r in rows if r["config"] == config_name)
    if len(selected) < 2:
        return {
            "config": config_name, "total_timestamps": total,
            "gate_pass_successes": len(selected), "trajectory_consistent_successes": len(selected),
            "note": "fewer than 2 accepted poses; consistency check not applicable",
        }

    times = np.array([float(r["time_s"]) for r in selected])
    dt = np.diff(times)
    dt = np.where(dt <= 0, 1e-6, dt)  # guard against duplicate timestamps

    xy = np.array([(float(r["x_px"]), float(r["y_px"])) for r in selected])
    jumps = np.linalg.norm(np.diff(xy, axis=0), axis=1) / dt  # px/s, so gaps of different length are comparable
    position_outlier = mad_outliers(jumps)

    has_heading = all(r.get("heading_deg", "") != "" for r in selected)
    heading_outlier = np.zeros(len(jumps), dtype=bool)
    if has_heading:
        headings = np.array([float(r["heading_deg"]) for r in selected])
        heading_jumps = np.abs(angular_diff_deg(np.diff(headings))) / dt  # deg/s
        heading_outlier = mad_outliers(heading_jumps)

    combined_outlier_step = position_outlier | heading_outlier
    flagged_point_idx = set()
    for i, is_out in enumerate(combined_outlier_step):
        if is_out:
            flagged_point_idx.add(i)
            flagged_point_idx.add(i + 1)

    consistent = len(selected) - len(flagged_point_idx)
    return {
        "config": config_name,
        "total_timestamps": total,
        "gate_pass_successes": len(selected),
        "gate_pass_rate": len(selected) / total if total else 0.0,
        "trajectory_consistent_successes": consistent,
        "trajectory_consistent_rate": consistent / total if total else 0.0,
        "flagged_as_position_or_heading_outlier": len(flagged_point_idx),
        "has_heading_logged": has_heading,
        "median_position_speed_px_per_s": float(np.median(jumps)),
        "median_heading_speed_deg_per_s": float(np.median(heading_jumps)) if has_heading else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    with args.csv.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    configs = list(dict.fromkeys(r["config"] for r in rows))

    results = [analyze(rows, c) for c in configs]
    summary = {
        "source_csv": str(args.csv),
        "method": (
            "MAD-based outlier flag (|modified z| > 3.5) on consecutive position-jump and "
            "heading-jump magnitudes, each divided by the elapsed time between the two accepted "
            "poses (px/s, deg/s) since failed timestamps leave gaps of 10/20/30s+ that would "
            "otherwise dominate the statistic. No absolute meters-per-pixel scale is available for "
            "this map, so this is a relative/self-normalizing check, not an absolute speed gate."
        ),
        "per_config": results,
    }
    out_path = args.out or args.csv.with_name(args.csv.stem + "_trajectory_consistency.json")
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
