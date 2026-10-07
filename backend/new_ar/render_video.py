"""Render calibrated replay, current geometry ablation, and visual inspection sheets."""
from pathlib import Path
import json
import sys
from types import SimpleNamespace
import cv2
import numpy as np
import networkx as nx

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT.parent),str(ROOT.parent/'poc_cross_camera'),str(ROOT.parent/'app')]
from app.core.ar_geometry import FloorProjector
from app.services.ar_service import MAX_REPROJ_ERROR_PX
from run_non_imu_video_comparison import payload_screen_polygons
from render_fullrate_non_imu_ar import draw_overlay
from world_ar import fit_floor,plane_intersection,fixed_arrows,draw

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=ROOT/'out')
    args=ap.parse_args()
    out=args.out
    calibration=json.loads((out/'camera_calibration.json').read_text())
    geometry=json.loads((out/'map_geometry.json').read_text())
    rows=[json.loads(x) for x in (out/'poses.jsonl').read_text().splitlines()]
    first_second=int(round(rows[0]['time']))
    last_second=int(round(rows[-1]['time'] + 1))
    suffix=f'{first_second}_{last_second}'
    projector=FloorProjector(geometry['H'],geometry['floor_config'])
    K=np.array(calibration['K'])
    # Independent floor observations in map coordinates, not hand-picked screen anchors.
    samples=[]
    for seconds in [24,30,40]:
        data=np.load(out/f'landmarks_{seconds}.npz')
        p2,p3=data['p2'],data['p3']
        C=-data['R'].T@data['t']
        mask=(p2[:,1]>540)&(p2[:,0]>384)&(p2[:,0]<1536)&((p3-C)@projector.down>.08)
        samples.extend(p3[mask])
    normal,offset,mask=fit_floor(samples,projector.down)
    heights=[offset-normal@(-np.array(r['R']).T@r['t']) for r in rows if r['accepted'] and 25<r['time']<40]
    # Metric scale is explicitly conditional on a 1.5m phone holding height.
    upm=float(np.median(heights))/1.5
    floor_report=dict(normal=normal.tolist(),offset=offset,points=len(samples),inliers=int(mask.sum()),
        units_per_metre=upm,assumed_camera_height_m=1.5,
        calibration_frames=[24,30,40],heldout_frames=[50,59],
        note='Offline floor fit. Camera K was frozen before tracking. Ground normal has a 15 degree prior; no per-time plane correction.')
    for seconds in [50,59]:
        d=np.load(out/f'landmarks_{seconds}.npz')
        C=-d['R'].T@d['t']
        keep=(d['p2'][:,1]>600)&((d['p3']-C)@projector.down>.08)
        floor_report[f'heldout_{seconds}_residual_m']=(np.abs(d['p3'][keep]@normal-offset)/upm).tolist()
    (out/'floor_calibration.json').write_text(json.dumps(floor_report,indent=2))
    graph=json.loads((ROOT.parent/'app/data/json_map/floor1.json').read_text(encoding='utf-8-sig'))['graph']
    nodes=graph['nodes']
    coords={k:np.array([v['metadata']['position']['x'],v['metadata']['position']['y']],float) for k,v in nodes.items()}
    G=nx.Graph()
    for e in graph['edges']:
        a,b=e['source'],e['target']
        G.add_edge(a,b,weight=float(np.linalg.norm(coords[a]-coords[b])))
    labels={v['label']:k for k,v in nodes.items()}
    # Declared replay scenario follows the corridor observed in the clip; not destination GT.
    waypoints=['Intersection 3','Intersection 1','Intersection 2','M23_B','M21_B']
    path=[]
    for a,b in zip(waypoints,waypoints[1:]):
        segment=nx.shortest_path(G,labels[a],labels[b],weight='weight')
        path.extend(segment if not path else segment[1:])
    route=np.array([coords[k] for k in path])
    (out/'route.json').write_text(json.dumps(dict(assumption='Replay test route, inferred corridor direction; destination not supplied by user',
        labels=[nodes[k]['label'] for k in path],points=route.tolist()),indent=2))
    route_world=np.array([plane_intersection(projector.plane_point(*p),projector.down,normal,offset) for p in route])
    arrows=fixed_arrows(route_world,normal,upm)
    (out/'world_anchors.json').write_text(json.dumps([dict(center=x['center'].tolist(),polygon=x['polygon'].tolist(),station=float(x['station']),segment=int(x['segment'])) for x in arrows],indent=2))
    localizer=SimpleNamespace(H_matrix=np.array(geometry['H']),floor_config=geometry['floor_config'],K=K)
    cap=cv2.VideoCapture(calibration['video'])
    fps=calibration['fps']
    cap.set(cv2.CAP_PROP_POS_FRAMES,rows[0]['frame'])
    writer=cv2.VideoWriter(str(out/f'IMG_1895_AR_{suffix}.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),fps,(1280,720))
    compare=cv2.VideoWriter(str(out/f'IMG_1895_comparison_{suffix}.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),fps,(1920,540))
    assert writer.isOpened() and compare.isOpened()
    inspection=[]
    samplesheets=[]
    for i,row in enumerate(rows):
        ok,frame=cap.read()
        assert ok
        frame=cv2.resize(frame,(1280,720),interpolation=cv2.INTER_AREA)
        render_K=K.copy()
        render_K[:2]*=1280/calibration['image_size'][0]
        candidate,baseline=frame.copy(),frame.copy()
        count=0
        ar_accepted=row['accepted'] and row['error']<=MAX_REPROJ_ERROR_PX
        if row['accepted']:
            R,t=np.array(row['R']),np.array(row['t'])
            if ar_accepted:
                candidate,count,_=draw(frame,arrows,R,t,render_K,upm)
            # The full-minute deliverable focuses on the new world renderer.
            # The old renderer remains available in the 20-60 comparison file.
            baseline=frame.copy()
        status=f'{row["time"]:05.2f}s | {row["inliers"]} inliers | '+('TRACKED' if ar_accepted else 'POSE UNCERTAIN')
        candidate=cv2.resize(candidate,(1280,720))
        cv2.rectangle(candidate,(0,0),(1280,42),(20,20,20),-1)
        cv2.putText(candidate,'NEW WORLD AR | '+status,(14,28),0,.7,(255,255,255),1,cv2.LINE_AA)
        cv2.putText(candidate,'Replay route: corridor to M21_B (assumed)',(14,701),0,.55,(255,255,255),1,cv2.LINE_AA)
        if not count:
            message='Updating visual position' if not ar_accepted else 'Floor markers not visible from this angle'
            cv2.rectangle(candidate,(350,645),(930,682),(25,25,25),-1)
            cv2.putText(candidate,message,(365,670),0,.6,(255,255,255),1,cv2.LINE_AA)
        left=cv2.resize(baseline,(960,540))
        right=cv2.resize(candidate,(960,540))
        cv2.rectangle(left,(0,0),(960,32),(20,20,20),-1)
        cv2.putText(left,'CURRENT GEOMETRY / SAME CALIBRATED POSE',(10,22),0,.55,(255,255,255),1,cv2.LINE_AA)
        panel=np.hstack([left,right])
        writer.write(candidate)
        compare.write(panel)
        inspection.append(dict(time=row['time'],pose_accepted=row['accepted'],ar_accepted=bool(ar_accepted),visible_arrows=count))
        if i%60==0:
            cv2.imwrite(str(out/f'check_{i:04d}.png'),panel)
            samplesheets.append(cv2.resize(panel,(960,270)))
        if i%150==0: print('RENDER',status,'arrows',count,flush=True)
    cap.release();writer.release();compare.release()
    for index in range(0,len(samplesheets),5):
        cv2.imwrite(str(out/f'contact_sheet_{index//5+1}.png'),np.vstack(samplesheets[index:index+5]))
    (out/'render_metrics.json').write_text(json.dumps(inspection,indent=2))
    print('FLOOR',floor_report)

if __name__=='__main__': main()
