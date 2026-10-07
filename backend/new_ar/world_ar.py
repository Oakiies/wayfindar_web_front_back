"""Small, stateless world-space route renderer. All anchors are fixed in 3D."""
import cv2
import numpy as np

def fit_floor(points, reference_normal, threshold=.012):
    points=np.asarray(points,float)
    reference_normal=np.asarray(reference_normal,float)
    reference_normal/=np.linalg.norm(reference_normal)
    rng=np.random.default_rng(19)
    best=None
    for _ in range(2000):
        a,b,c=points[rng.choice(len(points),3,replace=False)]
        n=np.cross(b-a,c-a)
        if np.linalg.norm(n)<1e-8: continue
        n/=np.linalg.norm(n)
        if n@reference_normal<0: n=-n
        if n@reference_normal<np.cos(np.radians(15)): continue
        d=float(n@a)
        error=np.abs(points@n-d)
        mask=error<threshold
        key=(int(mask.sum()),-float(np.median(error[mask])))
        if best is None or key>best[0]: best=(key,mask)
    if best is None or best[1].sum()<8:
        raise ValueError('Insufficient floor-plane evidence')
    pts=points[best[1]]
    _,_,V=np.linalg.svd(pts-pts.mean(0))
    n=V[-1]
    if n@reference_normal<0: n=-n
    return n,float(n@pts.mean(0)),best[1]

def plane_intersection(point, direction, normal, offset):
    return point+direction*((offset-normal@point)/(normal@direction))

def fixed_arrows(route_world, normal, units_per_metre, spacing_m=2.0):
    route=np.asarray(route_world,float)
    lengths=np.linalg.norm(np.diff(route,axis=0),axis=1)
    cum=np.r_[0,np.cumsum(lengths)]
    result=[]
    for distance in np.arange(.8*units_per_metre,cum[-1],spacing_m*units_per_metre):
        i=min(np.searchsorted(cum,distance,side='right')-1,len(lengths)-1)
        forward=(route[i+1]-route[i])/lengths[i]
        right=np.cross(forward,normal)
        right/=np.linalg.norm(right)
        center=route[i]+forward*(distance-cum[i])
        # Orthogonal world-space basis, never perpendicular map pixels under projective H.
        outline=np.array([[-.30,-.20],[0,.30],[.30,-.20],[.30,-.40],[0,.10],[-.30,-.40]])
        polygon=center+units_per_metre*(outline[:,0,None]*right+outline[:,1,None]*forward)
        result.append(dict(center=center,polygon=polygon,station=distance,segment=i))
    return result

def clip_near(poly,near):
    output=[]
    for a,b in zip(poly,np.roll(poly,-1,axis=0)):
        ain,bin=a[2]>=near,b[2]>=near
        if ain: output.append(a)
        if ain!=bin: output.append(a+(b-a)*((near-a[2])/(b[2]-a[2])))
    return np.asarray(output)

def visible_arrows(arrows,R,t,K,units_per_metre,image_wh,max_depth_m=10):
    """Return the exact clipped world polygons accepted by the renderer."""
    R=np.asarray(R,float);t=np.asarray(t,float).reshape(3);K=np.asarray(K,float)
    w,h=image_wh
    selected=[]
    for marker in reversed(arrows):
        camera_center=R@marker['center']+t
        depth=camera_center[2]/units_per_metre
        if depth<.6 or depth>max_depth_m: continue
        camera_poly=clip_near((R@marker['polygon'].T).T+t,.25*units_per_metre)
        if len(camera_poly)<3: continue
        pixels=(K@camera_poly.T).T
        pixels=pixels[:,:2]/pixels[:,2:]
        if not np.isfinite(pixels).all() or np.abs(pixels).max()>1e5: continue
        area=abs(cv2.contourArea(pixels.astype(np.float32)))
        span=np.linalg.norm(np.ptp(pixels,axis=0))
        # Grazing views of a higher landing can collapse a whole marker to a stripe.
        if area<16 or area/max(span*span,1)<.015: continue
        if pixels[:,0].max()<0 or pixels[:,0].min()>w or pixels[:,1].max()<0 or pixels[:,1].min()>h: continue
        mask=np.zeros((h,w),np.uint8)
        cv2.fillPoly(mask,[np.round(pixels).astype(np.int32)],255)
        if cv2.countNonZero(mask)<12: continue
        alpha=.68*min(1,(depth-.6)/.7)*min(1,(max_depth_m-depth)/2)
        if alpha<=.02: continue
        world_poly=(R.T@(camera_poly-t).T).T
        selected.append(dict(polygon=world_poly,pixels=pixels,alpha=float(alpha),depth=float(depth)))
    return selected

def visible_scene(anchors,R,t,K,image_wh,max_depth_m=10):
    """Reference-ground scene selection shared by video and browser payloads."""
    camera=-np.asarray(R,float).T@np.asarray(t,float).reshape(3)
    selected=[]
    for anchor in reversed(anchors):
        scale=float(anchor['units_per_metre'])
        height=(float(anchor['offset'])-np.asarray(anchor['normal'],float)@camera)/scale
        if height<.35 or height>2.6: continue
        marker=dict(center=np.asarray(anchor['center'],float),polygon=np.asarray(anchor['polygon'],float))
        selected.extend(visible_arrows([marker],R,t,K,scale,image_wh,max_depth_m))
    return selected

def draw(frame,arrows,R,t,K,units_per_metre,max_depth_m=10):
    result=frame.copy()
    selected=visible_arrows(arrows,R,t,K,units_per_metre,(frame.shape[1],frame.shape[0]),max_depth_m)
    centers=[]
    for item in selected:
        pixels=item['pixels'];alpha=item['alpha']
        h,w=frame.shape[:2]
        mask=np.zeros((h,w),np.uint8)
        cv2.fillPoly(mask,[np.round(pixels).astype(np.int32)],255)
        layer=result.copy()
        layer[mask>0]=(255,170,0)
        result=cv2.addWeighted(layer,alpha,result,1-alpha,0)
        cv2.polylines(result,[np.round(pixels).astype(np.int32)],True,(255,240,195),1,cv2.LINE_AA)
        centers.append(pixels.mean(0).tolist())
    return result,len(selected),centers
