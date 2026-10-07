"""Prepared backend plus causal, paced camera replay. No future-video calibration."""
from pathlib import Path
import argparse
import json
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent
BACKEND=ROOT.parent
sys.path[:0]=[str(ROOT),str(BACKEND/'poc_cross_camera'),str(BACKEND),str(BACKEND/'app')]
from run_temporal_landmark_propagation import (Localizer,accelerate_localizer,DEFAULT_DATA,
    DEFAULT_MAP,DEFAULT_GRAPH,find_reference_size,evaluate_target,dedupe_correspondences,loc)
from run_gap_tracked_pnp import track_step,solve_pose
from app.core.ar_geometry import FloorProjector
from app.core.self_calibration import _solve_p4pf
from prepared_scene import prepare_scene


class OnlineCalibration:
    def __init__(self,K):
        self.K=K.copy();self.estimates=[];self.events=[];self.version=0;self.calibrated=False

    def observe(self,estimate,frame,time_s):
        if not estimate or estimate['inliers']<10 or estimate['median_reproj_error_px']>8:
            return False
        focal=float(estimate['focal_px'])
        if not .25*self.K[0,2]*2<focal<3*self.K[0,2]*2: return False
        self.estimates.append(dict(frame=frame,time=time_s,**estimate))
        if self.version==0:
            # A valid image-derived prior can improve on map intrinsics immediately.
            # It remains explicitly provisional until independent frames agree.
            self.K[0,0]=self.K[1,1]=focal;self.version=1
            self.events.append(dict(observed_frame=frame,observed_time=time_s,focal=focal,
                version=1,stage='provisional',evidence_frames=[frame]))
            return True
        values=np.array([x['focal_px'] for x in self.estimates[-8:]])
        if len(values)<3: return False
        med=float(np.median(values))
        consensus=values[np.abs(values-med)<.12*med]
        if len(consensus)<3: return False
        target=float(np.median(consensus))
        if self.calibrated:
            target=float(self.K[0,0]+np.clip(.2*(target-self.K[0,0]),-.02*self.K[0,0],.02*self.K[0,0]))
            if abs(target-self.K[0,0])<1: return False
        self.K[0,0]=self.K[1,1]=target;self.version+=1;self.calibrated=True
        self.events.append(dict(observed_frame=frame,observed_time=time_s,focal=target,
            version=self.version,stage='calibrated',evidence_frames=[x['frame'] for x in self.estimates[-8:]]))
        return True


class PreparedBackend:
    def __init__(self,out, floor_id, data_dir, map_path, graph_path, start_label, destination_label):
        started=time.perf_counter()
        cv2.setNumThreads(2)
        self.localizer=Localizer(floor_id=floor_id,data_dir=data_dir,floor_plan_path=map_path,
            json_map_path=graph_path,matching_mode='superpoint',retrieval_mode='megaloc')
        accelerate_localizer(self.localizer)
        self.localizer.camera_self_calibrator.close()
        self.size=find_reference_size(data_dir)
        self.projector=FloorProjector(self.localizer.H_matrix,self.localizer.floor_config)
        self.map_K=self.localizer.K.copy()
        (out/'geometry.json').write_text(json.dumps(dict(H=np.asarray(self.localizer.H_matrix).tolist(), floor_config=self.localizer.floor_config), default=lambda x:np.asarray(x).tolist()))
        self.scene=prepare_scene(self.localizer,self.projector,self.size,graph_path,start_label,destination_label)
        # Trigger GPU allocations and inference kernels with a reference image, never video.
        image=cv2.imread(str(self.localizer.keyframes_dir/'0001'/'image.png'))
        self.seed(image,-1,-1,self.map_K)
        self.prepare_s=time.perf_counter()-started
        self.ready=True
        (out/'prepared_scene.json').write_text(json.dumps(self.scene,indent=2))
        (out/'backend_ready.json').write_text(json.dumps(dict(ready=True,prepare_wall_s=self.prepare_s,
            warmed_on='reference keyframe 0001',query_frames_consumed=0,ground_points=self.scene['ground_points']),indent=2))
        print(f'BACKEND_READY before camera start | prepare={self.prepare_s:.2f}s',flush=True)

    def seed(self,frame,index,time_s,K):
        started=time.perf_counter()
        self.localizer.K=K.copy()
        _,direct,_=evaluate_target(self.localizer,frame,self.size,20)
        estimate=_solve_p4pf(direct['points_2d'],direct['points_3d'],K[0,2],K[1,2],128,8.,index+100)
        # Returning observations, not stale pose; foreground re-solves at the current frame.
        return dict(frame=index,time=time_s,direct=direct,estimate=estimate,work_s=time.perf_counter()-started)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--video',type=Path,default=Path(r'D:\video\video_from_iphone_pare\IMG_1895.MOV'))
    parser.add_argument('--duration',type=float,default=60.)
    parser.add_argument('--out',type=Path,default=ROOT/'causal_0_60')
    parser.add_argument('--floor',default='floor1')
    parser.add_argument('--start',default=None)
    parser.add_argument('--destination',default='M21_B')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    data_dir=BACKEND/'app'/'data'/'map_data'/f'result_{args.floor}_6'
    map_path=BACKEND/'app'/'data'/'map'/f'{args.floor}.jpg'
    graph_path=BACKEND/'app'/'data'/'json_map'/f'{args.floor}.json'
    if not data_dir.exists():
        data_dir=DEFAULT_DATA; map_path=DEFAULT_MAP; graph_path=DEFAULT_GRAPH
    backend=PreparedBackend(out,args.floor,data_dir,map_path,graph_path,args.start,args.destination)
    (out/'request.json').write_text(json.dumps(dict(video=str(args.video),floor=args.floor,start=args.start,destination=args.destination),indent=2),encoding='utf-8')
    calibration=OnlineCalibration(backend.map_K)
    # Camera is opened only after backend readiness. No previous experiment cache is loaded.
    cap=cv2.VideoCapture(str(args.video))
    if not cap.isOpened(): raise RuntimeError(args.video)
    fps=cap.get(cv2.CAP_PROP_FPS);count=int(np.ceil(args.duration*fps))
    p2,p3,ids=np.empty((0,2),np.float32),np.empty((0,3),np.float32),np.empty(0,np.int64)
    history=deque(maxlen=100)
    previous=None;pending=None;last_request=-100.;last_seed=None
    last_C=None;last_time=None
    events=[];rows=[];work=[]
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='localization') as worker:
        camera_started=time.perf_counter()
        for index in range(count):
            timestamp=index/fps
            wait=camera_started+timestamp-time.perf_counter()
            if wait>0: time.sleep(wait)
            ok,frame=cap.read()
            if not ok: raise RuntimeError('Source ended before requested duration')
            target_started=time.perf_counter()
            gray=cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),backend.size)
            history.append((index,gray))
            if previous is not None:
                p2,p3,ids=track_step(previous,gray,p2,p3,ids,1.)
            previous=gray
            if pending is not None and pending.done():
                result=pending.result();pending=None
                version_changed=calibration.observe(result['estimate'],result['frame'],result['time'])
                if version_changed:
                    calibration.events[-1]['available_at_frame']=index
                    calibration.events[-1]['available_wall_s']=time.perf_counter()-camera_started
                    last_C=None
                direct=result['direct']
                seed_pose=solve_pose(SimpleNamespace(K=calibration.K),direct['points_2d'],direct['points_3d'])
                refreshed=False
                if seed_pose and seed_pose['accepted'] and history[0][0]<=result['frame']:
                    keep=seed_pose['inliers']
                    q2,q3,qids=direct['points_2d'][keep],direct['points_3d'][keep],direct['mp_ids'][keep]
                    past=[x for x in history if x[0]>=result['frame']]
                    for (_,a),(_,b) in zip(past,past[1:]):
                        q2,q3,qids=track_step(a,b,q2,q3,qids,1.)
                    items=[dict(point_2d=a,point_3d=b,mp_id=int(c),track_error=0)
                        for a,b,c in zip(q2,q3,qids)]
                    items += [dict(point_2d=a,point_3d=b,mp_id=int(c),track_error=1)
                        for a,b,c in zip(p2,p3,ids)]
                    combined=dedupe_correspondences(items)
                    p2,p3,ids=(combined[k] for k in ['points_2d','points_3d','mp_ids'])
                    last_seed=index;refreshed=True
                events.append(dict(source_frame=result['frame'],source_time=result['time'],
                    available_frame=index,available_wall_s=time.perf_counter()-camera_started,
                    work_s=result['work_s'],refreshed=refreshed,focal_estimate=result['estimate']))
            interval=.25 if not calibration.calibrated else 1.
            if pending is None and timestamp-last_request>=interval:
                pending=worker.submit(backend.seed,frame.copy(),index,timestamp,calibration.K.copy())
                last_request=timestamp
            pose=solve_pose(SimpleNamespace(K=calibration.K),p2,p3)
            accepted=bool(pose and pose['accepted'])
            reason='ok' if accepted else 'pnp_quality'
            if accepted:
                C=-pose['R'].T@pose['t']
                if last_C is not None and np.linalg.norm(C-last_C)*backend.projector.metres_per_unit>.25+2.5*(timestamp-last_time):
                    accepted=False;reason='position_jump'
                if accepted: last_C,last_time=C,timestamp
            completed=time.perf_counter()-camera_started
            row=dict(frame=index,time=timestamp,available_wall_s=completed,
                latency_s=completed-timestamp,accepted=accepted,reason=reason,
                calibration_version=calibration.version,calibrated=calibration.calibrated,K=calibration.K.tolist(),
                tracks=len(p2),inliers=len(pose['inliers']) if pose else 0,
                error=float(pose['reproj_error']) if pose else None,last_seed_frame=last_seed)
            if pose:
                row.update(R=pose['R'].tolist(),t=pose['t'].tolist(),
                    xy=backend.projector.camera_floor_px(pose['R'],pose['t']).tolist())
            rows.append(row);work.append(time.perf_counter()-target_started)
            if index%150==0:
                print(f'LIVE {timestamp:.2f}s accepted={accepted} f={calibration.K[0,0]:.1f} version={calibration.version} latency={row["latency_s"]:.3f}s',flush=True)
        pending_work_at_end=bool(pending and not pending.done())
    cap.release()
    def safe(value):
        if isinstance(value,dict): return {k:safe(v) for k,v in value.items()}
        if isinstance(value,list): return [safe(v) for v in value]
        if isinstance(value,float) and not np.isfinite(value): return None
        return value
    (out/'poses.jsonl').write_text(''.join(json.dumps(safe(r))+'\n' for r in rows))
    (out/'calibration_events.json').write_text(json.dumps(safe(dict(estimates=calibration.estimates,commits=calibration.events,seed_events=events)),indent=2))
    first=next((r for r in rows if r['accepted']),None)
    summary=dict(video=str(args.video),frames=len(rows),fps=fps,duration_s=len(rows)/fps,
        prepare_s=backend.prepare_s,ready_before_camera=True,
        first_pose_source_s=first['time'] if first else None,
        first_pose_available_s=first['available_wall_s'] if first else None,
        first_calibration_available_s=next((e['available_wall_s'] for e in calibration.events if e['stage']=='calibrated'),None),
        accepted=sum(r['accepted'] for r in rows),calibration_versions=calibration.version,
        latency_p50_p95_max_s=np.percentile([r['latency_s'] for r in rows],[50,95,100]).tolist(),
        compute_p50_p95_max_s=np.percentile(work,[50,95,100]).tolist(),
        pending_work_at_end=pending_work_at_end,
        provenance='Reference-only scene preparation; strictly sequential query frames and asynchronous past-frame measurements. No cached video calibration, future-frame fitting or retroactive K updates.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__': main()
