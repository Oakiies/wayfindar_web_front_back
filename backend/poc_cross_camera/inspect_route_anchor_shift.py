"""Compare route-anchor policies using fresh poses, without rerunning models."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import ar_service
from poc_ar_arrow import ar_arrow_v2 as ar
from run_non_imu_video_comparison import payload_screen_polygons
from render_fullrate_non_imu_ar import draw_overlay

OUT = ROOT / 'poc_cross_camera/out/replay_registration_1p5s'
DATA = ROOT / 'app/data/map_data/result_floor1_4'


def main():
    updates = [json.loads(line) for line in (OUT/'updates.jsonl').read_text(encoding='utf-8').splitlines()]
    localizer = SimpleNamespace(
        H_matrix=np.load(DATA/'H_matrix_floor1_4_offset.npy'),
        floor_config=json.loads((DATA/'floor_algin_offset_config.json').read_text(encoding='utf-8')))
    cap = cv2.VideoCapture(r'D:\video\video_from_iphone_oak_wide\IMG_6955.MOV')
    original = ar.chevron_anchors
    samples = []
    def pinned(x, y, path_coords, clip_at_corner=True, recenter=True):
        anchors = original(x, y, path_coords, clip_at_corner)
        offset, (nx, ny) = ar_service._lateral_offset(x, y, path_coords)
        return [(px+offset*nx, py+offset*ny) for px, py in anchors]
    for target in (19.5, 25.5, 31.5, 34.5, 43.5, 49.5):
        update = min(updates, key=lambda row: abs(row['timestamp']-target))
        payload = update.get('ar_world')
        if not payload:
            continue
        fx, fy, cx, cy = payload['K']
        localizer.K = np.array([[fx,0,cx],[0,fy,cy],[0,0,1]])
        pose = {key: payload[key] for key in ('R','t')}
        cap.set(cv2.CAP_PROP_POS_MSEC, update['timestamp']*1000)
        ok, frame = cap.read()
        if not ok:
            continue
        try:
            ar.chevron_anchors = pinned
            candidate = ar_service.build_ar_world_poc(localizer, 'floor1', pose,
                update['position']['x'], update['position']['y'], update['path'],
                100, payload['imgWH'], 0)
        finally:
            ar.chevron_anchors = original
        panes = []
        for title, item in [('CURRENT: shifted through camera', payload), ('EXPERIMENT: pinned map route', candidate)]:
            pane = cv2.resize(draw_overlay(frame, payload_screen_polygons(item, frame.shape)), (640,360))
            cv2.rectangle(pane,(0,0),(640,35),(0,0,0),-1)
            cv2.putText(pane,f'{title} {update["timestamp"]:.2f}s',(8,23),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
            panes.append(pane)
        pair=np.hstack(panes)
        cv2.imwrite(str(OUT/f'anchor_shift_{target:.1f}.jpg'),pair)
        samples.append(pair)
    cap.release()
    cv2.imwrite(str(OUT/'anchor_shift_contact.jpg'),np.vstack(samples))


if __name__ == '__main__':
    main()
