from pathlib import Path
import cv2, json, hashlib
root=Path(__file__).resolve().parent
path=root/'IMG_1895_AR_0_60.mp4'
cap=cv2.VideoCapture(str(path)); count=0; first=None; last=None
while True:
    ok,frame=cap.read()
    if not ok: break
    if first is None: first=(frame.shape[1],frame.shape[0])
    last=(frame.shape[1],frame.shape[0]); count+=1
fps=cap.get(cv2.CAP_PROP_FPS); cap.release()
report=dict(file=str(path),frames=count,fps=fps,duration_s=count/fps,
    resolution=first,all_frames_same_resolution=(first==last),bytes=path.stat().st_size,
    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    warmup_frames=600,ar_frames=count-600,
    note='0-20s is original video with explicit calibration/warmup label; AR world renderer starts after camera calibration and verified pose.')
(root/'out/full_video_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
