"""Plot a floor's SLAM trajectory, projected with its H matrix, over the floor plan + route graph.

    cd WebNav_front_back/backend
    .venv/Scripts/python -m app.scripts.plot_floor_alignment --floor floor_siamdis3
Output: app/out/<floor_id>_alignment.png
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR.parent))
DATA = APP_DIR / 'data'


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image
    from app.core.localizer import _find_h_matrix_path
    from app.core.localization import project_to_floor_plan

    ap = argparse.ArgumentParser()
    ap.add_argument('--floor', required=True)
    floor_id = ap.parse_args().floor
    cfg = json.loads((DATA / 'config' / 'building.json').read_text(encoding='utf-8-sig'))
    floor = next(f for f in cfg['floors'] if f['id'] == floor_id)
    dd = DATA / floor['data_dir']
    H = np.load(_find_h_matrix_path(dd))
    fcfg = json.loads((dd / 'floor_algin_offset_config.json').read_text(encoding='utf-8-sig'))

    rows = np.array([l.split() for l in (dd / 'KeyFrameTrajectory.txt').read_text().splitlines() if l.strip()], float)
    pts = np.array([project_to_floor_plan(p, H, fcfg) for p in rows[:, 1:4]])
    img = Image.open(DATA / floor['map_image'])
    graph = json.loads((DATA / floor['graph_json']).read_text(encoding='utf-8'))['graph']
    nodes = {k: v['metadata']['position'] for k, v in graph['nodes'].items()}

    fig, ax = plt.subplots(figsize=(14, 10.8), dpi=110)
    ax.imshow(img)
    for e in graph['edges']:
        a, b = nodes[e['source']], nodes[e['target']]
        ax.plot([a['x'], b['x']], [a['y'], b['y']], color='#f59e0b', lw=1.6, alpha=.9, zorder=2)
    sc = ax.scatter(pts[:, 0], pts[:, 1], c=np.arange(len(pts)), cmap='viridis', s=5, zorder=3)
    ax.scatter(*pts[0], c='lime', s=90, edgecolor='k', zorder=5, label='trajectory start')
    ax.scatter(*pts[-1], c='red', s=90, edgecolor='k', zorder=5, label='trajectory end')
    ax.scatter([n['x'] for n in nodes.values()], [n['y'] for n in nodes.values()], c='white', s=22, edgecolor='#f59e0b', zorder=4, label='graph node')
    fig.colorbar(sc, ax=ax, fraction=.03, label='keyframe order')
    ax.set_title(f'{floor_id}: trajectory (H-aligned) vs floor plan + route graph  [{len(pts)} keyframes]')
    ax.legend(loc='lower right')
    out = APP_DIR / 'out' / f'{floor_id}_alignment.png'
    fig.savefig(out, bbox_inches='tight')
    print('saved', out)
    inside = ((pts[:, 0] >= 0) & (pts[:, 0] < img.width) & (pts[:, 1] >= 0) & (pts[:, 1] < img.height)).mean()
    print(f'inside plan: {inside:.1%}  x[{pts[:,0].min():.0f},{pts[:,0].max():.0f}] y[{pts[:,1].min():.0f},{pts[:,1].max():.0f}]')


if __name__ == '__main__':
    main()
