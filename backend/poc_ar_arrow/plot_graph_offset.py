"""Visualize the graph-vs-real-walk mismatch found near M21 on floor1:
overlay the route graph (nodes/edges) on the floor plan image, highlight the
offending diagonal edge, and plot the actual walked trajectory (from
diagnose_new_walk.py's CSV) so the ~2.4m gap is visible directly on the map
instead of only as numbers.

Run from backend/:
    .venv/Scripts/python.exe poc_ar_arrow/plot_graph_offset.py
"""
import csv
import json
from pathlib import Path

import cv2
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BACKEND = Path(__file__).resolve().parent.parent
GRAPH_JSON = BACKEND / 'app' / 'data' / 'json_map' / 'floor1.json'
MAP_IMG = BACKEND / 'app' / 'data' / 'map' / 'floor1.jpg'
WALK_CSV = Path(__file__).resolve().parent / 'out' / 'walk_m21_final_interval0.5.csv'
OUT_PNG = Path(__file__).resolve().parent / 'out' / 'graph_offset_diagnosis.png'

BAD_EDGE = ('Intersection 1', 'M23_B')

data = json.loads(GRAPH_JSON.read_text(encoding='utf-8-sig'))
nodes = data['graph']['nodes']
edges = data['graph']['edges']

img = cv2.cvtColor(cv2.imread(str(MAP_IMG)), cv2.COLOR_BGR2RGB)

# Region of interest around the M21 approach.
x0, x1 = 260, 400
y0, y1 = 170, 460

rows = list(csv.DictReader(open(WALK_CSV, encoding='utf-8')))
walk_xy = [(float(r['x']), float(r['y'])) for r in rows if r['x']]

fig, axes = plt.subplots(1, 2, figsize=(16, 9))

for ax, title in zip(axes, ['Full zone around M21', 'Zoomed to the bad edge']):
    ax.imshow(img)
    for e in edges:
        s, t = nodes.get(e['source']), nodes.get(e['target'])
        if not s or not t:
            continue
        sp, tp = s['metadata']['position'], t['metadata']['position']
        if not (x0 - 40 <= sp['x'] <= x1 + 40 and y0 - 40 <= sp['y'] <= y1 + 40):
            continue
        is_bad = {e.get('source_label'), e.get('target_label')} == set(BAD_EDGE)
        ax.plot([sp['x'], tp['x']], [sp['y'], tp['y']],
                color='#ff3b30' if is_bad else '#0d6efd',
                linewidth=4 if is_bad else 2, zorder=3, alpha=0.9)
    for nid, nd in nodes.items():
        pos = nd['metadata']['position']
        if not (x0 - 40 <= pos['x'] <= x1 + 40 and y0 - 40 <= pos['y'] <= y1 + 40):
            continue
        ax.scatter([pos['x']], [pos['y']], s=28, color='#111', zorder=4)
        ax.annotate(nd.get('label', nid), (pos['x'], pos['y']),
                    textcoords='offset points', xytext=(6, 6), fontsize=8, color='#111')

    wx = [p[0] for p in walk_xy]
    wy = [p[1] for p in walk_xy]
    ax.plot(wx, wy, color='#22c55e', linewidth=3, alpha=0.85, zorder=5,
            label='actual walked position (smoothed x,y)')

    ax.set_title(title)
    ax.legend(loc='lower right', fontsize=9)

axes[0].set_xlim(x0 - 60, x1 + 60)
axes[0].set_ylim(y1 + 40, y0 - 40)
axes[1].set_xlim(290, 360)
axes[1].set_ylim(340, 220)

fig.suptitle('Graph route (blue, red = the mis-cut edge) vs. real walked path (green)',
             fontsize=13)
fig.tight_layout()
fig.savefig(OUT_PNG, dpi=150)
print(f'[OK] wrote {OUT_PNG}')
