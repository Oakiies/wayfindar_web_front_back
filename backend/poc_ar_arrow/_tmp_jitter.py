import csv
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent / 'out' / 'walk_m21_graphfix.csv'
rows = list(csv.DictReader(open(CSV_PATH, encoding='utf-8')))
pts = [(float(r['t_sec']), float(r['x']), float(r['y']), r['num_inliers'])
       for r in rows if r['x']]

# Lateral jitter proxy: second difference of position (how much the path
# zig-zags frame to frame), same idea as the PoC's "probe jitter" metric.
print(f"{'t':>7} {'x':>7} {'y':>7} {'inl':>4} {'jerk_px':>8}")
for i in range(1, len(pts) - 1):
    t0, x0, y0, _ = pts[i - 1]
    t1, x1, y1, inl = pts[i]
    t2, x2, y2, _ = pts[i + 1]
    jerk = ((x2 - 2 * x1 + x0) ** 2 + (y2 - 2 * y1 + y0) ** 2) ** 0.5
    flag = '  <<<' if jerk > 4.0 else ''
    print(f"{t1:7.2f} {x1:7.1f} {y1:7.1f} {inl:>4} {jerk:8.2f}{flag}")
