"""Put a native-resolution map popup on the already-validated AR render.

The localization pass is intentionally not repeated here. The existing full
render already contains the verified 20 FPS pose/sync metrics; this exporter
uses those metrics to redraw only the map card on the original-size output.
That keeps the camera/AR composition unchanged while preventing the map from
being enlarged from a 238 px comparison pane.
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

from app.core import navigation as nav  # noqa: E402
from app.core.topology import load_graph  # noqa: E402
from poc_ar_arrow.render_poc import render_map_popup  # noqa: E402


SOURCE = BACKEND.parent.parent / 'navigate_indoor' / 'uploads' / 'floor5_2.mp4'
BASE = HERE / 'out' / 'ar_poc_v2_right_1920x1080_30fps.mp4'
METRICS = HERE / 'out' / 'ar_poc_poc37_density_hold_full_111s.csv'
OUTPUT = HERE / 'out' / 'ar_poc_v2_right_native_map_clear_full_111s_30fps.mp4'
GRAPH = BACKEND / 'app' / 'data' / 'json_map' / 'floor5.json'

SOURCE_FPS = 59.94
RENDER_FPS = 20.0
OUTPUT_FPS = 30.0
MAP_SIZE = 500
MAP_MARGIN = 38
MAP_TOP = 140


class RouteCache:
    def __init__(self) -> None:
        self.coords: list[tuple[float, float]] | None = None


def read_metrics() -> list[dict[str, str]]:
    with METRICS.open('r', encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def value(row: dict[str, str], key: str) -> float | None:
    raw = row.get(key, '')
    if raw in ('', None):
        return None
    try:
        result = float(raw)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def route_for(
    graph,
    nodes: dict,
    cache: RouteCache,
    x: float,
    y: float,
) -> list[tuple[float, float]] | None:
    if cache.coords:
        _, projected = nav._nearest_on_path(x, y, cache.coords)
        if math.hypot(x - projected[0], y - projected[1]) <= 55.0:
            return cache.coords

    destination = nav.get_node_by_name(nodes, 'Fire Exit 1', exact=False)
    if destination is None:
        return cache.coords
    _, path = nav.find_best_start_node(graph, nodes, x, y, destination, top_k=3)
    if not path:
        return cache.coords
    cache.coords = [
        (float(point[0]), float(point[1]))
        for point in nav.get_path_coordinates(nodes, path)
    ]
    return cache.coords


def replace_old_popup_with_source(frame: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Remove the old enlarged popup so its pixels cannot show through corners."""
    height, width = frame.shape[:2]
    left = max(0, width - 555)
    top = max(0, MAP_TOP - 12)
    right = min(width, width - MAP_MARGIN + 12)
    bottom = min(height, MAP_TOP + MAP_SIZE + 78)
    frame[top:bottom, left:right] = source[top:bottom, left:right]
    return frame


def main() -> None:
    rows = read_metrics()
    base = cv2.VideoCapture(str(BASE))
    source = cv2.VideoCapture(str(SOURCE))
    if not base.isOpened() or not source.isOpened():
        raise SystemExit('base render or source video could not be opened')

    width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(base.get(cv2.CAP_PROP_FRAME_COUNT))
    if (width, height) != (1920, 1080):
        raise SystemExit(f'unexpected source size: {width}x{height}')

    writer = cv2.VideoWriter(
        str(OUTPUT), cv2.VideoWriter_fourcc(*'mp4v'), OUTPUT_FPS, (width, height)
    )
    if not writer.isOpened():
        raise SystemExit(f'could not open output: {OUTPUT}')

    graph, nodes = load_graph(str(GRAPH), verbose=False)
    cache = RouteCache()
    last_position: tuple[float, float] | None = None
    last_heading: float | None = None
    base_frame_index = -1
    source_frame_index = -1
    source_frame_count = int(source.get(cv2.CAP_PROP_FRAME_COUNT))
    written = 0

    for output_index in range(total):
        wanted_base = output_index
        while base_frame_index < wanted_base:
            ok, base_frame = base.read()
            if not ok:
                break
            base_frame_index += 1
        if base_frame_index != wanted_base:
            break

        # Each 20 FPS metrics row represents source frames 0, 3, 6, ... .
        row_index = min(len(rows) - 1, int(round(output_index * RENDER_FPS / OUTPUT_FPS)))
        row = rows[row_index]
        source_target = min(source_frame_count - 1, row_index * 3)
        while source_frame_index < source_target:
            ok, source_frame = source.read()
            if not ok:
                break
            source_frame_index += 1
        if source_frame_index != source_target:
            break

        x = value(row, 'x')
        y = value(row, 'y')
        if x is not None and y is not None:
            last_position = (x, y)
            route_for(graph, nodes, cache, x, y)
        heading = value(row, 'map_heading')
        if heading is not None:
            last_heading = heading

        composed = base_frame.copy()
        if cache.coords:
            composed = replace_old_popup_with_source(composed, source_frame)
            pose_visible = str(row.get('map_pose_visible', '0')) == '1'
            pose = last_position if pose_visible else None
            composed = render_map_popup(
                composed,
                cache.coords,
                pose,
                last_heading,
                corner='top-right',
                top_override=MAP_TOP,
                size_override=MAP_SIZE,
                margin_override=MAP_MARGIN,
            )

        writer.write(composed)
        written += 1
        if written % 300 == 0:
            print(f'frames={written}/{total}', flush=True)

    base.release()
    source.release()
    writer.release()
    print(f'frames={written} fps={OUTPUT_FPS:.2f} size={width}x{height}')
    print(f'video={OUTPUT}')


if __name__ == '__main__':
    main()
