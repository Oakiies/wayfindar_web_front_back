"""Render only causal per-frame results; preserve per-frame K and availability evidence."""
from pathlib import Path
import argparse
import json
import subprocess
import cv2
import numpy as np
import imageio_ffmpeg
try:
    from .world_ar import draw, visible_scene
except ImportError:  # direct script execution
    from world_ar import draw, visible_scene

ROOT=Path(__file__).resolve().parent

def render_scene(frame,anchors,R,t,K):
    selected=visible_scene(anchors,R,t,K,(frame.shape[1],frame.shape[0]))
    output=frame.copy()
    for item in selected:
        pixels=item['pixels'];alpha=item['alpha']
        mask=np.zeros(frame.shape[:2],np.uint8)
        cv2.fillPoly(mask,[np.round(pixels).astype(np.int32)],255)
        layer=output.copy();layer[mask>0]=(255,170,0)
        output=cv2.addWeighted(layer,alpha,output,1-alpha,0)
        cv2.polylines(output,[np.round(pixels).astype(np.int32)],True,(255,240,195),1,cv2.LINE_AA)
    return output,len(selected)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=ROOT/'causal_0_60')
    args=parser.parse_args();out=args.out.resolve()
    summary=json.loads((out/'summary.json').read_text())
    request=json.loads((out/'request.json').read_text()) if (out/'request.json').exists() else {}
    scene=json.loads((out/'prepared_scene.json').read_text())
    rows=[json.loads(x) for x in (out/'poses.jsonl').read_text().splitlines()]
    cap=cv2.VideoCapture(summary['video'])
    writer=cv2.VideoWriter(str(out/'render.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),summary['fps'],(1280,720))
    if not writer.isOpened(): raise RuntimeError('Video writer unavailable')
    results=[];panels=[]
    for i,row in enumerate(rows):
        ok,raw=cap.read()
        if not ok: raise RuntimeError('Source video ended early')
        frame=cv2.resize(raw,(1280,720),interpolation=cv2.INTER_AREA)
        K=np.array(row['K']);K[0]*=1280/raw.shape[1];K[1]*=720/raw.shape[0]
        count=0
        accepted=row['accepted'] and row['error']<=6.3
        if accepted:
            frame,count=render_scene(frame,scene['anchors'],np.array(row['R']),np.array(row['t']),K)
        state='NAVIGATING' if accepted else 'FINDING POSITION'
        calibration='CAMERA CALIBRATED' if row.get('calibrated',False) else 'ADAPTING CAMERA'
        cv2.rectangle(frame,(0,0),(1280,70),(20,20,20),-1)
        cv2.putText(frame,f'{row["time"]:05.2f}s | {state} | {calibration}',(14,27),0,.65,(255,255,255),1,cv2.LINE_AA)
        cv2.putText(frame,f'Backend ready before camera | f={row["K"][0][0]:.0f}px | inliers={row["inliers"]} | latency={row["latency_s"]*1000:.0f}ms',
            (14,55),0,.53,(210,225,230),1,cv2.LINE_AA)
        if row['accepted']:
            # Navigation is available as soon as position exists, even when a floor is not visible.
            route=np.array(scene['route'])
            user=np.array(row['xy'])
            nearest=int(np.argmin(np.linalg.norm(route-user,axis=1)))
            nextpoint=route[min(nearest+1,len(route)-1)]
            message=f'Route to {request.get("destination", "destination")} | map {user[0]:.0f}, {user[1]:.0f}'
        else:
            message='Looking for visual landmarks'
        cv2.rectangle(frame,(0,684),(1280,720),(20,20,20),-1)
        cv2.putText(frame,message,(14,708),0,.55,(255,255,255),1,cv2.LINE_AA)
        writer.write(frame)
        results.append(dict(frame=i,time=row['time'],available_wall_s=row['available_wall_s'],
            navigation=row['accepted'],ar_accepted=bool(accepted),visible_arrows=count))
        if i%60==0 or i in [15,30,45,60,75,90,105,120]:
            cv2.imwrite(str(out/f'frame_{i:04d}.png'),frame)
        if i%60==0: panels.append(cv2.resize(frame,(640,360)))
        if i%300==0: print(f'RENDER {row["time"]:.2f}s arrows={count}',flush=True)
    cap.release();writer.release()
    for page in range(0,len(panels),6):
        batch=panels[page:page+6]
        if len(batch)%2: batch.append(np.zeros_like(batch[0]))
        sheet=np.vstack([np.hstack(batch[j:j+2]) for j in range(0,len(batch),2)])
        cv2.imwrite(str(out/f'contact_{page//6+1}.png'),sheet)
    final=out/'IMG_1895_causal_AR.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-loglevel','error','-i',str(out/'render.mp4'),
        '-i',summary['video'],'-map','0:v:0','-map','1:a?','-c:v','libx264','-preset','veryfast','-crf','19',
        '-pix_fmt','yuv420p','-c:a','aac','-t',str(len(rows)/summary['fps']),'-movflags','+faststart',str(final)],check=True)
    cap=cv2.VideoCapture(str(final));decoded=0
    while cap.read()[0]: decoded+=1
    cap.release()
    if decoded!=len(rows): raise RuntimeError(f'Video frame mismatch {decoded}/{len(rows)}')
    first=next((r for r in results if r['visible_arrows']),None)
    report=dict(frames=decoded,first_visible_ar_source_s=first['time'] if first else None,
        first_visible_ar_available_s=first['available_wall_s'] if first else None,
        visible_ar_frames=sum(r['visible_arrows']>0 for r in results),file=str(final),
        no_future_queries=all(e['source_frame']<=e['available_frame'] for e in json.loads((out/'calibration_events.json').read_text())['seed_events']))
    (out/'render_verification.json').write_text(json.dumps(report,indent=2))
    (out/'render_frames.json').write_text(json.dumps(results))
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
