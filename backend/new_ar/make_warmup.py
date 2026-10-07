import cv2
from pathlib import Path

src=Path(r'D:\video\video_from_iphone_pare\IMG_1895.MOV')
out=Path(__file__).resolve().parent/'warmup_0_20.mp4'
cap=cv2.VideoCapture(str(src)); fps=cap.get(cv2.CAP_PROP_FPS) or 30.0
writer=cv2.VideoWriter(str(out),cv2.VideoWriter_fourcc(*'mp4v'),fps,(1280,720))
target=round(20*fps); n=0
while n<target:
    ok,frame=cap.read()
    if not ok: break
    frame=cv2.resize(frame,(1280,720),interpolation=cv2.INTER_AREA)
    cv2.rectangle(frame,(0,0),(1280,48),(15,15,15),-1)
    cv2.putText(frame,f'CALIBRATION / AR WARMUP | {n/fps:05.2f}s | AR hidden until pose is verified',(16,32),0,.65,(255,255,255),1,cv2.LINE_AA)
    writer.write(frame); n+=1
cap.release(); writer.release(); print(n,fps)
