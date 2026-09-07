"""Offline fixed-map cross-camera PoC for floor 1.

Runs the existing localization stack on sampled frames from a wide-lens video:
  V0: original query frame
  V2: center crop approximating the map camera FoV
  V3: pinhole virtual-camera reprojection approximating the map camera FoV

This is intentionally isolated from the production API. V3 uses an estimated
source horizontal FoV unless a real camera calibration is supplied; its output
must therefore be treated as a geometry prototype, not final calibration.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_DIR.parent.parent
APP_DIR = BACKEND_DIR / "app"

# The application normally adds these paths while starting uvicorn. Keep the
# PoC runnable directly from PowerShell without changing production imports.
for path in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core import localization as loc  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402


DEFAULT_VIDEO = REPO_ROOT / "floor1_wide.MOV"
DEFAULT_DATA = APP_DIR / "data" / "map_data" / "result_floor1_4"
DEFAULT_MAP = APP_DIR / "data" / "map" / "floor1.jpg"
DEFAULT_GRAPH = APP_DIR / "data" / "json_map" / "floor1.json"
DEFAULT_OUT = SCRIPT_DIR / "out"


def camera_matrix_from_hfov(width: int, height: int, hfov_deg: float) -> np.ndarray:
    fx = (width / 2.0) / np.tan(np.deg2rad(hfov_deg) / 2.0)
    fy = fx
    return np.array(
        [[fx, 0.0, (width - 1) / 2.0],
         [0.0, fy, (height - 1) / 2.0],
         [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def scale_intrinsics(k: np.ndarray, width: int, height: int, ref_width: int, ref_height: int) -> np.ndarray:
    sx = width / float(ref_width)
    sy = height / float(ref_height)
    out = np.asarray(k, dtype=np.float64).copy()
    out[0, 0] *= sx
    out[0, 2] *= sx
    out[1, 1] *= sy
    out[1, 2] *= sy
    return out


def center_crop_to_hfov(image: np.ndarray, source_hfov: float, target_hfov: float) -> np.ndarray:
    """Crop the central source region whose pinhole FoV is target_hfov."""
    if target_hfov >= source_hfov:
        return image.copy()
    width = image.shape[1]
    fraction = np.tan(np.deg2rad(target_hfov) / 2.0) / np.tan(np.deg2rad(source_hfov) / 2.0)
    crop_width = max(32, min(width, int(round(width * fraction))))
    x0 = max(0, (width - crop_width) // 2)
    return image[:, x0:x0 + crop_width].copy()


def virtual_pinhole_reproject(
    image: np.ndarray,
    source_hfov: float,
    target_k: np.ndarray,
    output_width: int,
    output_height: int,
) -> np.ndarray:
    """Reproject an estimated pinhole source into the target virtual camera.

    The mapping is inverse-rendered from target rays into source pixels. This
    handles the FOV change consistently with a pinhole model, but does not
    model real lens distortion; real K/D should replace source_hfov in a later
    calibration-backed version.
    """
    source_h, source_w = image.shape[:2]
    source_k = camera_matrix_from_hfov(source_w, source_h, source_hfov)
    target_k = scale_intrinsics(target_k, output_width, output_height, output_width, output_height)
    # Keep the estimated source camera's principal point aligned with the
    # target/map camera. This makes the identity case truly identity when the
    # source and target FoV are equal; using the raw image center here would
    # introduce a few-pixel shift and can break a marginal feature match.
    source_k[0, 2] = target_k[0, 2] * source_w / float(output_width)
    source_k[1, 2] = target_k[1, 2] * source_h / float(output_height)

    u, v = np.meshgrid(
        np.arange(output_width, dtype=np.float32),
        np.arange(output_height, dtype=np.float32),
    )
    fx_t, fy_t = target_k[0, 0], target_k[1, 1]
    cx_t, cy_t = target_k[0, 2], target_k[1, 2]
    x = (u - cx_t) / fx_t
    y = (v - cy_t) / fy_t
    z = np.ones_like(x)

    # Target and source share the optical axis; only their intrinsics differ.
    src_u = source_k[0, 0] * (x / z) + source_k[0, 2]
    src_v = source_k[1, 1] * (y / z) + source_k[1, 2]
    return cv2.remap(
        image,
        src_u.astype(np.float32),
        src_v.astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )


def read_frame(cap: cv2.VideoCapture, frame_index: int) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
    ok, frame = cap.read()
    return frame if ok else None


def run_variant(localizer: Localizer, frame: np.ndarray, variant: str, source_hfov: float, target_hfov: float):
    if variant == "V0":
        processed = frame
    elif variant == "V2":
        processed = center_crop_to_hfov(frame, source_hfov, target_hfov)
    elif variant == "V3":
        processed = virtual_pinhole_reproject(
            frame,
            source_hfov=source_hfov,
            target_k=localizer.K,
            output_width=frame.shape[1],
            output_height=frame.shape[0],
        )
    else:
        raise ValueError(f"Unknown variant: {variant}")

    started = time.perf_counter()
    result, xy = localizer.localize(processed)
    elapsed = time.perf_counter() - started
    return processed, result, xy, elapsed


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "frame", "time_s", "variant", "success", "method", "x_px", "y_px",
        "matched_keyframe", "num_matches", "num_inliers", "inlier_ratio",
        "median_reproj_error", "elapsed_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plot_results(path: Path, floor_plan: np.ndarray, rows: list[dict], title: str) -> None:
    colors = {"V0": "#d62728", "V2": "#ff8c00", "V3": "#1479ff"}
    labels = {
        "V0": "V0 original",
        "V2": "V2 center crop",
        "V3": "V3 virtual pinhole (estimated FoV)",
    }
    fig, ax = plt.subplots(figsize=(15, 9), dpi=140)
    ax.imshow(cv2.cvtColor(floor_plan, cv2.COLOR_BGR2RGB))
    for variant in ("V0", "V2", "V3"):
        points = [
            (float(row["x_px"]), float(row["y_px"]))
            for row in rows
            if row["variant"] == variant and row["success"] == "1"
            and row["x_px"] != "" and row["y_px"] != ""
        ]
        if not points:
            continue
        xy = np.asarray(points, dtype=np.float64)
        ax.plot(xy[:, 0], xy[:, 1], "-", color=colors[variant], linewidth=1.2, alpha=0.65, label=labels[variant])
        ax.scatter(xy[:, 0], xy[:, 1], s=10, color=colors[variant], alpha=0.75)
        ax.scatter(xy[0, 0], xy[0, 1], s=70, marker="o", color=colors[variant], edgecolor="white", linewidth=1.0)
        ax.scatter(xy[-1, 0], xy[-1, 1], s=90, marker="X", color=colors[variant], edgecolor="white", linewidth=1.0)
    ax.set_title(title)
    ax.set_xlim(0, floor_plan.shape[1])
    ax.set_ylim(floor_plan.shape[0], 0)
    ax.set_aspect("equal")
    ax.legend(loc="best")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=60)
    parser.add_argument("--source-hfov", type=float, default=90.0)
    parser.add_argument("--target-hfov", type=float, default=None)
    parser.add_argument(
        "--tag",
        type=str,
        default="v0_v2_v3",
        help="Suffix for output files so different FoV experiments are preserved.",
    )
    parser.add_argument("--retrieval", choices=["cosplace", "megaloc", "netvlad"], default="cosplace")
    args = parser.parse_args()

    for path in (args.video, args.data_dir, args.map_image, args.graph_json):
        if not path.exists():
            raise FileNotFoundError(path)
    args.out.mkdir(parents=True, exist_ok=True)

    floor_plan = cv2.imread(str(args.map_image), cv2.IMREAD_COLOR)
    if floor_plan is None:
        raise RuntimeError(f"Cannot read floor plan: {args.map_image}")

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_s = frame_count / fps if fps > 0 else 0.0
    step_frames = max(1, int(round(args.step_seconds * fps)))
    frame_indices = list(range(0, frame_count, step_frames))[: max(1, args.max_frames)]
    print(json.dumps({
        "video": str(args.video), "fps": fps, "frames": frame_count,
        "duration_s": duration_s, "sampled_frames": len(frame_indices),
        "source_hfov_assumed_deg": args.source_hfov,
    }, indent=2), flush=True)

    localizer = Localizer(
        floor_id="floor1",
        data_dir=args.data_dir,
        floor_plan_path=args.map_image,
        json_map_path=args.graph_json,
        matching_mode="superpoint",
        retrieval_mode=args.retrieval,
    )
    reference_image = None
    reference_dir = args.data_dir / "keyframes_superpoint"
    if not reference_dir.exists():
        reference_dir = args.data_dir / "keyframes"
    for kf_dir in sorted(reference_dir.iterdir()):
        candidate = kf_dir / "image.png"
        if not candidate.exists():
            candidate = kf_dir / "image.jpg"
        if candidate.exists():
            reference_image = cv2.imread(str(candidate), cv2.IMREAD_COLOR)
            if reference_image is not None:
                break
    if reference_image is None:
        raise RuntimeError(f"Could not read a map keyframe image from {reference_dir}")
    reference_height, reference_width = reference_image.shape[:2]
    target_hfov = args.target_hfov
    if target_hfov is None:
        target_hfov = float(np.rad2deg(2.0 * np.arctan(reference_width / (2.0 * localizer.K[0, 0]))))
    print(
        f"Using map camera image={reference_width}x{reference_height}; "
        f"target/map horizontal FoV ~= {target_hfov:.2f} deg",
        flush=True,
    )

    rows: list[dict] = []
    variants = ("V0", "V2", "V3")
    for ordinal, frame_index in enumerate(frame_indices, start=1):
        frame = read_frame(cap, frame_index)
        if frame is None:
            print(f"[WARN] frame {frame_index} could not be decoded", flush=True)
            continue
        time_s = frame_index / fps if fps > 0 else 0.0
        print(f"[{ordinal}/{len(frame_indices)}] frame={frame_index} t={time_s:.1f}s", flush=True)
        for variant in variants:
            _, result, xy, elapsed = run_variant(localizer, frame, variant, args.source_hfov, target_hfov)
            success = bool(result.get("success")) and xy is not None
            rows.append({
                "frame": frame_index,
                "time_s": round(time_s, 3),
                "variant": variant,
                "success": int(success),
                "method": result.get("method") or "",
                "x_px": round(float(xy[0]), 3) if success else "",
                "y_px": round(float(xy[1]), 3) if success else "",
                "matched_keyframe": result.get("matched_keyframe") or "",
                "num_matches": result.get("num_matches", 0),
                "num_inliers": result.get("num_inliers", 0),
                "inlier_ratio": result.get("inlier_ratio", 0.0),
                "median_reproj_error": result.get("median_reproj_error") if result.get("median_reproj_error") is not None else "",
                "elapsed_s": round(elapsed, 3),
            })
            print(
                f"  {variant}: success={success} method={result.get('method')} "
                f"inliers={result.get('num_inliers', 0)} reproj={result.get('median_reproj_error')}",
                flush=True,
            )
    cap.release()

    output_tag = re.sub(r"[^A-Za-z0-9_-]+", "_", args.tag).strip("_") or "run"
    csv_path = args.out / f"floor1_wide_{output_tag}.csv"
    plot_path = args.out / f"floor1_wide_{output_tag}_trajectory.png"
    summary_path = args.out / f"floor1_wide_{output_tag}_summary.json"
    write_csv(csv_path, rows)
    plot_results(
        plot_path,
        floor_plan,
        rows,
        f"Floor 1 fixed-map localization: {args.video.name} | source HFoV assumed {args.source_hfov:.1f}°",
    )
    summary = {
        "video": str(args.video),
        "map_data": str(args.data_dir),
        "source_hfov_assumed_deg": args.source_hfov,
        "target_hfov_deg": target_hfov,
        "sampled_frames": len(frame_indices),
        "results": {
            variant: {
                "attempts": sum(1 for row in rows if row["variant"] == variant),
                "successes": sum(1 for row in rows if row["variant"] == variant and row["success"] == 1),
            }
            for variant in variants
        },
        "outputs": {"csv": str(csv_path), "plot": str(plot_path)},
        "note": "V3 uses estimated pinhole source FoV; real K/D calibration is still required for final claims.",
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
