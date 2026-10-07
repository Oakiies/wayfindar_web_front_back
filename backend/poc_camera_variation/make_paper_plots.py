"""Research-paper-style "quality of result" plots for P4Pf, using only real
photos/frames (no synthetic crop/resize/zoom): the images_compare normal +
wide lens photos (floor5) and the iPhone 11 random frames (floor1).

Reads:
  backend/poc_camera_variation/out/images_compare/results.json  (map K, wide focal estimate)
  backend/evidence/images_compare_web/iphone11_data.js          (iPhone 11 random frames)
  backend/poc_camera_variation/out/p4pf_stats.json               (from collect_p4pf_stats.py)

Writes PNGs to backend/poc_camera_variation/out/plots/:
  p4pf_focal_parity.png       -- P4Pf estimated focal vs. reference focal, per image (agreement plot)
  p4pf_reproj_hist.png        -- distribution of P4Pf reprojection error, by camera group
  p4pf_features_vs_error.png -- reprojection error & relative focal error vs. number of matched features
  selfcal_convergence_floor1_iphone11.png -- committed focal + naive-vs-selfcal drift, floor1/iPhone11 walk
  selfcal_convergence_floor5_2.png        -- committed focal + naive-vs-selfcal drift, floor5_2 walk

Run:
  cd backend/poc_camera_variation
  ..\.venv\Scripts\python.exe make_paper_plots.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
WEB_DIR = BACKEND_DIR / "evidence" / "images_compare_web"
OUT_DIR = SCRIPT_DIR / "out"
PLOTS_DIR = OUT_DIR / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
})

GROUP_COLORS = {
    "floor5-normal": "#0d6efd",
    "floor5-wide": "#e6484b",
    "floor1-iphone11": "#2ecc71",
}

LABELED_FLOOR_COLORS = {
    "floor1": "#2a78d6",
    "floor2": "#1baf7a",
    "floor3": "#eb6834",
    "floor4": "#c85683",
    "floor5": "#7b61a8",
}


def load_js_const(path: Path):
    text = path.read_text(encoding="utf-8")
    text = text.split("=", 1)[1].strip()
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text)


def norm(p: Path) -> str:
    return str(p.resolve().relative_to(BACKEND_DIR)).replace("\\", "/")


def build_reference_lookup():
    """image path (relative to BACKEND_DIR, forward slashes) -> (group, reference_focal_px)"""
    lookup: dict[str, tuple[str, float]] = {}

    ic_results = json.loads((SCRIPT_DIR / "out" / "images_compare" / "results.json").read_text(encoding="utf-8"))
    map_focal = ic_results["map_K"]["f"]
    wide_focal = ic_results["wide_focal_est"]
    evidence_dir = BACKEND_DIR / "evidence"
    for pt in ic_results["points"]:
        for shot in pt["shots"]:
            lookup[norm(evidence_dir / shot["normal_img"])] = ("floor5-normal", map_focal)
            lookup[norm(evidence_dir / shot["wide_img"])] = ("floor5-wide", wide_focal)

    idata = load_js_const(WEB_DIR / "iphone11_data.js")
    for f in idata["frames"]:
        # No independent ground truth for this device: use the production
        # self-calibrator's converged focal at that point in the video as the
        # best available reference (it settles to a stable ~905-915px plateau).
        lookup[norm(WEB_DIR / f["img"])] = ("floor1-iphone11", f["focal_used"])

    return lookup


def load_natural_p4pf_records():
    """P4Pf stats restricted to real photos/frames (drop crop/resize/zoom sweeps)."""
    records = json.loads((OUT_DIR / "p4pf_stats.json").read_text(encoding="utf-8"))
    lookup = build_reference_lookup()
    enriched = []
    for r in records:
        key = r["image"].replace("\\", "/")
        if "/transforms/" in key:
            continue  # synthetic crop/resize/zoom sweep -- excluded on request
        ref = lookup.get(key)
        if ref is None or r["p4pf_focal_px"] is None:
            continue
        group, true_focal = ref
        enriched.append({
            **r, "group": group, "true_focal": true_focal,
            "rel_focal_err_pct": (r["p4pf_focal_px"] - true_focal) / true_focal * 100,
        })
    return enriched


# ------------------------------------------------------------- parity plot
def plot_parity(records):
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    all_focals = [r["true_focal"] for r in records] + [r["p4pf_focal_px"] for r in records]
    lo, hi = min(all_focals) * 0.9, max(all_focals) * 1.05
    ax.plot([lo, hi], [lo, hi], "--", color="#888", linewidth=1, label="perfect estimate (y = x)")

    for group, color in GROUP_COLORS.items():
        pts = [r for r in records if r["group"] == group]
        if not pts:
            continue
        sizes = 8 + 1.6 * np.array([r["num_features"] for r in pts])
        ax.scatter([r["true_focal"] for r in pts], [r["p4pf_focal_px"] for r in pts],
                   s=sizes, color=color, alpha=0.6, label=f"{group} (n={len(pts)})", edgecolors="white", linewidth=0.5)

    ax.set_xlabel("Reference focal length (px)")
    ax.set_ylabel("P4Pf estimated focal length (px)")
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.set_title("P4Pf estimate vs. reference focal, per image\n(marker size = number of matched features)")
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "p4pf_focal_parity.png", dpi=150)
    plt.close(fig)


# -------------------------------------------------------- reprojection hist
def plot_reproj_hist(records):
    fig, ax = plt.subplots(figsize=(7, 5))
    bins = np.linspace(0, 8, 25)
    for group, color in GROUP_COLORS.items():
        vals = [r["p4pf_reproj_px"] for r in records if r["group"] == group]
        if not vals:
            continue
        ax.hist(vals, bins=bins, alpha=0.5, color=color, label=f"{group} (n={len(vals)}, median={np.median(vals):.1f}px)")
    ax.set_xlabel("P4Pf median reprojection error (px)")
    ax.set_ylabel("number of images")
    ax.set_title("Distribution of P4Pf reprojection error, by camera")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "p4pf_reproj_hist.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------- P4Pf features plot
# Same keypoint-count buckets as plot_reliability_by_bucket() below, so the
# two figures read as one consistent story instead of two different binnings.
FEATURE_BUCKET_EDGES = (0, 15, 25, 40, 60, 1000)


def _bucket_index(num_features: int) -> int | None:
    for i in range(len(FEATURE_BUCKET_EDGES) - 1):
        if FEATURE_BUCKET_EDGES[i] <= num_features < FEATURE_BUCKET_EDGES[i + 1]:
            return i
    return None


def _rolling_median(xs, ys, window):
    """Sort by x, take a centered rolling median of window `window` -- a
    continuous, less-noisy trend line without collapsing x-resolution down
    to a handful of bucket positions."""
    order = np.argsort(xs)
    xs_s = np.asarray(xs)[order]
    ys_s = np.asarray(ys)[order]
    half = window // 2
    out = np.array([np.median(ys_s[max(0, i - half):min(len(ys_s), i + half + 1)]) for i in range(len(ys_s))])
    return xs_s, out


def plot_p4pf_vs_features(records):
    """x = actual number of matched keypoints, a real linear axis (a
    previous version used 5 evenly-spaced bucket labels -- "0-15", ...,
    "60+" -- which put a 940-wide bucket at the same visual width as a
    15-wide one and quietly flattened the true shape of both trends).

    Left y = reprojection error: bucket medians (same FEATURE_BUCKET_EDGES
    used by plot_reliability_by_bucket) plotted at each bucket's own mean
    x-position with horizontal bars showing the bucket's actual [min, max]
    span, so bucket width is visible instead of implied to be uniform.

    Right y = P4Pf focal length. floor5-normal/floor5-wide have only 7
    images each -- shown as raw points, already maximal detail. floor1-
    iphone11 has 60 -- raw points plus a rolling-median trend line (window
    9) so the trend is visible without binning away x-resolution."""
    # A P4Pf estimate with zero inliers under the reprojection threshold
    # reports median_reproj_error_px = inf (see _score_pose in
    # self_calibration.py) -- a calibration *failure*, not a large-but-real
    # error. Left in, a single inf corrupts np.percentile for its whole
    # bucket (75th percentile becomes inf, so the IQR band silently extends
    # to infinity). Keep them out of the error statistic and report the
    # failure count on the chart instead.
    n_buckets = len(FEATURE_BUCKET_EDGES) - 1
    by_bucket_finite = defaultdict(list)
    by_bucket_x = defaultdict(list)
    n_failed_by_bucket = defaultdict(int)
    for r in records:
        b = _bucket_index(r["num_features"])
        if b is None:
            continue
        by_bucket_x[b].append(r["num_features"])
        if np.isfinite(r["p4pf_reproj_px"]):
            by_bucket_finite[b].append(r["p4pf_reproj_px"])
        else:
            n_failed_by_bucket[b] += 1

    bucket_x, bucket_xerr_lo, bucket_xerr_hi, reproj_med, reproj_yerr_lo, reproj_yerr_hi, n_per_bucket = (
        [], [], [], [], [], [], []
    )
    for i in range(n_buckets):
        xs = by_bucket_x.get(i, [])
        vals = by_bucket_finite.get(i, [])
        if not xs or not vals:
            continue
        cx = float(np.mean(xs))
        bucket_x.append(cx)
        bucket_xerr_lo.append(cx - min(xs))
        bucket_xerr_hi.append(max(xs) - cx)
        med = np.median(vals)
        reproj_med.append(med)
        reproj_yerr_lo.append(med - np.percentile(vals, 25))
        reproj_yerr_hi.append(np.percentile(vals, 75) - med)
        n_per_bucket.append((i, len(vals) + n_failed_by_bucket.get(i, 0), n_failed_by_bucket.get(i, 0)))

    fig, ax1 = plt.subplots(figsize=(10, 6.5))
    c1 = "#333333"
    finite_records = [r for r in records if np.isfinite(r["p4pf_reproj_px"])]
    ax1.scatter([r["num_features"] for r in finite_records],
                [r["p4pf_reproj_px"] for r in finite_records],
                s=18, color="#777777", alpha=0.28, edgecolors="none",
                label="individual reprojection error")
    ax1.errorbar(bucket_x, reproj_med, yerr=[reproj_yerr_lo, reproj_yerr_hi], xerr=[bucket_xerr_lo, bucket_xerr_hi],
                 fmt="o-", color=c1, ecolor=c1, elinewidth=1, capsize=4, alpha=0.9,
                 label="reprojection error median ± IQR")
    ax1.set_xlabel("Number of matched keypoints in the image (actual count)")
    ax1.set_ylabel("P4Pf reprojection error (px)", color=c1)
    ax1.tick_params(axis="y", labelcolor=c1)
    ax1.set_ylim(bottom=0)
    ax1.set_xlim(left=-3)

    ax2 = ax1.twinx()
    for group, color in GROUP_COLORS.items():
        group_records = [r for r in records if r["group"] == group]
        if not group_records:
            continue
        xs = [r["num_features"] for r in group_records]
        ys = [r["p4pf_focal_px"] for r in group_records]
        ax2.scatter(xs, ys, s=22, color=color, alpha=0.5, edgecolors="white", linewidth=0.4,
                    label=f"estimated focal, {group} (n={len(xs)})")
        # floor1-iphone11 has no independent focal ground truth: its
        # per-frame reference in the input data is the converged production
        # estimate, so drawing one horizontal line per frame would be invalid.
        # The two floor5 groups do have fixed reference values.
        if group != "floor1-iphone11":
            true_values = sorted({float(r["true_focal"]) for r in group_records})
            for true_focal in true_values:
                ax2.axhline(true_focal, color=color, linestyle=":", linewidth=1.4, alpha=0.85,
                            label=f"reference focal = {true_focal:.0f}px ({group})")
        if len(xs) >= 15:
            tx, ty = _rolling_median(xs, ys, window=9)
            ax2.plot(tx, ty, "-", color=color, linewidth=2.2, label=f"{group} rolling median (window=9)")
    ax2.set_ylabel("Focal length: P4Pf estimate and ground truth (px)")

    for cx, (i, n, nf) in zip(bucket_x, n_per_bucket):
        label = f"n={n}" + (f" ({nf} failed)" if nf else "")
        ax1.annotate(label, (cx, 0), xycoords=("data", "axes fraction"),
                     textcoords="offset points", xytext=(0, -20),
                     ha="center", fontsize=7.5, color="#888", annotation_clip=False)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper center", bbox_to_anchor=(0.5, -0.20),
               ncol=2, fontsize=7.5, frameon=False)
    ax1.set_title("P4Pf: reprojection error and focal-length recovery vs. feature count\n"
                  "Left y = reprojection error | Right y = estimated focal vs ground truth",
                  fontsize=10.5)
    fig.tight_layout(rect=(0, 0.20, 1, 0.92))
    fig.savefig(PLOTS_DIR / "p4pf_features_vs_error.png", dpi=150)
    plt.close(fig)


# ------------------------------------------------- reliability conclusion plot
def plot_reliability_by_bucket(records, edges=(0, 15, 25, 40, 60, 1000), threshold_pct=10.0):
    """The 'so what' plot: bucket images by matched-keypoint count and show
    the spread of |relative focal error| per bucket against a usability
    threshold. Answers directly: 'how many features does P4Pf need before its
    estimate can be trusted', which is the kind of statement a paper's
    conclusion/discussion section can cite.
    """
    labels = [f"{edges[i]}-{edges[i+1]}" if edges[i+1] < 1000 else f"{edges[i]}+"
              for i in range(len(edges) - 1)]
    buckets = [[] for _ in labels]
    for r in records:
        for i in range(len(edges) - 1):
            if edges[i] <= r["num_features"] < edges[i + 1]:
                buckets[i].append(abs(r["rel_focal_err_pct"]))
                break

    fig, ax = plt.subplots(figsize=(8, 5.5))
    positions = list(range(1, len(labels) + 1))
    bp = ax.boxplot([b if b else [np.nan] for b in buckets], positions=positions, widths=0.6,
                     patch_artist=True, showmeans=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#0d6efd"); patch.set_alpha(0.35)

    ax.axhline(threshold_pct, color="#e6484b", linestyle="--", linewidth=1.5,
               label=f"{threshold_pct:.0f}% usability threshold (illustrative)")

    for x, b in zip(positions, buckets):
        pct_ok = 100 * np.mean(np.array(b) <= threshold_pct) if b else float("nan")
        ax.annotate(f"n={len(b)}\n{pct_ok:.0f}% <= {threshold_pct:.0f}%", (x, -0.14),
                    xycoords=("data", "axes fraction"), ha="center", va="top",
                    fontsize=8, color="#555", annotation_clip=False)

    ax.set_xticks(positions, labels)
    ax.set_xlabel("Number of matched keypoints (bucket)")
    ax.set_ylabel("|P4Pf relative focal error| (%)")
    ax.set_ylim(bottom=0)
    ax.set_title("P4Pf reliability vs. number of matched keypoints\n"
                 "(real photos/frames only -- lower box & whiskers = more trustworthy calibration)")
    ax.legend(loc="upper right")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(PLOTS_DIR / "p4pf_reliability_by_features.png", dpi=150)
    plt.close(fig)
    print("bucket summary (n, median |error|%, % within threshold):")
    for lbl, b in zip(labels, buckets):
        if b:
            print(f"  {lbl}: n={len(b)}, median={np.median(b):.1f}%, "
                  f"{100*np.mean(np.array(b) <= threshold_pct):.0f}% <= {threshold_pct:.0f}%")
        else:
            print(f"  {lbl}: n=0")


# ------------------------------------------------ self-calibration convergence
def plot_selfcal_convergence(data_path: Path, out_name: str, walk_label: str):
    """The production question, not the offline-P4Pf question: walking through
    a floor with a phone that may or may not be the mapping camera, how much
    does the position estimate actually drift if you *don't* self-calibrate,
    and how quickly does the committed focal settle? Left y: focal_used (a
    step function -- it only changes when CameraSelfCalibrator commits a new
    estimate), with the map's own focal as a reference line. Right y:
    drift_px, the distance between the naive-K position and the self-cal-K
    position on the same frame -- there is no independent ground truth for
    these phones, so this is a lower bound on how wrong naive-K is, not the
    absolute position error."""
    idata = load_js_const(data_path)
    frames = sorted(idata["frames"], key=lambda f: f["t"])
    frames = [f for f in frames if f.get("focal_used") is not None and f.get("drift_px") is not None]
    map_focal = idata["map_K"]["f"]
    t = [f["t"] for f in frames]
    focal = [f["focal_used"] for f in frames]
    drift = [f["drift_px"] for f in frames]

    fig, ax1 = plt.subplots(figsize=(9, 5.5))
    c1 = "#0d6efd"
    ax1.step(t, focal, where="post", color=c1, linewidth=2, label="self-cal committed focal (focal_used)")
    ax1.axhline(map_focal, color=c1, linestyle=":", linewidth=1.5, alpha=0.6,
                label=f"map's own focal ({map_focal:.0f}px)")
    ax1.set_xlabel("Time into the walk (s)")
    ax1.set_ylabel("Focal length (px)", color=c1)
    ax1.tick_params(axis="y", labelcolor=c1)

    ax2 = ax1.twinx()
    c2 = "#e6484b"
    ax2.plot(t, drift, "o-", color=c2, alpha=0.7, markersize=4,
              label="naive-K vs. self-cal-K position drift (same frame)")
    ax2.set_ylabel("Position drift (px on floor plan)", color=c2)
    ax2.tick_params(axis="y", labelcolor=c2)
    ax2.set_ylim(bottom=0)

    median_drift = float(np.median(drift))
    ax2.axhline(median_drift, color=c2, linestyle="--", linewidth=1, alpha=0.5)
    ax2.annotate(f"median drift = {median_drift:.1f}px", (t[-1], median_drift),
                 ha="right", va="bottom", fontsize=8, color=c2)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=8)
    ax1.set_title("Self-calibration in production: committed focal and naive-vs-self-cal position drift\n"
                  f"over {walk_label}", fontsize=10.5)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(PLOTS_DIR / out_name, dpi=150)
    plt.close(fig)
    print(f"selfcal convergence ({out_name}): {len(frames)} frames, focal 1st={focal[0]:.0f}px -> last={focal[-1]:.0f}px, "
          f"map={map_focal:.0f}px, drift median={median_drift:.2f}px max={max(drift):.2f}px")


# ------------------------------------------------ focal error over time
def plot_focal_error_over_time(data_path: Path, out_name: str, true_focal: float, walk_label: str, band_pct: float = 1.0):
    """Answers 'as time passes, how close is the estimate to the truth' as
    its own plot instead of forcing the reader to read it off a dual-axis
    focal/drift chart. Only meaningful where an independent true focal
    exists (floor5_2, whose true focal is the map's own 1400px -- floor1's
    iPhone11 has no independent ground truth, see load_natural_p4pf_records
    for why). y = relative error of the committed focal_used vs. true_focal,
    as a step function (it only changes when CameraSelfCalibrator commits);
    a shaded band marks an illustrative "converged" tolerance, and the plot
    is annotated with the first time the estimate enters the band and never
    leaves it again."""
    idata = load_js_const(data_path)
    frames = sorted(idata["frames"], key=lambda f: f["t"])
    frames = [f for f in frames if f.get("focal_used") is not None]
    t = [f["t"] for f in frames]
    err_pct = [(f["focal_used"] - true_focal) / true_focal * 100 for f in frames]

    settle_t = None
    for i in range(len(err_pct)):
        if all(abs(e) <= band_pct for e in err_pct[i:]):
            settle_t = t[i]
            break

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.step(t, err_pct, where="post", color="#0d6efd", linewidth=2, label="P4Pf/self-cal focal error vs. true focal")
    ax.axhline(0, color="#888", linewidth=1)
    ax.axhspan(-band_pct, band_pct, color="#2ecc71", alpha=0.12, label=f"illustrative converged band (+/-{band_pct:.0f}%)")
    ax.scatter(t, err_pct, s=14, color="#0d6efd", zorder=3)

    if settle_t is not None:
        ax.axvline(settle_t, color="#e6484b", linestyle="--", linewidth=1.2)
        ax.annotate(f"stays within +/-{band_pct:.0f}% from t={settle_t:.0f}s",
                    (settle_t, ax.get_ylim()[1] * 0.85), color="#e6484b", fontsize=9,
                    ha="left", va="top", xytext=(6, 0), textcoords="offset points")

    ax.set_xlabel("Time into the walk (s)")
    ax.set_ylabel(f"Focal error vs. true focal ({true_focal:.0f}px) (%)")
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title(f"How close is the self-calibrated focal to the true focal over time?\n{walk_label}", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / out_name, dpi=150)
    plt.close(fig)
    print(f"focal error over time ({out_name}): settle_t={settle_t}, "
          f"final err={err_pct[-1]:+.3f}%, max |err|={max(abs(e) for e in err_pct):.2f}%")


# ------------------------------------------------ focal length -> trajectory
def plot_focal_trajectory_effect(data_path: Path, out_name: str, true_focal: float, floorplan_path: Path, walk_label: str):
    """Show the spatial consequence of using a changing focal estimate.

    The left panel overlays the trajectory localized with the fixed map K and
    the trajectory localized with the self-calibrated K.  The right panels
    align focal length and trajectory separation on the same time axis, so a
    reader can see whether a focal update actually changes the position.
    """
    idata = load_js_const(data_path)
    rows = []
    for f in sorted(idata["frames"], key=lambda x: x["t"]):
        naive = f.get("naive", {}).get("xy")
        selfcal = f.get("selfcal", {}).get("xy")
        focal = f.get("focal_used")
        if naive and selfcal and focal is not None:
            rows.append((f["t"], float(focal), float(naive[0]), float(naive[1]),
                         float(selfcal[0]), float(selfcal[1])))
    if len(rows) < 2:
        print(f"trajectory effect ({out_name}): not enough valid paired positions")
        return

    arr = np.asarray(rows, dtype=float)
    t, focal = arr[:, 0], arr[:, 1]
    naive_xy = arr[:, 2:4]
    selfcal_xy = arr[:, 4:6]
    separation = np.linalg.norm(naive_xy - selfcal_xy, axis=1)
    focal_err_pct = (focal - true_focal) / true_focal * 100.0

    fig = plt.figure(figsize=(12, 6.6))
    gs = fig.add_gridspec(2, 2, width_ratios=(1.08, 1.0), height_ratios=(1.0, 0.9),
                          wspace=0.28, hspace=0.42)
    ax_map = fig.add_subplot(gs[:, 0])
    ax_focal = fig.add_subplot(gs[0, 1])
    ax_sep = fig.add_subplot(gs[1, 1])

    image = plt.imread(floorplan_path)
    ax_map.imshow(image, origin="upper")
    ax_map.plot(naive_xy[:, 0], naive_xy[:, 1], color="#e6484b", linewidth=2,
                linestyle="--", alpha=0.85, label="fixed map K (naive)")
    ax_map.plot(selfcal_xy[:, 0], selfcal_xy[:, 1], color="#0d6efd", linewidth=2,
                alpha=0.9, label="self-calibrated K")
    # Mark where the largest trajectory disagreement occurs.
    imax = int(np.argmax(separation))
    ax_map.scatter(*naive_xy[imax], color="#e6484b", s=38, edgecolor="white", zorder=4)
    ax_map.scatter(*selfcal_xy[imax], color="#0d6efd", s=38, edgecolor="white", zorder=4)
    ax_map.annotate(f"max separation\n{separation[imax]:.1f} px",
                    xy=((naive_xy[imax, 0] + selfcal_xy[imax, 0]) / 2,
                        (naive_xy[imax, 1] + selfcal_xy[imax, 1]) / 2),
                    xytext=(8, -12), textcoords="offset points", fontsize=8,
                    color="#333", arrowprops={"arrowstyle": "-", "color": "#777"})
    ax_map.set_xlim(0, image.shape[1]); ax_map.set_ylim(image.shape[0], 0)
    ax_map.set_aspect("equal")
    ax_map.set_xlabel("Floor-plan x (px)")
    ax_map.set_ylabel("Floor-plan y (px)")
    ax_map.set_title("Trajectory on floor plan")
    ax_map.legend(loc="best", fontsize=8)

    ax_focal.step(t, focal, where="post", color="#0d6efd", linewidth=2,
                  label="estimated focal")
    ax_focal.axhline(true_focal, color="#333", linestyle=":", linewidth=1.3,
                     label=f"true focal = {true_focal:.0f}px")
    ax_focal.set_xlabel("Time (s)")
    ax_focal.set_ylabel("Focal length (px)")
    ax_focal.set_title("Camera estimate over time")
    ax_focal.grid(alpha=0.25)
    ax_focal.legend(fontsize=8)

    ax_sep.plot(t, separation, color="#e6484b", linewidth=1.8)
    ax_sep.fill_between(t, 0, separation, color="#e6484b", alpha=0.12)
    ax_sep.axhline(float(np.median(separation)), color="#e6484b", linestyle="--",
                   linewidth=1, alpha=0.7, label=f"median = {np.median(separation):.2f}px")
    ax_sep.set_xlabel("Time (s)")
    ax_sep.set_ylabel("Trajectory separation (px)")
    ax_sep.set_title("Effect on localized position: naive K vs self-calibrated K")
    ax_sep.grid(alpha=0.25)
    ax_sep.legend(fontsize=8)

    fig.suptitle(f"How focal-length estimation changes the trajectory\n{walk_label}", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(PLOTS_DIR / out_name, dpi=180)
    plt.close(fig)
    print(f"focal -> trajectory ({out_name}): n={len(rows)}, "
          f"median separation={np.median(separation):.2f}px, max={max(separation):.2f}px, "
          f"focal range={min(focal):.1f}-{max(focal):.1f}px")


# ----------------------------------------------- floor5_2 P4Pf three-axis plot
def plot_floor5_2_p4pf_three_axes(stats_path: Path, out_name: str):
    """Three-axis plot from one video only: feature count on x, reprojection
    error on the left y, and raw P4Pf focal estimate against the 1400px camera
    calibration on the right y."""
    if stats_path.suffix == ".jsonl":
        records = [json.loads(line) for line in stats_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        true_focal = 1400.0
    else:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
        records = data["records"]
        true_focal = float(data["true_focal_px"])
    rows = [r for r in records
            if r.get("p4pf_focal_px") is not None and np.isfinite(r.get("p4pf_reproj_px", np.inf))]
    rows.sort(key=lambda r: r["num_features"])
    # Aggregate by the exact feature count.  Each plotted x value therefore
    # means: average over all frames having exactly this many feature points.
    grouped = defaultdict(list)
    for r in rows:
        grouped[int(r["num_features"])].append(r)
    x = np.asarray(sorted(grouped), dtype=float)
    reproj_mean = np.asarray([np.mean([r["p4pf_reproj_px"] for r in grouped[int(v)]]) for v in x])
    reproj_std = np.asarray([np.std([r["p4pf_reproj_px"] for r in grouped[int(v)]], ddof=1)
                             if len(grouped[int(v)]) > 1 else 0.0 for v in x])
    focal_mean = np.asarray([np.mean([r["p4pf_focal_px"] for r in grouped[int(v)]]) for v in x])
    focal_std = np.asarray([np.std([r["p4pf_focal_px"] for r in grouped[int(v)]], ddof=1)
                            if len(grouped[int(v)]) > 1 else 0.0 for v in x])
    counts = np.asarray([len(grouped[int(v)]) for v in x])

    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()
    ax1.errorbar(x, reproj_mean, yerr=reproj_std, fmt="o-", color="#333333",
                 ecolor="#777777", elinewidth=1, capsize=3, markersize=4,
                 label="mean reprojection error ± SD")
    ax1.set_xlabel("Number of feature points used by P4Pf (per frame)")
    ax1.set_ylabel("Reprojection error (px)", color="#333333")
    ax1.tick_params(axis="y", labelcolor="#333333")
    ax1.set_ylim(bottom=0)

    focal_yerr = np.vstack([np.minimum(focal_std, focal_mean), focal_std])
    ax2.errorbar(x, focal_mean, yerr=focal_yerr, fmt="s-", color="#0d6efd",
                 ecolor="#7aaeff", elinewidth=1, capsize=3, markersize=4,
                 label="mean P4Pf focal ± SD")
    ax2.axhline(true_focal, color="#e6484b", linestyle="--", linewidth=1.8,
                label=f"calibration ground truth = {true_focal:.0f}px")
    ax2.set_ylabel("Focal length (px)", color="#0d6efd")
    ax2.tick_params(axis="y", labelcolor="#0d6efd")

    focal_err = (focal_mean - true_focal) / true_focal * 100
    ax2.annotate(f"mean focal = {np.mean(focal_mean):.1f}px\n"
                 f"mean |error| = {np.mean(np.abs(focal_err)):.2f}%",
                 xy=(0.98, 0.06), xycoords="axes fraction", ha="right", va="bottom",
                 fontsize=9, color="#0d6efd",
                 bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85,
                       "edgecolor": "#cccccc"})

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper center",
               bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=8.5, frameon=False)
    ax1.set_title("P4Pf on floor5_2: feature count, reprojection error, and focal recovery\n"
                  "x = feature points | left y = reprojection error | right y = focal length",
                  fontsize=11)
    fig.tight_layout(rect=(0, 0.13, 1, 0.92))
    fig.savefig(PLOTS_DIR / out_name, dpi=180)
    plt.close(fig)
    print(f"floor5_2 P4Pf three-axis ({out_name}): n={len(rows)}, "
          f"exact-count groups={len(x)}, mean focal={np.mean(focal_mean):.1f}px, "
          f"mean |error|={np.mean(np.abs(focal_err)):.2f}%, "
          f"mean reproj={np.mean(reproj_mean):.2f}px")


def plot_labeled_all_floors_three_axes(stats_path: Path, out_name: str):
    """Aggregate labeled query images from every non-empty floor.

    Exact feature counts are the grouping key. If the same count occurs on
    several images/floors, focal and reprojection values are averaged across
    all of those observations; whiskers show the within-group standard
    deviation.
    """
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    rows = [r for r in data["records"]
            if r.get("p4pf_focal_px") is not None and np.isfinite(r.get("p4pf_reproj_px", np.inf))
            and int(r.get("num_features", 0)) > 0]
    grouped = defaultdict(list)
    for row in rows:
        grouped[int(row["num_features"])].append(row)
    x = np.asarray(sorted(grouped), dtype=float)
    reproj_mean = np.asarray([np.mean([r["p4pf_reproj_px"] for r in grouped[int(v)]]) for v in x])
    reproj_std = np.asarray([np.std([r["p4pf_reproj_px"] for r in grouped[int(v)]], ddof=1)
                             if len(grouped[int(v)]) > 1 else 0.0 for v in x])
    focal_mean = np.asarray([np.mean([r["p4pf_focal_px"] for r in grouped[int(v)]]) for v in x])
    focal_std = np.asarray([np.std([r["p4pf_focal_px"] for r in grouped[int(v)]], ddof=1)
                            if len(grouped[int(v)]) > 1 else 0.0 for v in x])
    true_values = sorted({float(r["true_focal_px"]) for r in rows})
    true_focal = float(np.mean(true_values))

    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()
    ax1.errorbar(x, reproj_mean, yerr=reproj_std, fmt="o-", color="#333333",
                 ecolor="#888888", elinewidth=1, capsize=3, markersize=4,
                 label="mean reprojection error ± SD")
    ax1.set_xlabel("Number of feature points used by P4Pf (exact count)")
    ax1.set_ylabel("Mean reprojection error (px)", color="#333333")
    ax1.tick_params(axis="y", labelcolor="#333333")
    ax1.set_ylim(bottom=0)
    ax1.set_xlim(left=max(0, float(min(x) - 5)))

    ax2.errorbar(x, focal_mean, yerr=focal_std, fmt="s-", color="#0d6efd",
                 ecolor="#7aaeff", elinewidth=1, capsize=3, markersize=4,
                 label="mean P4Pf focal ± SD")
    ax2.axhline(true_focal, color="#e6484b", linestyle="--", linewidth=1.8,
                label=f"calibration ground truth = {true_focal:.0f}px")
    # A few degenerate P4Pf solutions can be orders of magnitude away from
    # the calibration value. Keep those observations in the requested
    # arithmetic mean, but use symlog so the normal ~1400 px region remains
    # readable instead of being flattened at the bottom of a linear axis.
    ax2.set_yscale("symlog", linthresh=300)
    ax2.set_ylabel("Mean focal length (px, symlog)", color="#0d6efd")
    ax2.tick_params(axis="y", labelcolor="#0d6efd")
    ax2.set_ylim(bottom=0)

    focal_err = (focal_mean - true_focal) / true_focal * 100
    ax2.annotate(f"all labeled floors: {len(rows)} images / {len(x)} exact-count groups\n"
                 f"mean of group means = {np.mean(focal_mean):.1f}px\n"
                 f"mean |error| of groups = {np.mean(np.abs(focal_err)):.2f}%",
                 xy=(0.98, 0.06), xycoords="axes fraction", ha="right", va="bottom",
                 fontsize=9, color="#0d6efd",
                 bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85,
                       "edgecolor": "#cccccc"})
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper center",
               bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=8.5, frameon=False)
    floors = sorted({r["floor"] for r in rows})
    ax1.set_title("P4Pf across all labeled floors: feature count, reprojection error, and focal recovery\n"
                  f"floors = {', '.join(floors)} | same feature count is averaged across floors; focal axis = symlog",
                  fontsize=11)
    fig.tight_layout(rect=(0, 0.13, 1, 0.92))
    fig.savefig(PLOTS_DIR / out_name, dpi=180)
    plt.close(fig)
    print(f"all labeled floors P4Pf ({out_name}): n={len(rows)}, groups={len(x)}, "
          f"floors={floors}, mean focal={np.mean(focal_mean):.1f}px, "
          f"mean |error|={np.mean(np.abs(focal_err)):.2f}%, mean reproj={np.mean(reproj_mean):.2f}px")


def load_labeled_p4pf_rows(stats_path: Path):
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    return [r for r in data["records"]
            if r.get("p4pf_focal_px") is not None
            and np.isfinite(float(r.get("p4pf_focal_px")))
            and np.isfinite(float(r.get("p4pf_reproj_px", np.inf)))
            and int(r.get("num_features", 0)) > 0
            and int(r.get("p4pf_inliers", 0)) > 0]


def plot_p4pf_reprojection_vs_focal_error(stats_path: Path, out_name: str):
    """Test whether reprojection error is a reliable focal-quality signal."""
    rows = load_labeled_p4pf_rows(stats_path)
    fig, ax = plt.subplots(figsize=(8.5, 6))
    for floor in sorted({r["floor"] for r in rows}):
        group = [r for r in rows if r["floor"] == floor]
        reproj = np.asarray([float(r["p4pf_reproj_px"]) for r in group])
        focal_error = np.asarray([
            abs(float(r["p4pf_focal_px"]) - float(r["true_focal_px"]))
            / float(r["true_focal_px"]) * 100.0 for r in group
        ])
        ax.scatter(reproj, np.maximum(focal_error, 0.05), s=28,
                   alpha=0.72, color=LABELED_FLOOR_COLORS.get(floor, "#555555"),
                   edgecolors="white", linewidth=0.4, label=floor)

    ax.axvline(8.0, color="#777777", linestyle=":", linewidth=1.4,
               label="P4Pf reprojection gate = 8 px")
    ax.axhline(10.0, color="#e6484b", linestyle="--", linewidth=1.5,
               label="10% focal error")
    ax.set_yscale("log")
    ax.set_xlabel("P4Pf median reprojection error (px)")
    ax.set_ylabel("Absolute focal error (%) — log scale")
    ax.set_title("Reprojection error is not sufficient to validate focal length")
    ax.legend(fontsize=8.5, loc="upper left")
    ax.text(0.98, 0.04,
            "Low reprojection error can still produce a highly wrong focal estimate",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=9,
            color="#555555")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / out_name, dpi=180)
    plt.close(fig)


def plot_p4pf_focal_distribution_by_floor(stats_path: Path, out_name: str):
    """Show focal estimates relative to the 1400 px calibration reference."""
    rows = load_labeled_p4pf_rows(stats_path)
    floors = sorted({r["floor"] for r in rows})
    values = [[float(r["p4pf_focal_px"]) / float(r["true_focal_px"])
               for r in rows if r["floor"] == floor] for floor in floors]
    fig, ax = plt.subplots(figsize=(8.5, 6))
    bp = ax.boxplot(values, positions=np.arange(1, len(floors) + 1), widths=0.52,
                    patch_artist=True, showfliers=False, whis=(5, 95),
                    medianprops={"color": "#1b1a17", "linewidth": 1.8})
    rng = np.random.default_rng(7)
    for idx, (floor, vals) in enumerate(zip(floors, values), 1):
        jitter = rng.uniform(-0.16, 0.16, size=len(vals))
        ax.scatter(idx + jitter, vals, s=18, alpha=0.55,
                   color=LABELED_FLOOR_COLORS.get(floor, "#555555"),
                   edgecolors="white", linewidth=0.35)
        label_y = max(1.35, min(max(vals) * 1.18, 2.2))
        ax.text(idx, label_y, f"n={len(vals)}\nmed={np.median(vals):.3f}",
                ha="center", va="bottom", fontsize=8)
    for patch, floor in zip(bp["boxes"], floors):
        patch.set_facecolor(LABELED_FLOOR_COLORS.get(floor, "#777777"))
        patch.set_alpha(0.45)
    ax.axhline(1.0, color="#e6484b", linestyle="--", linewidth=1.6,
               label="calibration reference = 1400 px")
    ax.set_yscale("log")
    ax.set_xticks(np.arange(1, len(floors) + 1), floors)
    ax.set_xlabel("Floor")
    ax.set_ylabel("Estimated focal / calibration focal (log scale)")
    ax.set_title("P4Pf focal-length distribution by labeled floor")
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / out_name, dpi=180)
    plt.close(fig)


def plot_p4pf_feature_reliability(stats_path: Path, out_name: str):
    """Estimate how many matched features are needed for reliable focal recovery."""
    rows = load_labeled_p4pf_rows(stats_path)
    bins = [(0, 15), (15, 25), (25, 40), (40, 60), (60, 10_000)]
    labels = ["<15", "15–24", "25–39", "40–59", "60+"]
    centers = np.arange(len(bins))
    fig, ax = plt.subplots(figsize=(8.5, 6))
    for threshold, color in [(5, "#2a78d6"), (10, "#1baf7a"), (20, "#e6484b")]:
        rates = []
        counts = []
        for lo, hi in bins:
            group = [r for r in rows if lo <= int(r["num_features"]) < hi]
            errors = np.asarray([
                abs(float(r["p4pf_focal_px"]) - float(r["true_focal_px"]))
                / float(r["true_focal_px"]) * 100.0 for r in group
            ])
            rates.append(100.0 * np.mean(errors <= threshold) if len(errors) else np.nan)
            counts.append(len(group))
        ax.plot(centers, rates, "o-", linewidth=2, markersize=5,
                color=color, label=f"|focal error| ≤ {threshold}%")
    # n is shared by all threshold curves, so show it once below each bin.
    for x, (lo, hi) in zip(centers, bins):
        n = sum(lo <= int(r["num_features"]) < hi for r in rows)
        ax.annotate(f"n={n}", (x, 0), xycoords=("data", "axes fraction"),
                    xytext=(0, -24), textcoords="offset points", ha="center",
                    fontsize=8, color="#666666")
    ax.set_xticks(centers, labels)
    ax.set_ylim(0, 105)
    ax.set_xlabel("Number of matched feature points used by P4Pf")
    ax.set_ylabel("Reliable estimates (%)")
    ax.set_title("P4Pf reliability increases with feature support")
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(PLOTS_DIR / out_name, dpi=180)
    plt.close(fig)


def plot_p4pf_inlier_ratio_vs_focal_error(stats_path: Path, out_name: str):
    """Check whether P4Pf inlier ratio can reject bad focal solutions."""
    rows = load_labeled_p4pf_rows(stats_path)
    fig, ax = plt.subplots(figsize=(8.5, 6))
    for floor in sorted({r["floor"] for r in rows}):
        group = [r for r in rows if r["floor"] == floor]
        inlier_ratio = np.asarray([100.0 * float(r["p4pf_inliers"])
                                   / float(r["num_features"]) for r in group])
        focal_error = np.asarray([
            abs(float(r["p4pf_focal_px"]) - float(r["true_focal_px"]))
            / float(r["true_focal_px"]) * 100.0 for r in group
        ])
        sizes = 18 + 1.2 * np.sqrt([int(r["num_features"]) for r in group])
        ax.scatter(inlier_ratio, np.maximum(focal_error, 0.05), s=sizes,
                   alpha=0.72, color=LABELED_FLOOR_COLORS.get(floor, "#555555"),
                   edgecolors="white", linewidth=0.4, label=floor)
    ax.axhline(10.0, color="#e6484b", linestyle="--", linewidth=1.5,
               label="10% focal error")
    ax.set_yscale("log")
    ax.set_xlabel("P4Pf inlier ratio (%)")
    ax.set_ylabel("Absolute focal error (%) — log scale")
    ax.set_title("Inlier ratio alone does not guarantee a correct focal estimate")
    ax.legend(fontsize=8.5, loc="upper right")
    ax.text(0.02, 0.04, "marker size ∝ √(feature count)", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=9, color="#555555")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / out_name, dpi=180)
    plt.close(fig)


def main():
    records = load_natural_p4pf_records()
    print(f"{len(records)} real (non-synthetic) images with a valid P4Pf estimate")
    for group in GROUP_COLORS:
        n = sum(1 for r in records if r["group"] == group)
        print(f"  {group}: {n}")

    plot_parity(records)
    plot_reproj_hist(records)
    plot_p4pf_vs_features(records)
    plot_reliability_by_bucket(records)
    plot_selfcal_convergence(
        WEB_DIR / "iphone11_data.js", "selfcal_convergence_floor1_iphone11.png",
        "one iPhone11 walk on the floor1 map (built with a different phone)",
    )
    plot_selfcal_convergence(
        BACKEND_DIR / "evidence" / "floor5_2_web" / "floor5_2_data.js", "selfcal_convergence_floor5_2.png",
        "one floor5_2 walk on the floor5 map",
    )
    plot_focal_error_over_time(
        BACKEND_DIR / "evidence" / "floor5_2_web" / "floor5_2_data.js", "focal_error_over_time_floor5_2.png",
        true_focal=1400.0, walk_label="floor5_2 walk on the floor5 map (true focal = map's own 1400px)",
    )
    plot_focal_trajectory_effect(
        BACKEND_DIR / "evidence" / "floor5_2_web" / "floor5_2_data.js",
        "focal_trajectory_effect_floor5_2.png", true_focal=1400.0,
        floorplan_path=BACKEND_DIR / "app" / "data" / "map" / "floor5.jpg",
        walk_label="floor5_2 walk on the floor5 map",
    )
    plot_focal_trajectory_effect(
        WEB_DIR / "iphone11_data.js",
        "focal_trajectory_effect_floor1_iphone11.png", true_focal=1400.0,
        floorplan_path=BACKEND_DIR / "app" / "data" / "map" / "floor1.jpg",
        walk_label="iPhone11 walk on the floor1 map",
    )
    plot_floor5_2_p4pf_three_axes(
        OUT_DIR / "floor5_2_p4pf_full.jsonl", "p4pf_floor5_2_three_axes.png",
    )
    plot_labeled_all_floors_three_axes(
        OUT_DIR / "p4pf_labeled_all_floors.json", "p4pf_labeled_all_floors_three_axes.png",
    )
    plot_p4pf_reprojection_vs_focal_error(
        OUT_DIR / "p4pf_labeled_all_floors.json", "p4pf_reprojection_vs_focal_error.png",
    )
    plot_p4pf_focal_distribution_by_floor(
        OUT_DIR / "p4pf_labeled_all_floors.json", "p4pf_focal_distribution_by_floor.png",
    )
    plot_p4pf_feature_reliability(
        OUT_DIR / "p4pf_labeled_all_floors.json", "p4pf_feature_reliability.png",
    )
    plot_p4pf_inlier_ratio_vs_focal_error(
        OUT_DIR / "p4pf_labeled_all_floors.json", "p4pf_inlier_ratio_vs_focal_error.png",
    )
    print(f"wrote p4pf_focal_parity.png, p4pf_reproj_hist.png, p4pf_features_vs_error.png, "
          f"p4pf_reliability_by_features.png, selfcal_convergence_floor1_iphone11.png, "
          f"selfcal_convergence_floor5_2.png, focal_error_over_time_floor5_2.png, "
          f"focal_trajectory_effect_floor5_2.png, focal_trajectory_effect_floor1_iphone11.png "
          f"p4pf_floor5_2_three_axes.png, p4pf_reprojection_vs_focal_error.png, "
          f"p4pf_focal_distribution_by_floor.png, p4pf_feature_reliability.png, "
          f"and p4pf_inlier_ratio_vs_focal_error.png to {PLOTS_DIR}")


if __name__ == "__main__":
    main()
