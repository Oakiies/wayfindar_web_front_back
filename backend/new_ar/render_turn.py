"""Causal replay with the poc_ar_arrow UI and pose stabilization."""
from pathlib import Path
import sys,json,argparse,time
from types import SimpleNamespace
import cv2,numpy as np,imageio_ffmpeg,subprocess
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT.parent),str(ROOT.parent/'poc_ar_arrow')]
import ar_arrow_v2 as ar
from app.services.ar_service import get_projector

def rounded_route(route,radius=3.):
    points=[np.array(route[0],float)]
    for a,b,c in zip(route,route[1:],route[2:]):
        a,b,c=map(lambda x:np.array(x,float),(a,b,c))
        u,v=a-b,c-b
        radius_here=min(radius,.2*np.linalg.norm(u),.2*np.linalg.norm(v))
        if radius_here<1e-6: continue
        enter=b+u/np.linalg.norm(u)*radius_here
        leave=b+v/np.linalg.norm(v)*radius_here
        for t in np.linspace(0,1,9): points.append((1-t)**2*enter+2*t*(1-t)*b+t*t*leave)
    points.append(np.array(route[-1],float))
    return [p.tolist() for i,p in enumerate(points) if i==0 or np.linalg.norm(p-points[i-1])>1e-6]

def main():
    cv2.setNumThreads(2)
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    summary=json.loads((out/'summary.json').read_text());scene=json.loads((out/'prepared_scene.json').read_text())
    geo=json.loads((out/'geometry.json').read_text());rows=[json.loads(s) for s in (out/'poses.jsonl').read_text().splitlines()]
    loc=SimpleNamespace(H_matrix=np.array(geo['H']),floor_config=geo['floor_config'],K=None)
    proj=get_projector('floor5',loc)
    route=rounded_route(scene['route'])
    original_guidance=ar.route_guidance_mode
    ar.route_guidance_mode=lambda x,y,path:original_guidance(x,y,scene['route'])
    # Render a short rounded transition, but retain the graph's real corner for
    # visibility clipping. Otherwise the rounded samples look like tiny bends
    # and the lane can be projected through the wall beyond the junction.
    original_next_turn=ar.nav.next_turn_info
    ar.nav.next_turn_info=lambda x,y,path:original_next_turn(x,y,scene['route'])
    original_chevrons=ar.chevron_anchors
    ar.chevron_anchors=lambda x,y,path,clip_at_corner=True,recenter=True: original_chevrons(
        x,y,path,clip_at_corner=True,recenter=recenter)
    stabilizer=ar.PoseStabilizer(metres_per_unit=proj.metres_per_unit,expected_interval_s=1/30)
    progress=ar.RouteProgressTracker(allowed_backslide_px=4)
    cap=cv2.VideoCapture(summary['video']);fps=summary['fps']
    writer=cv2.VideoWriter(str(out/'turn_temp.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),fps,(1280,720))
    records=[];panels=[];last_good=None;raw_probe=[];filtered_probe=[];cost=[];near_count=0
    probe=proj.floor_point(*scene['route'][-2])
    def project(R,t,K):
        c=R@probe+t
        return (K@c)[:2]/c[2] if c[2]>0.1 else None
    for row in rows:
        ok,frame=cap.read()
        if not ok: raise RuntimeError('short video')
        raw_h,raw_w=frame.shape[:2];frame=cv2.resize(frame,(1280,720))
        K=np.array(row['K']);K[0]*=1280/raw_w;K[1]*=720/raw_h;loc.K=K
        payload=None;reason='tracking unavailable';started=time.perf_counter()
        if row['accepted']:
            if last_good is None or row['time']-last_good>.2:
                stabilizer=ar.PoseStabilizer(metres_per_unit=proj.metres_per_unit,expected_interval_s=1/30)
            last_good=row['time']
            R,t=np.array(row['R']),np.array(row['t']);xy=row['xy']
            payload,reason=ar.build_ar_world_v2(loc,'floor5',dict(R=R,t=t),*xy,route,row['inliers'],(1280,720),row['error'],stabilizer=stabilizer,pin_route=True,timestamp=row['time'],progress_tracker=progress)
            distance=np.linalg.norm(np.array(xy)-scene['route'][-1])
            near_count=near_count+1 if distance<8 else 0
            if near_count>=3: payload=None;reason='near destination'
            rp=project(R,t,K);sp=project(stabilizer.R,-stabilizer.R@stabilizer.C,K) if stabilizer.R is not None else None
            raw_probe.append(rp);filtered_probe.append(sp)
        else: raw_probe.append(None);filtered_probe.append(None);near_count=0
        if payload:
            # Limit distant geometry: a map does not provide wall occlusion.
            Rv,tv=payload['R'],payload['t'];mpu=payload['metres_per_unit']
            payload['ribbon_quads']=[(q,d) for q,d in payload['ribbon_quads'] if d*mpu<=12]
            payload['ribbon_edges']=[e for e in payload['ribbon_edges'] if np.max((Rv@np.asarray(e).T).T[:,2]+tv[2])*mpu<=12]
            pairs=[(p,a) for p,a in zip(payload['carets'],payload['alphas']) if float((Rv@np.mean(p,axis=0)+tv)[2])*mpu<=12]
            payload['carets']=[p for p,a in pairs];payload['alphas']=[a for p,a in pairs]
        frame=ar.render_v2(frame,payload) if row['time']>=25 else frame
        cost.append(time.perf_counter()-started)
        n=len(payload['carets']) if payload else 0
        records.append(dict(frame=row['frame'],time=row['time'],visible_arrows=n,reason=reason))
        if row['time']<25: continue
        cv2.rectangle(frame,(0,0),(1280,42),(22,22,22),-1)
        cv2.putText(frame,f"{row['time']:05.2f}s | Fire Exit 1 | {reason} | causal pose + PoC floor AR",(12,28),0,.65,(255,255,255),1,cv2.LINE_AA)
        writer.write(frame)
        if row['frame']%150==0:
            cv2.imwrite(str(out/f"turn_{row['time']:05.1f}.png"),frame)
            panels.append(cv2.resize(frame,(640,360)))
        if row['frame']%300==0: print('RENDER',row['time'],reason,n,flush=True)
    cap.release();writer.release()
    for i in range(0,len(panels),6):
        batch=panels[i:i+6]
        if len(batch)%2:batch.append(np.zeros_like(batch[0]))
        cv2.imwrite(str(out/f'review_{i//6}.png'),np.vstack([np.hstack(batch[j:j+2]) for j in range(0,len(batch),2)]))
    final=out/'floor5_2_FireExit1_AR_25_110.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-loglevel','error','-i',str(out/'turn_temp.mp4'),'-ss','25','-i',r'D:\video\floor5_2.mp4','-map','0:v:0','-map','1:a?','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-t','85','-movflags','+faststart',str(final)],check=True)
    def jitter(seq):
        values=[]
        for i in range(2,len(seq)):
            if all(seq[j] is not None for j in [i-2,i-1,i]):values.append(float(np.linalg.norm(seq[i]-2*seq[i-1]+seq[i-2])))
        return np.percentile(values,[50,95]).tolist() if values else None
    (out/'render_frames.json').write_text(json.dumps(records))
    report=dict(file=str(final),start_s=25,end_s=110,frames_written=sum(r['time']>=25 for r in rows),raw_probe_second_difference_px=jitter(raw_probe),filtered_probe_second_difference_px=jitter(filtered_probe),render_compute_p50_p95_s=np.percentile(cost,[50,95]).tolist(),route=route,limitations=['Offline rendering with causal pose filter; rendering cost is separate from localization latency.','Near destination is map proximity, not independently verified arrival.'])
    (out/'turn_report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
