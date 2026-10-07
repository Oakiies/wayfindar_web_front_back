"""Summaries and plots for run_camera_variation.py results.

floor5: error of every (variant, K-mode) against the unmodified baseline on the
        same sampled frame (baseline with map K; distances in floor-plan px,
        floor5.jpg is 500x500 and has no verified metre scale).
floor1: no reference trajectory exists for this clip, so report success rate,
        position jumps between consecutive fixes, and distance to the
        walkable corridor graph as plausibility checks.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from run_camera_variation import APP_DIR, OUT_DIR  # noqa: E402

plt.rcParams["font.family"] = ["Leelawadee UI", "Tahoma", "DejaVu Sans"]


def load(exp: str):
    out = OUT_DIR / exp
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    rows = defaultdict(list)
    with (out / "results.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows[(r["variant"], r["kmode"])].append(r)
    return rows, meta


def xy(r):
    return (float(r["x_px"]), float(r["y_px"])) if r["success"] == "1" else None


def corridor_segments(floor_id: str) -> np.ndarray:
    graph = json.loads((APP_DIR / "data" / "json_map" / f"{floor_id}.json").read_text(encoding="utf-8-sig"))["graph"]
    pos = {k: (v["metadata"]["position"]["x"], v["metadata"]["position"]["y"]) for k, v in graph["nodes"].items()}
    return np.array([[*pos[e["source"]], *pos[e["target"]]] for e in graph["edges"]
                     if e["source"] in pos and e["target"] in pos], dtype=np.float64)


def dist_to_segments(p, seg: np.ndarray) -> float:
    a, b = seg[:, :2], seg[:, 2:]
    ab = b - a
    tt = np.clip(np.einsum("ij,ij->i", np.asarray(p) - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-9), 0, 1)
    proj = a + ab * tt[:, None]
    return float(np.min(np.hypot(*(np.asarray(p) - proj).T)))


def fmt(v, spec=".1f"):
    return "-" if v is None else format(v, spec)


def floor5_summary(rows, meta) -> tuple[list[dict], str]:
    ref = {int(r["sample"]): xy(r) for r in rows[("base", "map")]}
    order = ["base", "px540", "crop75", "crop50", "crop43", "zoom2x", "zoomout75", "zoomdyn"]
    table = []
    for v in order:
        for m in ("map", "selfcal", "oracle"):
            rs = rows.get((v, m))
            if not rs:
                continue
            errs = []
            for r in rs:
                p, q = xy(r), ref.get(int(r["sample"]))
                if p and q:
                    errs.append(float(np.hypot(p[0] - q[0], p[1] - q[1])))
            errs = np.asarray(errs)
            inl = [int(r["num_inliers"]) for r in rs if r["success"] == "1"]
            final_f = [float(r["fx_used"]) for r in rs][-1]
            table.append({
                "variant": v, "kmode": m, "n": len(rs),
                "success": sum(r["success"] == "1" for r in rs),
                "err_median": float(np.median(errs)) if len(errs) else None,
                "err_p90": float(np.percentile(errs, 90)) if len(errs) else None,
                "err_gt20_pct": float(100 * np.mean(errs > 20)) if len(errs) else None,
                "inliers_median": float(np.median(inl)) if inl else None,
                "f_final": final_f,
            })
    lines = ["| ตัวแปร | K mode | หาได้ | คลาด median px | p90 px | คลาด >20px | inliers median | f ที่ใช้ตอนจบ |",
             "|---|---|---|---|---|---|---|---|"]
    for t in table:
        lines.append(f"| {t['variant']} | {t['kmode']} | {t['success']}/{t['n']} | {fmt(t['err_median'])} | "
                     f"{fmt(t['err_p90'])} | {fmt(t['err_gt20_pct'], '.0f')}% | {fmt(t['inliers_median'], '.0f')} | "
                     f"{t['f_final']:.0f} |")
    return table, "\n".join(lines)


def along_track(rows) -> str:
    """Split the error into along/cross the baseline walking direction."""
    base = {int(r["sample"]): np.array(xy(r)) for r in rows[("base", "map")] if xy(r)}
    lines = ["| ตัวแปร | K mode | ตามทิศเดิน median px | เบี่ยงข้าง median px | เฟรมที่อยู่ข้างหน้า |", "|---|---|---|---|---|"]
    for key in [("crop75", "map"), ("crop50", "map"), ("zoom2x", "map"), ("zoomout75", "map"),
                ("crop43", "map"), ("crop50", "selfcal")]:
        along, cross = [], []
        for r in rows.get(key, []):
            s, p = int(r["sample"]), xy(r)
            if not p or not all(k in base for k in (s, s - 2, s + 2)):
                continue
            d = base[s + 2] - base[s - 2]
            if np.linalg.norm(d) < 8:  # needs a clear walking direction
                continue
            u = d / np.linalg.norm(d)
            e = np.array(p) - base[s]
            along.append(float(e @ u))
            cross.append(abs(float(u[0] * e[1] - u[1] * e[0])))
        if along:
            lines.append(f"| {key[0]} | {key[1]} | {np.median(along):+.1f} | {np.median(cross):.1f} | "
                         f"{100 * np.mean(np.asarray(along) > 0):.0f}% |")
    return "\n".join(lines)


def floor1_summary(rows, meta) -> tuple[list[dict], str]:
    seg = corridor_segments("floor1")
    table = []
    for (v, m) in [("wide", "map"), ("wide", "selfcal"), ("wide", "estK"), ("wide_fov", "map")]:
        rs = rows.get((v, m))
        if not rs:
            continue
        pts = [xy(r) for r in rs if xy(r)]
        steps = [float(np.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(pts, pts[1:])]
        corr = [dist_to_segments(p, seg) for p in pts]
        inl = [int(r["num_inliers"]) for r in rs if r["success"] == "1"]
        table.append({
            "variant": v, "kmode": m, "n": len(rs), "success": len(pts),
            "jumps_gt40": int(sum(s > 40 for s in steps)),
            "step_median": float(np.median(steps)) if steps else None,
            "corridor_median": float(np.median(corr)) if corr else None,
            "corridor_gt15_pct": float(100 * np.mean(np.asarray(corr) > 15)) if corr else None,
            "inliers_median": float(np.median(inl)) if inl else None,
            "f_final": float(rs[-1]["fx_used"]),
        })
    lines = ["| วิธี | หาได้ | กระโดด >40px | ก้าวต่อวิ median px | ห่างทางเดิน median px | ห่างทางเดิน >15px | inliers median | f ที่ใช้ตอนจบ |",
             "|---|---|---|---|---|---|---|---|"]
    for t in table:
        lines.append(f"| {t['variant']} + {t['kmode']} | {t['success']}/{t['n']} | {t['jumps_gt40']} | "
                     f"{fmt(t['step_median'])} | {fmt(t['corridor_median'])} | {fmt(t['corridor_gt15_pct'], '.0f')}% | "
                     f"{fmt(t['inliers_median'], '.0f')} | {t['f_final']:.0f} |")
    return table, "\n".join(lines)


def plot_focal(rows, exp, out: Path, map_f: float, focal_est: float | None = None):
    variants = [v for (v, m) in rows if m == "selfcal"]
    fig, axes = plt.subplots(len(variants), 1, figsize=(12, 2.1 * len(variants)), sharex=True, dpi=110)
    axes = np.atleast_1d(axes)
    for ax, v in zip(axes, variants):
        rs = rows[(v, "selfcal")]
        t = np.array([float(r["time_s"]) for r in rs])
        used = np.array([float(r["fx_used"]) for r in rs])
        ax.plot(t, used, color="#d62728", lw=1.8, label="focal ที่ระบบใช้ (self-cal)")
        if exp == "floor5":
            true = np.array([float(r["zoom"]) for r in rs]) * map_f
            if v == "crop43":
                true = np.full_like(t, map_f * 1920 / 1440)
                ax.axhline(map_f, color="#1f77b4", ls=":", lw=1.2, label="fy ที่ถูกต้อง")
            ax.plot(t, true, color="#2ca02c", lw=1.4, ls="--", label="focal ที่ถูกต้อง (fx)")
        elif focal_est:
            ax.axhline(focal_est, color="#2ca02c", ls="--", lw=1.4, label="median ของ estimates")
        ax.axhline(map_f, color="#888", lw=0.8)
        ok = np.array([r["success"] == "1" for r in rs])
        ax.scatter(t[~ok], used[~ok], s=8, color="black", zorder=3, label="หาตำแหน่งไม่ได้")
        ax.set_ylabel(v)
        ax.grid(alpha=0.25)
    axes[0].legend(loc="upper right", fontsize=8, ncol=4)
    axes[-1].set_xlabel("เวลาในวิดีโอ (s)")
    fig.suptitle(f"{exp}: focal ที่ self-calibration ใช้ในแต่ละช่วงเวลา (เส้นเทา = focal ของแผนที่ {map_f:.0f}px)")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def plot_error_time(rows, out: Path):
    ref = {int(r["sample"]): xy(r) for r in rows[("base", "map")]}
    variants = ["px540", "crop75", "crop50", "crop43", "zoom2x", "zoomout75", "zoomdyn"]
    variants = [v for v in variants if (v, "map") in rows]
    fig, axes = plt.subplots(len(variants), 1, figsize=(12, 1.9 * len(variants)), sharex=True, dpi=110)
    axes = np.atleast_1d(axes)
    colors = {"map": "#d62728", "selfcal": "#ff7f0e", "oracle": "#2ca02c"}
    for ax, v in zip(axes, variants):
        for m in ("map", "selfcal", "oracle"):
            rs = rows.get((v, m))
            if not rs:
                continue
            t, e = [], []
            for r in rs:
                p, q = xy(r), ref.get(int(r["sample"]))
                if p and q:
                    t.append(float(r["time_s"]))
                    e.append(np.hypot(p[0] - q[0], p[1] - q[1]))
            ax.plot(t, np.minimum(e, 120), lw=1.0, color=colors[m], label=m, alpha=0.85)
        ax.set_ylabel(v)
        ax.set_ylim(0, 120)
        ax.grid(alpha=0.25)
    handles = [plt.Line2D([], [], color=c, label=lbl) for lbl, c in
               (("K แผนที่ (map)", colors["map"]), ("self-cal (ระบบจริง)", colors["selfcal"]),
                ("K ถูกต้อง (oracle)", colors["oracle"]))]
    axes[0].legend(handles=handles, loc="upper right", ncol=3, fontsize=8)
    axes[-1].set_xlabel("เวลาในวิดีโอ (s)")
    fig.suptitle("floor5:ระยะคลาดจากตำแหน่งของภาพต้นฉบับ (px บนแผนที่ 500px, ตัดที่ 120)")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def plot_trajectories(rows, exp, pairs, out: Path, title: str):
    floor = cv2.cvtColor(cv2.imread(str(APP_DIR / "data" / "map" / f"{exp}.jpg")), cv2.COLOR_BGR2RGB)
    n = len(pairs)
    fig, axes = plt.subplots(1, n, figsize=(4.2 * n, 4.6), dpi=110)
    for ax, (label, keys) in zip(np.atleast_1d(axes), pairs):
        ax.imshow(floor, alpha=0.55)
        for key, color in keys:
            rs = rows.get(key)
            if not rs:
                continue
            p = np.array([xy(r) for r in rs if xy(r)])
            if len(p):
                ax.plot(p[:, 0], p[:, 1], "-", color=color, lw=1.1, alpha=0.8)
                ax.scatter(p[:, 0], p[:, 1], s=5, color=color)
        ax.set_title(label, fontsize=10)
        ax.axis("off")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    report = {}
    if (OUT_DIR / "floor5" / "results.csv").exists():
        rows, meta = load("floor5")
        table, md = floor5_summary(rows, meta)
        report["floor5"] = table
        md += "\n\n" + along_track(rows)
        (OUT_DIR / "floor5" / "summary.md").write_text(md + "\n", encoding="utf-8")
        print(md)
        plot_focal(rows, "floor5", OUT_DIR / "floor5_focal_selfcal.png", meta["map_K"][0][0])
        plot_error_time(rows, OUT_DIR / "floor5_error_over_time.png")
        base = (("base", "map"), "#222222")
        plot_trajectories(rows, "floor5", [
            (f"{v} · {m}", [base, ((v, m), c)])
            for v in ("crop50", "crop43", "zoomout75")
            for m, c in (("map", "#d62728"), ("selfcal", "#ff7f0e"), ("oracle", "#2ca02c"))
        ][:9], OUT_DIR / "floor5_trajectories.png", "เส้นดำ = ภาพต้นฉบับ · แดง = K แผนที่ · ส้ม = self-cal · เขียว = K ถูกต้อง")
    if (OUT_DIR / "floor1" / "results.csv").exists():
        rows, meta = load("floor1")
        table, md = floor1_summary(rows, meta)
        report["floor1"] = table
        (OUT_DIR / "floor1" / "summary.md").write_text(md + "\n", encoding="utf-8")
        print(md)
        plot_focal(rows, "floor1", OUT_DIR / "floor1_focal_selfcal.png", meta["map_K"][0][0], meta.get("focal_est"))
        plot_trajectories(rows, "floor1", [
            ("K แผนที่", [(("wide", "map"), "#d62728")]),
            ("self-calibration", [(("wide", "selfcal"), "#ff7f0e")]),
            ("K ที่ประมาณได้", [(("wide", "estK"), "#2ca02c")]),
            ("ครอปให้มุมเท่าแผนที่", [(("wide_fov", "map"), "#1f77b4")]),
        ], OUT_DIR / "floor1_trajectories.png", "floor1 กล้องมุมกว้าง: ตำแหน่งที่ได้จากแต่ละวิธี")
    (OUT_DIR / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
