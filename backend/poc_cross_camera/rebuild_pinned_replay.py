"""Rebuild accepted replay AR with fixed world stations; no new localization."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import ar_service


def main():
    source = ROOT/'poc_cross_camera/out/replay_registration_1p5s'
    out = source/'world_pinned'
    out.mkdir(exist_ok=True)
    data = ROOT/'app/data/map_data/result_floor1_4'
    localizer = SimpleNamespace(
        H_matrix=np.load(data/'H_matrix_floor1_4_offset.npy'),
        floor_config=json.loads((data/'floor_algin_offset_config.json').read_text(encoding='utf-8')))
    shifts = []
    with (out/'updates.jsonl').open('w',encoding='utf-8') as dest:
        for line in (source/'updates.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            payload=row.get('ar_world')
            row['baseline_ar_world']=payload
            if payload:
                fx,fy,cx,cy=payload['K']
                localizer.K=np.array([[fx,0,cx],[0,fy,cy],[0,0,1]])
                pose={k:payload[k] for k in ('R','t')}
                projector=ar_service.get_projector('floor1',localizer)
                px,py=projector.camera_floor_px(pose['R'],pose['t'])
                offset,(nx,ny)=ar_service._lateral_offset(px,py,row['path'])
                shifts.append({'timestamp':row['timestamp'],'old_shift_px':[-offset*nx,-offset*ny]})
                # Only rebuild payloads that already passed production quality gates.
                fresh=ar_service.build_ar_world_poc(localizer,'floor1',pose,px,py,
                    row['path'],100,payload['imgWH'],0,pin_route=True)
                if fresh and payload.get('destination_marker'):
                    fresh['destination_marker']=payload['destination_marker']
                row['ar_world']=fresh
            dest.write(json.dumps(row,ensure_ascii=False)+'\n')
    steps=[float(np.linalg.norm(np.array(b['old_shift_px'])-a['old_shift_px']))
           for a,b in zip(shifts,shifts[1:])]
    metrics={'source':'accepted poses from previous fresh 1.5s M21 run',
             'max_removed_world_shift_step_px':max(steps,default=0),
             'max_removed_world_shift_step_m':max(steps,default=0)*ar_service.M_PER_PX,
             'pinned_shift_step_px':0,
             'note':'Measures camera-dependent translation of world geometry, not pose noise or image accuracy.',
             'shifts':shifts}
    (out/'anchor_stability.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print({k:v for k,v in metrics.items() if k!='shifts'})


if __name__=='__main__':
    main()
