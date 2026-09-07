"""Paper-backed query-side sweep for fixed-map floor-1 localization.

The map and production retrieval/matching stack are immutable in this PoC:
MegaLoc -> SuperPoint/LightGlue -> PnP.  Only the query image is changed.

Virtual-camera rendering follows the ray rotation/reprojection construction
used by 360Loc (Huang et al., CVPR 2024).  Unlike 360Loc's panorama source,
this input is a finite-FoV phone frame, so rays outside the source image are
marked invalid instead of synthesising unseen content.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_DIR.parent.parent
APP_DIR = BACKEND_DIR / "app"
for path in (BACKEND_DIR, APP_DIR, BACKEND_DIR / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core import localization as loc  # noqa: E402
from app.core.localizer import Localizer  # noqa: E402
from app.services.accel import accelerate_localizer  # noqa: E402
import app.localization_config as localization_config  # noqa: E402


DEFAULT_VIDEO = REPO_ROOT / "floor1_wide.MOV"
DEFAULT_DATA = APP_DIR / "data" / "map_data" / "result_floor1_4"
DEFAULT_MAP = APP_DIR / "data" / "map" / "floor1.jpg"
DEFAULT_GRAPH = APP_DIR / "data" / "json_map" / "floor1.json"
DEFAULT_OUT = SCRIPT_DIR / "out"

PAPERS = {
    "360Loc": "https://openaccess.thecvf.com/content/CVPR2024/html/"
    "Huang_360Loc_A_Dataset_and_Benchmark_for_Omnidirectional_Visual_"
    "Localization_with_CVPR_2024_paper.html",
    "360Loc_code": "https://github.com/HuajianUP/360Loc/blob/main/process.py",
    "MegaLoc": "https://arxiv.org/abs/2502.17237",
    "SuperPoint": "https://openaccess.thecvf.com/content_cvpr_2018_workshops/"
    "w9/html/DeTone_SuperPoint_Self-Supervised_Interest_CVPR_2018_paper.html",
    "LightGlue": "https://openaccess.thecvf.com/content/ICCV2023/html/"
    "Lindenberger_LightGlue_Local_Feature_Matching_at_Light_Speed_"
    "ICCV_2023_paper.html",
}


@dataclass(frozen=True)
class QueryConfig:
    name: str
    kind: str
    exact_size: bool
    source_hfov: float | None = None
    yaw_deg: float = 0.0


def parse_numbers(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def find_reference_size(data_dir: Path) -> tuple[int, int]:
    for root_name in ("keyframes_superpoint", "keyframes"):
        root = data_dir / root_name
        if not root.exists():
            continue
        for kf_dir in sorted(root.iterdir()):
            for filename in ("image.png", "image.jpg"):
                image = cv2.imread(str(kf_dir / filename), cv2.IMREAD_COLOR)
                if image is not None:
                    return int(image.shape[1]), int(image.shape[0])
    raise RuntimeError(f"No keyframe image found under {data_dir}")


def pinhole_k(width: int, height: int, hfov_deg: float) -> np.ndarray:
    focal = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    return np.array(
        [[focal, 0.0, (width - 1.0) / 2.0],
         [0.0, focal, (height - 1.0) / 2.0],
         [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def virtual_camera(
    image: np.ndarray,
    source_hfov: float,
    target_k: np.ndarray,
    output_size: tuple[int, int],
    yaw_deg: float = 0.0,
) -> tuple[np.ndarray, float]:
    """Inverse-render target pinhole rays into a finite-FoV pinhole source."""
    output_w, output_h = output_size
    source_h, source_w = image.shape[:2]
    source_k = pinhole_k(source_w, source_h, source_hfov)

    u, v = np.meshgrid(
        np.arange(output_w, dtype=np.float32) + 0.5,
        np.arange(output_h, dtype=np.float32) + 0.5,
    )
    rays = np.stack(
        ((u - target_k[0, 2]) / target_k[0, 0],
         (v - target_k[1, 2]) / target_k[1, 1],
         np.ones_like(u)),
        axis=0,
    ).reshape(3, -1)

    yaw = math.radians(yaw_deg)
    rotation = np.array(
        [[math.cos(yaw), 0.0, math.sin(yaw)],
         [0.0, 1.0, 0.0],
         [-math.sin(yaw), 0.0, math.cos(yaw)]],
        dtype=np.float64,
    )
    source_rays = rotation @ rays
    z = source_rays[2]
    src_u = source_k[0, 0] * source_rays[0] / np.maximum(z, 1e-8) + source_k[0, 2]
    src_v = source_k[1, 1] * source_rays[1] / np.maximum(z, 1e-8) + source_k[1, 2]
    valid = (
        (z > 0.0)
        & (src_u >= 0.0) & (src_u < source_w - 1.0)
        & (src_v >= 0.0) & (src_v < source_h - 1.0)
    )
    map_x = np.where(valid, src_u, -1.0).reshape(output_h, output_w).astype(np.float32)
    map_y = np.where(valid, src_v, -1.0).reshape(output_h, output_w).astype(np.float32)
    rendered = cv2.remap(
        image, map_x, map_y, interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
    )
    return rendered, float(np.mean(valid))


def fov_preserving_canvas(
    target_k: np.ndarray, reference_size: tuple[int, int], source_hfov: float, map_hfov_deg: float,
) -> tuple[tuple[int, int], np.ndarray]:
    """Expand the render canvas so a wider source FoV is not cropped to the map's FoV.

    The original construction rendered into `reference_size` using the map's own
    K: when the assumed source HFoV exceeds the map's HFoV, that forces sampling
    a smaller-than-full center crop of the source image and upsampling it back to
    `reference_size`, which reduces effective pixels-per-degree for SuperPoint
    rather than preserving it. Here the canvas grows so the map's own
    pixels-per-degree (its focal length) is kept, but the *entire* wider FoV of
    the source is still covered -- no periphery is thrown away and no artificial
    upsampling occurs for the shared region.
    """
    if source_hfov <= map_hfov_deg:
        return reference_size, target_k
    scale = math.tan(math.radians(source_hfov / 2.0)) / math.tan(math.radians(map_hfov_deg / 2.0))
    new_w = int(round(reference_size[0] * scale))
    new_h = int(round(reference_size[1] * scale))
    expanded_k = target_k.copy()
    expanded_k[0, 2] = (new_w - 1.0) / 2.0
    expanded_k[1, 2] = (new_h - 1.0) / 2.0
    return (new_w, new_h), expanded_k


def prepare_query(
    frame: np.ndarray,
    config: QueryConfig,
    target_k: np.ndarray,
    reference_size: tuple[int, int],
    map_hfov_deg: float,
) -> tuple[np.ndarray, float]:
    if config.kind == "raw":
        return frame.copy(), 1.0
    if config.kind == "virtual_camera" and config.source_hfov is not None:
        output_size, k_for_render = fov_preserving_canvas(
            target_k, reference_size, config.source_hfov, map_hfov_deg
        )
        return virtual_camera(
            frame, config.source_hfov, k_for_render, output_size, config.yaw_deg
        )
    raise ValueError(config)


class AttemptObserver:
    """Collect failure-stage evidence without altering acceptance thresholds."""

    def __init__(self) -> None:
        self.match_counts: list[int] = []
        self.raw_pnp_inliers: list[int] = []
        self.accepted_pnp_inliers: list[int] = []
        self.quality: list[tuple[float, float]] = []

    @property
    def max_matches(self) -> int:
        return max(self.match_counts, default=0)

    @property
    def max_raw_inliers(self) -> int:
        return max(self.raw_pnp_inliers, default=0)

    def failure_stage(self, success: bool) -> str:
        if success:
            return "success"
        if self.max_matches < 4:
            return "local_matching"
        if self.max_raw_inliers < 10:
            return "pnp_insufficient_inliers"
        return "quality_or_pose_gate"


@contextmanager
def observe_attempt(observer: AttemptObserver, exact_size: tuple[int, int] | None):
    original_size = loc.get_reference_image_size_from_intrinsics
    original_match = loc.match_2d_3d
    original_pnp = loc.solve_pnp_ransac
    original_quality = loc.compute_pnp_quality

    if exact_size is not None:
        loc.get_reference_image_size_from_intrinsics = lambda _k: exact_size

    def match_wrapper(*args, **kwargs):
        points_2d, points_3d = original_match(*args, **kwargs)
        observer.match_counts.append(0 if points_2d is None else int(len(points_2d)))
        return points_2d, points_3d

    def pnp_wrapper(points_2d, points_3d, k, **kwargs):
        answer = original_pnp(points_2d, points_3d, k, **kwargs)
        success, _r, _t, inliers = answer
        accepted_count = 0 if inliers is None else int(len(inliers))
        observer.accepted_pnp_inliers.append(accepted_count)
        raw_count = accepted_count
        if not success and points_2d is not None and len(points_2d) >= 4:
            ok, _rv, _tv, raw_inliers = cv2.solvePnPRansac(
                objectPoints=points_3d,
                imagePoints=points_2d,
                cameraMatrix=k,
                distCoeffs=np.zeros(4),
                reprojectionError=float(kwargs.get("reproj_threshold", 8.0)),
                iterationsCount=int(kwargs.get("iterations", 1000)),
                flags=cv2.SOLVEPNP_P3P,
            )
            raw_count = int(len(raw_inliers)) if ok and raw_inliers is not None else 0
        observer.raw_pnp_inliers.append(raw_count)
        return answer

    def quality_wrapper(*args, **kwargs):
        ratio, error = original_quality(*args, **kwargs)
        observer.quality.append((float(ratio), float(error)))
        return ratio, error

    loc.match_2d_3d = match_wrapper
    loc.solve_pnp_ransac = pnp_wrapper
    loc.compute_pnp_quality = quality_wrapper
    try:
        yield
    finally:
        loc.get_reference_image_size_from_intrinsics = original_size
        loc.match_2d_3d = original_match
        loc.solve_pnp_ransac = original_pnp
        loc.compute_pnp_quality = original_quality


def run_attempt(
    localizer: Localizer,
    query: np.ndarray,
    config: QueryConfig,
    reference_size: tuple[int, int],
) -> tuple[dict, tuple[float, float] | None, float, AttemptObserver]:
    observer = AttemptObserver()
    started = time.perf_counter()
    exact = reference_size if config.exact_size else None
    with observe_attempt(observer, exact):
        result, xy = localizer.localize(query)
    return result, xy, time.perf_counter() - started, observer


def safe_tag(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "run"


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: list[dict], configs: list[QueryConfig]) -> dict:
    by_config = {}
    for config in configs:
        selected = [row for row in rows if row["config"] == config.name]
        successes = [row for row in selected if row["success"] == 1]
        by_config[config.name] = {
            "attempts": len(selected),
            "successes": len(successes),
            "success_rate": len(successes) / len(selected) if selected else 0.0,
            "median_inliers_on_success": float(np.median([r["num_inliers"] for r in successes])) if successes else None,
            "median_reproj_on_success": float(np.median([r["median_reproj_error"] for r in successes])) if successes else None,
            "failure_stages": {
                stage: sum(1 for row in selected if row["failure_stage"] == stage)
                for stage in ("local_matching", "pnp_insufficient_inliers", "quality_or_pose_gate")
            },
        }

    by_hfov = {}
    frame_ids = sorted({int(row["frame"]) for row in rows})
    for hfov in sorted({c.source_hfov for c in configs if c.source_hfov is not None}):
        names = {c.name for c in configs if c.source_hfov == hfov}
        winning = []
        for frame_id in frame_ids:
            candidates = [
                row for row in rows
                if int(row["frame"]) == frame_id and row["config"] in names and row["success"] == 1
            ]
            if candidates:
                candidates.sort(
                    key=lambda row: (
                        int(row["num_inliers"]), float(row["inlier_ratio"]),
                        -float(row["median_reproj_error"]),
                    ),
                    reverse=True,
                )
                winning.append(candidates[0])
        by_hfov[f"vc_multi_hfov_{hfov:g}"] = {
            "frames": len(frame_ids),
            "successes_any_yaw": len(winning),
            "success_rate": len(winning) / len(frame_ids) if frame_ids else 0.0,
            "selection": "max inliers, then max inlier ratio, then min median reprojection error",
        }
    return {"per_config": by_config, "multi_view_per_hfov": by_hfov}


def plot_trajectory(path: Path, floor_plan: np.ndarray, rows: list[dict]) -> None:
    configs = list(dict.fromkeys(row["config"] for row in rows))
    cmap = plt.get_cmap("tab10")
    fig, ax = plt.subplots(figsize=(15, 9), dpi=140)
    ax.imshow(cv2.cvtColor(floor_plan, cv2.COLOR_BGR2RGB))
    for idx, name in enumerate(configs):
        points = [
            (float(r["x_px"]), float(r["y_px"])) for r in rows
            if r["config"] == name and r["success"] == 1
        ]
        if not points:
            continue
        points_np = np.asarray(points)
        color = cmap(idx % 10)
        ax.plot(points_np[:, 0], points_np[:, 1], "-", lw=1.0, alpha=0.55, color=color)
        ax.scatter(points_np[:, 0], points_np[:, 1], s=12, alpha=0.75, color=color, label=name)
    ax.set_xlim(0, floor_plan.shape[1])
    ax.set_ylim(floor_plan.shape[0], 0)
    ax.set_aspect("equal")
    ax.set_title("Floor 1 fixed-map localization — production pipeline, query-side sweep")
    ax.legend(fontsize=7, loc="best")
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
    parser.add_argument("--step-seconds", type=float, default=20.0)
    parser.add_argument("--max-frames", type=int, default=27)
    parser.add_argument("--hfovs", default="90", help="Comma-separated assumed source HFoVs")
    parser.add_argument("--yaws", default="0", help="Comma-separated virtual-camera yaw angles")
    parser.add_argument("--skip-raw", action="store_true")
    parser.add_argument(
        "--top-k", type=int, default=4,
        help="MegaLoc shortlist size; 360Loc reports retrieval at k=1,5,10.",
    )
    parser.add_argument("--tag", default="production_coarse")
    args = parser.parse_args()

    for path in (args.video, args.data_dir, args.map_image, args.graph_json):
        if not path.exists():
            raise FileNotFoundError(path)
    args.out.mkdir(parents=True, exist_ok=True)

    reference_size = find_reference_size(args.data_dir)
    configs: list[QueryConfig] = []
    if not args.skip_raw:
        configs.extend((
            QueryConfig("raw_production", "raw", exact_size=False),
            QueryConfig("raw_exact_1920x1080", "raw", exact_size=True),
        ))
    for hfov in parse_numbers(args.hfovs):
        for yaw in parse_numbers(args.yaws):
            configs.append(QueryConfig(
                f"vc_hfov_{hfov:g}_yaw_{yaw:+g}", "virtual_camera", True, hfov, yaw
            ))

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {args.video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(args.step_seconds * fps)))
    frame_indices = list(range(0, frame_count, step))[:args.max_frames]

    print(json.dumps({
        "video": str(args.video), "fps": fps, "frame_count": frame_count,
        "reference_size": reference_size, "sampled_frames": len(frame_indices),
        "configs": [c.name for c in configs],
    }, indent=2), flush=True)

    localizer = Localizer(
        floor_id="floor1", data_dir=args.data_dir,
        floor_plan_path=args.map_image, json_map_path=args.graph_json,
        matching_mode="superpoint", retrieval_mode="megaloc",
    )
    accelerate_localizer(localizer)
    localization_config.LOCALIZATION_PARAMS["top_k"] = int(args.top_k)
    localizer.debug_mode = True

    inferred_size = loc.get_reference_image_size_from_intrinsics(localizer.K)
    map_hfov = math.degrees(2.0 * math.atan(reference_size[0] / (2.0 * localizer.K[0, 0])))
    rows: list[dict] = []
    for ordinal, frame_index in enumerate(frame_indices, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            print(f"[WARN] cannot decode frame {frame_index}", flush=True)
            continue
        print(f"[{ordinal}/{len(frame_indices)}] frame={frame_index} t={frame_index / fps:.1f}s", flush=True)
        for config in configs:
            query, valid_fraction = prepare_query(frame, config, localizer.K, reference_size, map_hfov)
            result, xy, elapsed, observer = run_attempt(localizer, query, config, reference_size)
            success = bool(result.get("success")) and xy is not None
            debug = result.get("debug_info") or {}
            retrieved = debug.get("retrieved_keyframes") or []
            rows.append({
                "frame": frame_index,
                "time_s": round(frame_index / fps, 3),
                "config": config.name,
                "kind": config.kind,
                "source_hfov": "" if config.source_hfov is None else config.source_hfov,
                "yaw_deg": config.yaw_deg,
                "exact_reference_size": int(config.exact_size),
                "valid_pixel_fraction": round(valid_fraction, 6),
                "success": int(success),
                "failure_stage": observer.failure_stage(success),
                "method": result.get("method") or "",
                "x_px": round(float(xy[0]), 3) if success else "",
                "y_px": round(float(xy[1]), 3) if success else "",
                "heading_deg": round(float((result.get("pose") or {}).get("theta")), 3)
                if success and (result.get("pose") or {}).get("theta") is not None else "",
                "matched_keyframe": result.get("matched_keyframe") or "",
                "retrieval_top1": retrieved[0]["keyframe_id"] if retrieved else "",
                "retrieval_top1_score": round(float(retrieved[0]["score"]), 8) if retrieved else "",
                "num_matches": int(result.get("num_matches", 0)),
                "num_inliers": int(result.get("num_inliers", 0)),
                "inlier_ratio": float(result.get("inlier_ratio", 0.0)),
                "median_reproj_error": result.get("median_reproj_error") if result.get("median_reproj_error") is not None else "",
                "max_candidate_matches": observer.max_matches,
                "max_raw_pnp_inliers": observer.max_raw_inliers,
                "elapsed_s": round(elapsed, 3),
            })
            print(
                f"  {config.name}: ok={int(success)} matches={observer.max_matches} "
                f"raw_inliers={observer.max_raw_inliers} accepted={result.get('num_inliers', 0)} "
                f"stage={observer.failure_stage(success)}",
                flush=True,
            )
    cap.release()

    tag = safe_tag(args.tag)
    csv_path = args.out / f"floor1_wide_{tag}.csv"
    summary_path = args.out / f"floor1_wide_{tag}_summary.json"
    plot_path = args.out / f"floor1_wide_{tag}_trajectory.png"
    write_csv(csv_path, rows)
    floor_plan = cv2.imread(str(args.map_image), cv2.IMREAD_COLOR)
    if floor_plan is not None:
        plot_trajectory(plot_path, floor_plan, rows)

    summary = {
        "experiment": "paper-backed fixed-map query-side sweep",
        "pipeline_locked": {
            "retrieval": "MegaLoc",
            "local_features": "SuperPoint",
            "matcher": localizer.superglue_matcher.__class__.__name__,
            "pose": "PnP-RANSAC",
            "top_k": int(args.top_k),
            "map_data": str(args.data_dir),
            "map_rebuilt": False,
        },
        "camera": {
            "K": localizer.K.tolist(),
            "keyframe_size": list(reference_size),
            "size_inferred_by_current_code": list(inferred_size) if inferred_size else None,
            "map_hfov_deg": map_hfov,
        },
        "sampling": {
            "fps": fps, "video_frames": frame_count,
            "step_seconds": args.step_seconds, "sampled_frames": len(frame_indices),
        },
        "results": aggregate(rows, configs),
        "papers_and_official_code": PAPERS,
        "limitations": [
            "Source HFoV is swept because the MOV file does not provide calibrated K/distortion.",
            "The source is not panoramic; invalid virtual-camera rays remain black.",
            "Success means the unchanged production quality gates accepted PnP, not metric accuracy against ground truth.",
        ],
        "outputs": {"csv": str(csv_path), "trajectory": str(plot_path)},
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
