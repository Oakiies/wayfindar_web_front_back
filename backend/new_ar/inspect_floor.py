"""Collect independent visible map landmarks for floor-plane inspection."""
from estimate_and_track import *

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=ROOT/'out')
    args=ap.parse_args()
    out=args.out
    config=json.loads((out/'camera_calibration.json').read_text())
    localizer=Localizer(floor_id='floor1',data_dir=DEFAULT_DATA,
        floor_plan_path=DEFAULT_MAP,json_map_path=DEFAULT_GRAPH,
        matching_mode='superpoint',retrieval_mode='megaloc')
    accelerate_localizer(localizer)
    localizer.camera_self_calibrator.close()
    localizer.K=np.array(config['K'])
    size=tuple(config['image_size'])
    cap=cv2.VideoCapture(config['video'])
    sheets=[]
    for seconds in [23,24,30,40,50,59]:
        cap.set(cv2.CAP_PROP_POS_MSEC,seconds*1000)
        ok,frame=cap.read()
        assert ok
        _,direct,_=evaluate_target(localizer,frame,size,20)
        pose=solve_pose(localizer,direct['points_2d'],direct['points_3d'])
        if pose is None or not pose['accepted']: continue
        idx=pose['inliers']
        p2,p3=direct['points_2d'][idx],direct['points_3d'][idx]
        np.savez(out/f'landmarks_{seconds}.npz',p2=p2,p3=p3,R=pose['R'],t=pose['t'])
        normal=np.array(localizer.floor_config['floor_normal'])
        C=-pose['R'].T@pose['t']
        im=cv2.resize(frame,(960,540))
        for i,(xy,xyz) in enumerate(zip(p2,p3)):
            height=float((xyz-C)@normal)
            color=(0,255,0) if height>.05 else (0,100,255)
            uv=tuple((xy/2).astype(int))
            cv2.circle(im,uv,4,color,-1)
            if xy[1]>500:
                cv2.putText(im,f'{i}:{height:.2f}',uv,0,.35,color,1)
        cv2.putText(im,str(seconds),(12,30),0,1,(0,255,255),2)
        cv2.imwrite(str(out/f'landmarks_{seconds}.jpg'),im)
        sheets.append(im)
        print(seconds,'floor heights',[(i,round(float((p-C)@normal),3)) for i,p in enumerate(p3) if p2[i,1]>600],flush=True)
    cap.release()

if __name__=='__main__': main()
