"""Compare plane projection against held-out observed ground map landmarks."""
from pathlib import Path
import json
import sys
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from app.core.ar_geometry import FloorProjector
from world_ar import plane_intersection

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=ROOT/'out')
    args=ap.parse_args()
    out=args.out
    geometry=json.loads((out/'map_geometry.json').read_text())
    cal=json.loads((out/'camera_calibration.json').read_text())
    floor=json.loads((out/'floor_calibration.json').read_text())
    projector=FloorProjector(geometry['H'],geometry['floor_config'])
    n=np.array(floor['normal'])
    K=np.array(cal['K'])
    old_offset=float(projector.down@(projector.traj_center+projector.drop*projector.down))
    result=[]
    for seconds in floor['heldout_frames']:
        data=np.load(out/f'landmarks_{seconds}.npz')
        C=-data['R'].T@data['t']
        keep=(data['p2'][:,1]>600)&((data['p3']-C)@projector.down>.08)
        p2,p3=data['p2'][keep],data['p3'][keep]
        entry=dict(time=seconds,count=len(p2))
        for label,normal,offset in [('current',projector.down,old_offset),('new',n,floor['offset'])]:
            on_plane=np.array([plane_intersection(p,projector.down,normal,offset) for p in p3])
            camera=(data['R']@on_plane.T).T+data['t']
            uv=(K@camera.T).T
            uv=uv[:,:2]/uv[:,2:]
            errors=np.linalg.norm(uv-p2,axis=1)
            entry[label+'_pixel_errors']=errors.tolist()
            entry[label+'_median_px']=float(np.median(errors))
        result.append(entry)
    old=np.concatenate([r['current_pixel_errors'] for r in result])
    new=np.concatenate([r['new_pixel_errors'] for r in result])
    report=dict(method='Project held-out ground landmarks onto each proposed floor plane, then compare with observed image pixels. Same K and independent direct pose at each held-out frame.',
        note='9 automatically selected sparse floor candidates, not manually surveyed ground truth. This evaluates floor-plane alignment, not whole-route accuracy.',
        current_median_px=float(np.median(old)),new_median_px=float(np.median(new)),rows=result)
    (out/'ground_registration_check.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
