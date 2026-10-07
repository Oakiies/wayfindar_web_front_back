"""Produce PNG visual evidence directly from final encoded deliverables."""
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parent

def grab(cap,seconds,size):
    cap.set(cv2.CAP_PROP_POS_MSEC,seconds*1000)
    ok,frame=cap.read()
    if not ok: raise RuntimeError(f'Cannot decode {seconds}s')
    return cv2.resize(frame,size,interpolation=cv2.INTER_AREA)

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=ROOT/'out')
    args=ap.parse_args()
    cap=cv2.VideoCapture(str(args.out.parent/'IMG_1895_comparison_0_60.mp4'))
    images=[grab(cap,float(t),(960,270)) for t in range(0,40,2)]
    cap.release()
    for i in range(0,len(images),5):
        cv2.imwrite(str(args.out/f'contact_sheet_{i//5+1}.png'),np.vstack(images[i:i+5]))
    cap=cv2.VideoCapture(str(args.out.parent/'IMG_1895_AR_0_60.mp4'))
    images=[grab(cap,float(t),(640,360)) for t in np.arange(12.6,13.7,.15)]
    cap.release()
    cv2.imwrite(str(args.out/'final_temporal_check.png'),np.vstack([np.hstack(images[i:i+2]) for i in range(0,8,2)]))

if __name__=='__main__': main()
