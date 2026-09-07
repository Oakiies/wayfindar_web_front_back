"""Robustly aggregate per-frame focal estimates into one video-level prior.

This is a lightweight adaptation of multi-view/video self-calibration ideas:
the camera intrinsics are assumed constant within one clip, so per-frame focal
estimates are aggregated robustly instead of selecting a new focal per frame.
It is not a reproduction of a full self-calibration bundle-adjustment paper.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import median


def read_values(path: Path, column: str) -> list[float]:
    values: list[float] = []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows", [])
        for row in rows:
            try:
                number = float(row.get(column))
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number > 0:
                values.append(number)
        return values
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            value = row.get(column, "")
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number > 0:
                values.append(number)
    return values


def summarize(values: list[float], map_focal: float, width: int) -> dict:
    if not values:
        return {"n": 0, "error": "no valid focal estimates"}
    med = float(median(values))
    deviations = [abs(value - med) for value in values]
    mad = float(median(deviations))
    threshold = max(2.5 * mad, 40.0)
    inliers = [value for value in values if abs(value - med) <= threshold]
    robust_f = float(median(inliers))
    hfov = math.degrees(2.0 * math.atan((width / 2.0) / robust_f))
    return {
        "n": len(values),
        "median_focal_px": med,
        "mad_px": mad,
        "robust_threshold_px": threshold,
        "robust_inlier_n": len(inliers),
        "robust_focal_px": robust_f,
        "focal_ratio_to_map": robust_f / map_focal,
        "implied_hfov_deg": hfov,
        "min_focal_px": min(values),
        "max_focal_px": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pnpf-csv", type=Path, required=True)
    parser.add_argument("--geocalib-csv", type=Path)
    parser.add_argument("--map-focal", type=float, default=1400.0)
    parser.add_argument("--image-width", type=int, default=1920)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    pnpf_values = read_values(args.pnpf_csv, "best_fit_focal_px")
    result = {
        "experiment": "video-level robust focal aggregation",
        "paper_relation": {
            "inspiration": "multi-view/video self-calibration",
            "note": "robust session-level aggregation; not a reproduction of full Deep Geometry-Aware Camera Self-Calibration from Video",
        },
        "assumption": "intrinsics are constant within one video/session",
        "map_focal_px": args.map_focal,
        "image_width_px": args.image_width,
        "pnpf_adaptation": summarize(pnpf_values, args.map_focal, args.image_width),
    }
    if args.geocalib_csv:
        geocalib_values = read_values(args.geocalib_csv, "focal_px")
        result["geocalib"] = summarize(geocalib_values, args.map_focal, args.image_width)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
