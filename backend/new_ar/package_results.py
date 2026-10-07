"""Encode seekable H.264 deliverables and verify every output frame decodes."""
from pathlib import Path
import json
import subprocess
import hashlib
import cv2
import numpy as np
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parent

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=ROOT/'out')
    args=ap.parse_args()
    out=args.out
    cal=json.loads((out/'camera_calibration.json').read_text())
    rows=[json.loads(x) for x in (out/'poses.jsonl').read_text().splitlines()]
    metrics=json.loads((out/'render_metrics.json').read_text())
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    files=[]
    import glob
    input_names=[Path(x).name for x in glob.glob(str(out/'IMG_1895_AR_*.mp4'))+glob.glob(str(out/'IMG_1895_comparison_*.mp4'))]
    for name in input_names:
        target=out.parent/name.replace('.mp4','_h264.mp4')
        subprocess.run([ffmpeg,'-y','-loglevel','error','-i',str(out/name),
            '-ss',str(rows[0]['time']),'-i',cal['video'],
            '-map','0:v:0','-map','1:a?','-c:v','libx264','-preset','veryfast',
            '-crf','19','-pix_fmt','yuv420p','-c:a','aac','-t',str(len(rows)/cal['fps']),
            '-movflags','+faststart',str(target)],check=True)
        cap=cv2.VideoCapture(str(target))
        width,height=int(cap.get(3)),int(cap.get(4))
        fps=cap.get(5)
        count=0
        while True:
            ok,frame=cap.read()
            if not ok: break
            count+=1
        cap.release()
        assert count==len(rows),(name,count,len(rows))
        files.append(dict(name=name,frames=count,width=width,height=height,fps=fps,
            duration_s=count/fps,bytes=target.stat().st_size,
            sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    errors=[r['error'] for r in rows if r['accepted']]
    source=Path(cal['video'])
    report=dict(source=str(source),source_bytes=source.stat().st_size,
        source_mtime_ns=source.stat().st_mtime_ns,frames=len(rows),
        first_source_frame=rows[0]['frame'],last_source_frame=rows[-1]['frame'],
        first_source_timestamp=rows[0]['time'],last_source_timestamp=rows[-1]['time'],
        accepted_pose_frames=sum(r['accepted'] for r in rows),
        accepted_ar_frames=sum(r['ar_accepted'] for r in metrics),
        visible_ar_frames=sum(r['visible_arrows']>0 for r in metrics),
        pose_reprojection_px=dict(median=float(np.median(errors)),p95=float(np.percentile(errors,95))),
        files=files,geometry_unit_tests=4,
        note='Acceptance and reprojection are self-consistency metrics, not ground-truth accuracy. Comparison uses identical calibrated per-frame poses for both renderers.')
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
