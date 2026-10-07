"""Prepare route and local ground surfaces from reference map data, never query video."""
import json
from pathlib import Path
import cv2
import numpy as np
import networkx as nx
try:
    from .world_ar import plane_intersection
except ImportError:  # direct script execution
    from world_ar import plane_intersection


def reference_ground(localizer, projector, size):
    db=localizer.database
    samples={}
    # Sample the reference walk evenly. All of these observations predate the query session.
    for i in range(0,len(db['poses']),8):
        pose=db['poses'][i]
        if pose['position'] is None: continue
        p2=np.asarray(db['keypoints'][i])
        ids=np.asarray(db['mappoint_ids'][i])
        keep=(p2[:,1]>.52*size[1])&(p2[:,0]>.15*size[0])&(p2[:,0]<.85*size[0])
        for pixel,mpid in zip(p2[keep],ids[keep]):
            point=localizer.mappoint_dict.get(int(mpid))
            if point is None: continue
            point=np.asarray(point,float)
            below=float((point-pose['position'])@projector.down)
            if not .5*projector.drop<below<2.2*projector.drop: continue
            camera=pose['R']@point+pose['t']
            if camera[2]<=0: continue
            uv=localizer.K@camera
            if np.linalg.norm(uv[:2]/uv[2]-pixel)>8: continue
            samples[int(mpid)]=point
    if len(samples)<30: raise RuntimeError('Reference map has insufficient ground evidence')
    points=np.array(list(samples.values()))
    map_xy=np.array([projector.world_to_floor_px(p) for p in points])
    return points,map_xy


def local_plane(points,xy,station,projector):
    distances=np.linalg.norm(xy-station,axis=1)
    selected=points[np.argsort(distances)[:100]]
    radius=float(np.sort(distances)[min(99,len(distances)-1)])
    rng=np.random.default_rng(27)
    best=None
    for _ in range(250):
        tri=selected[rng.choice(len(selected),3,replace=False)]
        n=np.cross(tri[1]-tri[0],tri[2]-tri[0])
        norm=np.linalg.norm(n)
        if norm<1e-8: continue
        n/=norm
        if n@projector.down<0: n=-n
        if n@projector.down<np.cos(np.radians(15)): continue
        d=float(n@tri[0])
        errors=np.abs(selected@n-d)
        inliers=errors<.012
        score=int(inliers.sum())
        if best is None or score>best[0]: best=(score,n,d,inliers)
    if best is None or best[0]<8: return None
    ground=selected[best[3]]
    _,_,vt=np.linalg.svd(ground-ground.mean(0))
    n=vt[-1]
    if n@projector.down<0: n=-n
    return n,float(n@ground.mean(0)),best[0],radius


def prepare_scene(localizer,projector,size,graph_path,start_label=None,destination_label=None):
    points,xy=reference_ground(localizer,projector,size)
    graph=json.loads(Path(graph_path).read_text(encoding='utf-8-sig'))['graph']
    nodes=graph['nodes']
    coords={k:np.array([v['metadata']['position']['x'],v['metadata']['position']['y']],float) for k,v in nodes.items()}
    graph_nx=nx.Graph()
    for edge in graph['edges']:
        a,b=edge['source'],edge['target']
        graph_nx.add_edge(a,b,weight=float(np.linalg.norm(coords[a]-coords[b])))
    labels={v['label']:k for k,v in nodes.items()}
    # Build the route from the reference graph.  The old M21 route remains the
    # default for the IMG_1895 experiment; other floors/destinations use the
    # graph's shortest path and never inspect query-video frames.
    if start_label and destination_label:
        by_label={str(v.get('label','')).strip().lower(): (k,v) for k,v in nodes.items()}
        start=by_label.get(start_label.strip().lower())
        dest=by_label.get(destination_label.strip().lower())
        if start and dest:
            import heapq
            adj={k:[] for k in nodes}
            for e in graph.get('edges',[]):
                a,b=e.get('source'),e.get('target'); w=float(e.get('metadata',{}).get('distance',1))
                if a in adj and b in adj: adj[a].append((b,w)); adj[b].append((a,w))
            q=[(0.0,start[0])]; prev={start[0]:None}; dist={start[0]:0.0}
            while q:
                dcur,u=heapq.heappop(q)
                if dcur!=dist.get(u): continue
                if u==dest[0]: break
                for v,w in adj[u]:
                    nd=dcur+w
                    if nd<dist.get(v,float('inf')): dist[v]=nd;prev[v]=u;heapq.heappush(q,(nd,v))
            ids=[];u=dest[0]
            while u is not None: ids.append(u);u=prev.get(u)
            if ids and ids[-1]==start[0]: ids=list(reversed(ids))
            waypoints=[nodes[k].get('label',k) for k in ids]
        else: waypoints=[]
    else:
        waypoints=['Intersection 7','Intersection 3','Intersection 1','Intersection 2','M23_B','M21_B']
    ids=[]
    for a,b in zip(waypoints,waypoints[1:]):
        section=nx.shortest_path(graph_nx,labels[a],labels[b],weight='weight')
        ids.extend(section if not ids else section[1:])
    route=np.array([coords[k] for k in ids])
    # Extend the first straight entrance segment to the map boundary; independent of query pose.
    direction=route[1]-route[0]
    direction/=np.linalg.norm(direction)
    route=np.vstack([route[0]-direction*100,route])
    lengths=np.linalg.norm(np.diff(route,axis=0),axis=1)
    cumulative=np.r_[0,np.cumsum(lengths)]
    anchors=[]
    for station_s in np.arange(0,cumulative[-1],11.):
        segment=min(np.searchsorted(cumulative,station_s,side='right')-1,len(lengths)-1)
        direction=(route[segment+1]-route[segment])/lengths[segment]
        station=route[segment]+direction*(station_s-cumulative[segment])
        plane=local_plane(points,xy,station,projector)
        if plane is None: continue
        n,d,support,radius=plane
        origin=plane_intersection(projector.plane_point(*station),projector.down,n,d)
        target=plane_intersection(projector.plane_point(*(station+direction)),projector.down,n,d)
        forward=target-origin
        # Local map metric under projective H, instead of its top-left matrix norm.
        upm=np.linalg.norm(forward)/.181
        forward/=np.linalg.norm(forward)
        right=np.cross(forward,n);right/=np.linalg.norm(right)
        outline=np.array([[-.3,-.2],[0,.3],[.3,-.2],[.3,-.4],[0,.1],[-.3,-.4]])
        polygon=origin+upm*(outline[:,0,None]*right+outline[:,1,None]*forward)
        anchors.append(dict(center=origin.tolist(),polygon=polygon.tolist(),map_xy=station.tolist(),
            normal=n.tolist(),offset=d,support=support,radius_px=radius,units_per_metre=float(upm),station=float(station_s)))
    if not anchors: raise RuntimeError('No reference ground anchors')
    return dict(source='reference map only; no query frames',route=route.tolist(),
        scenario=f'{start_label} to {destination_label}' if start_label else 'M21_B default scenario',
        ground_points=len(points),anchors=anchors)
