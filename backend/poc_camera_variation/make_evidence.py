"""Evidence poster for REPORT.md: one figure per claim, then stitched.

Reads only the CSV/meta produced by run_camera_variation.py (no re-localizing).
Writes backend/evidence/images/0N_*.png and poster.png.

Colours follow the entity everywhere: map K = orange, self-cal = blue,
correct K (oracle / true focal) = aqua, baseline reference = ink.
"""

from __future__ import annotations

import cv2
import matplotlib
import numpy as np
from PIL import Image

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch  # noqa: E402

from analyze_camera_variation import corridor_segments, dist_to_segments, load, xy  # noqa: E402
from run_camera_variation import APP_DIR, EVIDENCE_DIR, apply_transform, transform_spec  # noqa: E402

EVID = EVIDENCE_DIR / "images"
MAP_K, SELF, ORACLE = "#eb6834", "#2a78d6", "#1baf7a"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
KCOL = {"map": MAP_K, "selfcal": SELF, "oracle": ORACLE}
KNAME = {"map": "K แผนที่ (ไม่ปรับ)", "selfcal": "self-cal (ระบบจริง)", "oracle": "K ที่ถูกต้อง"}

plt.rcParams.update({
    "font.family": ["Leelawadee UI", "Tahoma", "DejaVu Sans"],
    "font.size": 13, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 14,
    "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
})
W_IN = 16.0  # 1600 px at dpi 100


def header(fig, n: int, claim: str, evidence: str) -> None:
    fig.text(0.012, 0.985, f"{n}", fontsize=30, weight="bold", color=MUTED, va="top")
    fig.text(0.045, 0.982, claim, fontsize=21, weight="bold", color=INK, va="top")
    fig.text(0.045, 0.925, evidence, fontsize=13, color=INK2, va="top")


def errors(rows, key):
    ref = {int(r["sample"]): xy(r) for r in rows[("base", "map")]}
    out = []
    for r in rows.get(key, []):
        p, q = xy(r), ref.get(int(r["sample"]))
        if p and q:
            out.append(float(np.hypot(p[0] - q[0], p[1] - q[1])))
    return np.asarray(out)


def walking_frame(rows, key):
    """Error vectors rotated into (cross-track, along-track) of the baseline walk."""
    base = {int(r["sample"]): np.array(xy(r)) for r in rows[("base", "map")] if xy(r)}
    pts = []
    for r in rows.get(key, []):
        s, p = int(r["sample"]), xy(r)
        if not p or not all(k in base for k in (s, s - 2, s + 2)):
            continue
        d = base[s + 2] - base[s - 2]
        if np.linalg.norm(d) < 8:
            continue
        u = d / np.linalg.norm(d)
        e = np.array(p) - base[s]
        pts.append((float(u[0] * e[1] - u[1] * e[0]), float(e @ u)))
    return np.asarray(pts)


def sample_frame(meta, t: float) -> np.ndarray:
    cap = cv2.VideoCapture(meta["video"])
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * cap.get(cv2.CAP_PROP_FPS))))
    ok, frame = cap.read()
    cap.release()
    return frame


def rgb(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


# ── 1. pixels vs FoV ──────────────────────────────────────────────────────────
def fig_pixels_vs_fov(rows, meta):
    frame = sample_frame(meta, 160.0)
    fig = plt.figure(figsize=(W_IN, 7.2), dpi=100)
    header(fig, 1, "จำนวนพิกเซลไม่มีผล — มุมมอง (FoV) มีผลทั้งหมด",
           "ภาพ 960×540 เท่ากันทั้งคู่ แต่ภาพย่อ (มุมเท่าเดิม) ตำแหน่งตรงเกือบเป๊ะ ส่วนภาพครอป (มุมแคบลง) คลาด 27 px  ·  "
           "เพราะระบบ resize ทุกภาพเป็น 1920×1080 ก่อนหาตำแหน่งอยู่แล้ว")
    thumbs = [("base", "ต้นฉบับ 1920×1080"), ("px540", "ย่อทั้งภาพ 960×540"), ("crop50", "ครอป 50% = 960×540")]
    for i, (v, label) in enumerate(thumbs):
        ax = fig.add_axes([0.03 + i * 0.155, 0.40, 0.145, 0.40])
        img = apply_transform(frame, transform_spec(v, frame.shape[1], frame.shape[0], 160.0))
        ax.imshow(rgb(cv2.resize(img, (480, 270), interpolation=cv2.INTER_AREA)) if v != "px540"
                  else rgb(img[::2, ::2]))
        ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
        for s in ax.spines.values():
            s.set_visible(True); s.set_color(GRID)
        ax.set_title(label, fontsize=13, loc="center")
        med = np.median(errors(rows, (v, "map"))) if v != "base" else 0.0
        ax.text(0.5, -0.12, "อ้างอิง" if v == "base" else f"คลาด {med:.1f} px",
                transform=ax.transAxes, ha="center", va="top", fontsize=18, weight="bold",
                color=INK if v != "crop50" else MAP_K)
    fig.text(0.03, 0.14, "ภาพย่อ = เห็นเหมือนต้นฉบับทุกอย่าง แค่ละเอียดน้อยลง\n"
             "ภาพครอป = เห็นแคบลง แล้วถูกขยาย → เหมือนซูมเข้า", fontsize=13, color=INK2)

    ax = fig.add_axes([0.56, 0.12, 0.42, 0.70])
    items = [("px540", "ย่อ 960×540 (มุมเท่าเดิม)"), ("crop75", "ครอป 75%"), ("crop50", "ครอป 50%"),
             ("zoom2x", "ซูมอิน 2x (ครอป 50% แล้วขยายกลับ)"), ("zoomout75", "ซูมเอาต์ 0.75x")]
    med = [np.median(errors(rows, (v, "map"))) for v, _ in items]
    y = np.arange(len(items))[::-1]
    ax.barh(y, med, height=0.55, color=MAP_K)
    for yy, m in zip(y, med):
        ax.text(m + 0.6, yy, f"{m:.1f} px", va="center", fontsize=13, color=INK, weight="bold")
    ax.set_yticks(y, [lbl for _, lbl in items], fontsize=13, color=INK2)
    ax.set_xlim(0, 34); ax.grid(axis="y", visible=False)
    ax.set_xlabel("ระยะคลาดจากตำแหน่งของภาพต้นฉบับ · median px (แผนที่กว้าง 500 px) · ใช้ K แผนที่ไม่ปรับ")
    ax.set_title("ครอป 50% กับซูม 2x ได้ผลเท่ากัน (27.4 vs 27.6) — สำหรับระบบนี้คือสิ่งเดียวกัน")
    return fig


# ── 2. direction of the error ────────────────────────────────────────────────
def fig_direction(rows, meta):
    fig = plt.figure(figsize=(W_IN, 7.6), dpi=100)
    header(fig, 2, "focal ผิด → ตำแหน่งเลื่อนไปข้างหน้า/ข้างหลังตามทิศเดิน อย่างเป็นระบบ",
           "จุดแต่ละจุด = 1 เฟรม วัดความคลาดในกรอบของทิศที่ผู้ใช้เดิน (ขึ้น = ข้างหน้า)  ·  "
           "ซูมอินอยู่ข้างหน้า 99% ของเฟรม ซูมเอาต์อยู่ข้างหลัง 98%  ·  ไม่ใช่ noise แต่เป็น bias")
    cases = [(("zoomout75", "map"), "ซูมเอาต์ 0.75x · K แผนที่"), (("crop50", "map"), "ครอป 50% · K แผนที่"),
             (("crop50", "selfcal"), "ครอป 50% · self-cal")]
    for i, (key, title) in enumerate(cases):
        ax = fig.add_axes([0.04 + i * 0.165, 0.10, 0.14, 0.70])
        p = walking_frame(rows, key)
        ax.axhline(0, color="#c3c2b7", lw=1); ax.axvline(0, color="#c3c2b7", lw=1)
        ax.scatter(p[:, 0], p[:, 1], s=16, color=KCOL[key[1]], alpha=0.55, edgecolor="none")
        m = np.median(p[:, 1])
        ax.scatter([0], [m], s=120, color=KCOL[key[1]], edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.text(3, m, f"{m:+.1f} px\n{100 * np.mean(p[:, 1] > 0):.0f}% ข้างหน้า", va="center",
                fontsize=12, weight="bold", color=INK)
        ax.set_xlim(-30, 30); ax.set_ylim(-45, 70)
        ax.set_title(title, fontsize=13)
        ax.set_xlabel("เบี่ยงข้าง px")
        if i == 0:
            ax.set_ylabel("← ข้างหลัง    ตามทิศเดิน px    ข้างหน้า →")

    # Map evidence on the straightest corridor stretch: baseline dot -> variant dot.
    floor = rgb(cv2.imread(str(APP_DIR / "data" / "map" / "floor5.jpg")))
    base = {int(r["sample"]): xy(r) for r in rows[("base", "map")]}
    win = 14
    best, s0 = -1e9, 0
    for s in range(0, 320):
        seq = [base.get(k) for k in range(s, s + win)]
        if not all(seq):
            continue
        a = np.array(seq)
        score = abs(a[-1, 1] - a[0, 1]) - 3 * np.ptp(a[:, 0])
        if score > best:
            best, s0 = score, s
    fig.text(0.56, 0.86, f"บนแผนที่ช่วงเดินตรง (t = {s0}–{s0 + win} s):  ● ดำ = ตำแหน่งจากภาพต้นฉบับ   ● ส้ม = ที่ได้เมื่อใช้ K แผนที่",
             fontsize=12, color=INK2)
    for i, (v, title) in enumerate((("crop50", "ครอป 50%: ไปข้างหน้า"), ("zoomout75", "ซูมเอาต์: ไปข้างหลัง"))):
        ax = fig.add_axes([0.56 + i * 0.22, 0.04, 0.20, 0.78])
        ax.imshow(floor, alpha=0.4)
        var = {int(r["sample"]): xy(r) for r in rows[(v, "map")]}
        ss = [k for k in range(s0, s0 + win) if var.get(k)]
        b = np.array([base[k] for k in ss]); c = np.array([var[k] for k in ss])
        for k in ss[::2]:
            ax.add_patch(FancyArrowPatch(base[k], var[k], arrowstyle="-|>", mutation_scale=12,
                                         color=MAP_K, lw=1.6, shrinkA=3, shrinkB=3))
        ax.scatter(b[::2, 0], b[::2, 1], s=34, color=INK, zorder=3)
        ax.scatter(c[::2, 0], c[::2, 1], s=34, color=MAP_K, edgecolor=SURFACE, linewidth=1.5, zorder=4)
        allp = np.r_[b, c]
        cx, cy = allp[:, 0].mean(), allp[:, 1].mean()
        half = max(np.ptp(allp[:, 1]), np.ptp(allp[:, 0])) / 2 + 18
        ax.set_xlim(cx - half * 0.55, cx + half * 0.55); ax.set_ylim(cy + half, cy - half)
        up = (b[-1] - b[0])[1] < 0  # map y grows downwards
        ax.annotate("", (cx + half * 0.42, cy + (-0.6 if up else 0.6) * half),
                    (cx + half * 0.42, cy + (0.6 if up else -0.6) * half),
                    arrowprops=dict(arrowstyle="-|>", color=INK2, lw=2, mutation_scale=18))
        ax.text(cx + half * 0.40, cy, "ทิศเดิน", rotation=90, ha="right", va="center", fontsize=12,
                color=INK2, bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1))
        ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
        ax.set_title(title, fontsize=13)
    return fig


# ── 3. correct K fixes it; self-cal ≈ correct K ───────────────────────────────
def fig_fix(rows, meta):
    fig = plt.figure(figsize=(W_IN, 7.4), dpi=100)
    header(fig, 3, "ปัญหาคือ focal ผิด ไม่ใช่ภาพเสียข้อมูล — บอก K ถูก ตำแหน่งกลับมาตรง",
           "ภาพเดิมทุกพิกเซล เปลี่ยนแค่ค่า focal ที่บอกระบบ  ·  self-calibration ที่มีใน production ไปถึงค่าเดียวกันเองในกรณีซูมคงที่  ·  "
           "ยกเว้นภาพ 4:3 (fx ≠ fy) และซูมที่เปลี่ยนตลอด")
    items = [("crop75", "ครอป 75%"), ("crop50", "ครอป 50%"), ("zoom2x", "ซูมอิน 2x"),
             ("zoomout75", "ซูมเอาต์ 0.75x"), ("crop43", "ครอป 4:3 (ถูกยืดเป็น 16:9)"),
             ("zoomdyn", "ซูมเปลี่ยนตลอด 1x↔2x")]
    ax = fig.add_axes([0.20, 0.12, 0.50, 0.70])
    y = np.arange(len(items))[::-1] * 1.0
    offs = {"map": 0.22, "selfcal": 0.0, "oracle": -0.22}
    for m in ("map", "selfcal", "oracle"):
        med, p90 = [], []
        for v, _ in items:
            e = errors(rows, (v, m))
            med.append(np.median(e)); p90.append(np.percentile(e, 90))
        yy = y + offs[m]
        ax.hlines(yy, med, p90, color=KCOL[m], lw=2, alpha=0.35)
        ax.scatter(med, yy, s=90, color=KCOL[m], edgecolor=SURFACE, linewidth=2, zorder=3, label=KNAME[m])
        for x, yv in zip(med, yy):
            ax.text(x + (0.9 if x > 1 else 1.4), yv, f"{x:.1f}", va="center", fontsize=11,
                    color=INK2 if m != "map" else INK, weight="bold" if m == "map" else "normal")
    ax.set_yticks(y, [lbl for _, lbl in items], fontsize=13, color=INK2)
    ax.grid(axis="y", visible=False); ax.set_xlim(0, 52)
    ax.set_xlabel("ระยะคลาดจากต้นฉบับ px · จุด = median, เส้นจาง = ถึง p90")
    ax.legend(loc="lower right", frameon=False, fontsize=12)

    ax2 = fig.add_axes([0.75, 0.12, 0.23, 0.70])
    items2 = [("base", "ต้นฉบับ"), ("crop50", "ครอป 50%"), ("zoom2x", "ซูม 2x")]
    width = 0.26
    for j, m in enumerate(("map", "selfcal", "oracle")):
        n = [sum(r["success"] == "1" for r in rows.get((v, m), rows[(v, "map")])) for v, _ in items2]
        fails = [332 - k for k in n]
        xs = np.arange(len(items2)) + (j - 1) * (width + 0.02)
        ax2.bar(xs, fails, width=width, color=KCOL[m])
        for x, f in zip(xs, fails):
            ax2.text(x, f + 1.2, str(f), ha="center", fontsize=11, color=INK)
    ax2.set_xticks(np.arange(len(items2)), [lbl for _, lbl in items2], color=INK2)
    ax2.grid(axis="x", visible=False)
    ax2.set_title("เฟรมที่หาตำแหน่งไม่ได้ (จาก 332)", fontsize=13)
    return fig


# ── 4. self-cal weaknesses ───────────────────────────────────────────────────
def lag_seconds(rs, map_f):
    used = np.array([float(r["fx_used"]) for r in rs])
    true = np.array([float(r["zoom"]) for r in rs]) * map_f
    best = min(range(0, 40), key=lambda k: np.mean(np.abs(used[20 + k:] - true[20:len(true) - k])))
    return best


def fig_selfcal(rows, meta):
    map_f = meta["map_K"][0][0]
    fig = plt.figure(figsize=(W_IN, 7.0), dpi=100)
    header(fig, 4, "self-calibration แก้ได้ แต่มี 3 จุดอ่อน",
           "เส้นน้ำเงิน = focal ที่ระบบใช้จริงแต่ละวินาที · เส้นเขียว = ค่าที่ถูกต้อง  ·  "
           "(1) ค่าแรกเป็นค่าดิบจากเฟรมเดียว ผิดได้มาก  (2) ภาพ 4:3 ไม่ converge  (3) ซูมเปลี่ยน ตามช้า")
    panels = [("crop50", "ครอป 50% — ค่าแรกผิดแล้วค่อย converge", (0, 60)),
              ("crop43", "ครอป 4:3 — fx≠fy ประมาณได้ค่าเดียว ไม่ converge", (0, 332)),
              ("zoomdyn", "ซูม 1x↔2x ทุก 120 s — ตามช้า", (0, 332))]
    for i, (v, title, xlim) in enumerate(panels):
        ax = fig.add_axes([0.05 + i * 0.32, 0.12, 0.28, 0.66])
        rs = rows[(v, "selfcal")]
        t = np.array([float(r["time_s"]) for r in rs])
        used = np.array([float(r["fx_used"]) for r in rs])
        if v == "crop43":
            ax.axhline(map_f * 1920 / 1440, color=ORACLE, lw=2, label="fx ที่ถูก 1867")
            ax.axhline(map_f, color=ORACLE, lw=2, alpha=0.5, label="fy ที่ถูก 1400")
            ax.text(xlim[1], map_f * 1920 / 1440 + 40, "fx ถูก 1867", ha="right", color=INK2, fontsize=11)
            ax.text(xlim[1], map_f - 110, "fy ถูก 1400", ha="right", color=INK2, fontsize=11)
        else:
            true = np.array([float(r["zoom"]) for r in rs]) * map_f
            ax.plot(t, true, color=ORACLE, lw=2.5)
        ax.plot(t, used, color=SELF, lw=2)
        ax.axhline(map_f, color="#c3c2b7", lw=1)
        ax.set_xlim(*xlim)
        ax.set_title(title, fontsize=13)
        ax.set_xlabel("เวลา (s)")
        if i == 0:
            ax.set_ylabel("focal px")
            k = int(np.argmax(used[:10]))
            ax.set_ylim(1300, used[k] + 250)
            ax.annotate(f"ค่าแรก {used[k]:.0f} (ถูก 2800)\nใช้ค่าผิดนี้ ~15 s กว่าจะเข้าที่", (t[k], used[k]),
                        (t[k] + 14, used[k] + 60), fontsize=11, color=INK,
                        arrowprops=dict(arrowstyle="-", color=MUTED))
            ax.text(58, 2800 - 150, "ถูก 2800", ha="right", color=INK2, fontsize=11)
            ax.text(58, map_f + 40, "focal แผนที่ 1400", ha="right", color=MUTED, fontsize=10)
        if i == 1:
            k = int(np.argmax(used[:30]))
            ax.annotate(f"ค่าแรก {used[k]:.0f}", (t[k], used[k]), (t[k] + 25, used[k] - 150),
                        fontsize=11, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED))
        if i == 2:
            lag = lag_seconds(rs, map_f)
            ax.set_title(f"ซูม 1x↔2x ทุก 120 s — ระบบตามช้ากว่าจริง ≈ {lag} s", fontsize=13)
            ax.set_ylim(1150, 2900)
            ax.plot([], [], color=ORACLE, lw=2.5, label="ค่าที่ถูก")
            ax.plot([], [], color=SELF, lw=2, label="ระบบใช้")
            ax.legend(loc="lower center", bbox_to_anchor=(0.5, 0.02), ncol=2, frameon=False, fontsize=11)
    return fig


# ── 5. a different camera ────────────────────────────────────────────────────
def fig_floor1(rows1, meta1):
    fig = plt.figure(figsize=(W_IN, 8.2), dpi=100)
    f_est = meta1["focal_est"]
    hfov = lambda f: np.degrees(2 * np.arctan(964.7 / f))  # noqa: E731
    header(fig, 5, "กล้องคนละตัว (iPhone มุมกว้าง ชั้น 1) — ต้องรู้ focal ของกล้องนั้น",
           f"self-cal ประมาณ focal ได้ {f_est:.0f} px (มุม {hfov(f_est):.0f}°) ขณะที่กล้องแผนที่ 1400 px (มุม {hfov(1400):.0f}°)  ·  "
           "ใช้ค่าของแผนที่ ตำแหน่งกระโดดและหลุดทางเดิน  ·  ไม่มี ground truth ของคลิปนี้ จึงวัดจากการกระโดดและระยะห่างทางเดิน")
    floor = rgb(cv2.imread(str(APP_DIR / "data" / "map" / "floor1.jpg")))
    seg = corridor_segments("floor1")
    panels = [(("wide", "map"), "มุมกว้าง + K แผนที่ (1400)", MAP_K),
              (("wide", "selfcal"), f"มุมกว้าง + self-cal ({f_est:.0f})", SELF)]
    for i, (key, title, col) in enumerate(panels):
        ax = fig.add_axes([0.02 + i * 0.30, 0.07, 0.28, 0.77])
        ax.imshow(floor, alpha=0.45)
        pts = np.array([xy(r) for r in rows1[key] if xy(r)])
        ax.plot(pts[:, 0], pts[:, 1], color=col, lw=1.4, alpha=0.8)
        ax.scatter(pts[:, 0], pts[:, 1], s=9, color=col, zorder=3)
        jumps = [(a, b) for a, b in zip(pts, pts[1:]) if np.hypot(*(b - a)) > 40]
        for a, b in jumps:
            ax.plot([a[0], b[0]], [a[1], b[1]], color=INK, lw=2.4)
        off = [p for p in pts if dist_to_segments(p, seg) > 15]
        if off:
            off = np.array(off)
            ax.scatter(off[:, 0], off[:, 1], s=60, facecolor="none", edgecolor=INK, linewidth=1.5, zorder=4)
        ax.set_xlim(170, 470); ax.set_ylim(470, 120)
        ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
        ax.set_title(title, fontsize=14)
    fig.text(0.02, 0.02, "เส้นดำหนา = กระโดด >40 px ในวินาทีเดียว · วงดำ = จุดห่างทางเดิน >15 px",
             fontsize=11, color=INK2)

    # stat tiles
    stats = []
    for key in [("wide", "map"), ("wide", "selfcal"), ("wide", "estK"), ("wide_fov", "map")]:
        pts = np.array([xy(r) for r in rows1[key] if xy(r)])
        steps = np.hypot(*np.diff(pts, axis=0).T)
        corr = np.array([dist_to_segments(p, seg) for p in pts])
        stats.append((int((steps > 40).sum()), 100 * np.mean(corr > 15), len(pts)))
    names = ["K แผนที่", "self-cal", f"K คงที่ {f_est:.0f}", "ครอป 66% + K แผนที่"]
    cols = [MAP_K, SELF, ORACLE, INK2]
    ax = fig.add_axes([0.63, 0.06, 0.36, 0.78]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.0, 0.98, "ทั้ง 3 วิธีที่แก้ focal ให้ผลเหมือนกัน", fontsize=14, weight="bold", color=INK, va="top")
    heads = ["กระโดด >40px", "หลุดทางเดิน", "หาได้ /308"]
    for j, h in enumerate(heads):
        ax.text(0.45 + j * 0.2, 0.88, h, fontsize=11, color=MUTED, ha="center")
    for i, (name, col, (j_, o_, n_)) in enumerate(zip(names, cols, stats)):
        yy = 0.78 - i * 0.18
        ax.add_patch(plt.Rectangle((0, yy - 0.06), 0.02, 0.12, color=col))
        ax.text(0.04, yy, name, fontsize=13, color=INK, va="center")
        for j, val in enumerate((f"{j_}", f"{o_:.0f}%", f"{n_}")):
            ax.text(0.45 + j * 0.2, yy, val, fontsize=22 if j < 2 else 15, weight="bold",
                    color=INK if (i == 0 and j < 2) else INK2, ha="center", va="center")
    return fig


def main() -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    rows, meta = load("floor5")
    rows1, meta1 = load("floor1")
    figs = [("01_pixels_vs_fov", fig_pixels_vs_fov(rows, meta)), ("02_error_direction", fig_direction(rows, meta)),
            ("03_correct_k_fixes", fig_fix(rows, meta)), ("04_selfcal_weaknesses", fig_selfcal(rows, meta)),
            ("05_different_camera", fig_floor1(rows1, meta1))]
    paths = []
    for name, fig in figs:
        path = EVID / f"{name}.png"
        fig.savefig(path, dpi=100, facecolor=SURFACE)
        plt.close(fig)
        paths.append(path)
        print("wrote", path)
    images = [Image.open(p).convert("RGB") for p in paths]
    gap = 24
    poster = Image.new("RGB", (max(i.width for i in images), sum(i.height for i in images) + gap * (len(images) - 1)),
                       (225, 224, 217))
    y = 0
    for im in images:
        poster.paste(im, (0, y))
        y += im.height + gap
    poster.save(EVID / "poster.png", optimize=True)
    print("wrote", EVID / "poster.png", poster.size)


if __name__ == "__main__":
    main()
