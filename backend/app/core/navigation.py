import networkx as nx
import math
from app.core.topology import load_graph, load_building_graph

def find_nearest_node(graph, node_data, x, y):
    """
    Find the node closest to the given (x, y) coordinates.
    """
    min_dist = float('inf')
    nearest_node = None
    
    for node_id, data in node_data.items():
        node_x = data['x']
        node_y = data['y']
        dist = math.sqrt((x - node_x)**2 + (y - node_y)**2)
        
        if dist < min_dist:
            min_dist = dist
            nearest_node = node_id
            
    return nearest_node, min_dist

def find_path(graph, start_node, end_node):
    """
    Find shortest path using A* algorithm.
    """
    try:
        path = nx.astar_path(graph, start_node, end_node, weight='weight')
        return path
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

def find_best_start_node(graph, node_data, x, y, dest_node, top_k=3):
    """
    Find the best starting node by minimizing:
    Cost = Distance(User, Node) + ShortestPath(Node, Destination)
    
    Checks the top_k geometrically nearest nodes.
    """
    # 1. Get all nodes with distances
    candidates = []
    for node_id, data in node_data.items():
        node_x = data['x']
        node_y = data['y']
        dist = math.sqrt((x - node_x)**2 + (y - node_y)**2)
        candidates.append((node_id, dist))
    
    # 2. Sort by distance and take top K
    candidates.sort(key=lambda x: x[1])
    top_candidates = candidates[:top_k]
    
    best_node = None
    min_total_cost = float('inf')
    best_path = None
    
    # 3. Evaluate total cost for each candidate
    for node_id, user_dist in top_candidates:
        try:
            # Get path length from this node to destination
            path_len = nx.shortest_path_length(graph, source=node_id, target=dest_node, weight='weight')
            
            # Total cost
            total_cost = user_dist + path_len
            
            if total_cost < min_total_cost:
                min_total_cost = total_cost
                best_node = node_id
                # Pre-calculate path to avoid re-doing it later
                best_path = nx.shortest_path(graph, source=node_id, target=dest_node, weight='weight')
                
        except nx.NetworkXNoPath:
            continue
            
    return best_node, best_path

def get_node_by_name(node_data, name_query, floor_id=None, exact=False):
    """
    Search for a node by its name.
    By default this preserves old behavior and uses partial matching.
    """
    for node_id, data in node_data.items():
        if floor_id is not None and data.get('floor_id', data.get('floor')) != floor_id:
            continue

        node_name = data['name']
        matched = node_name == name_query if exact else name_query in node_name

        if matched:
            return node_id
    return None


def get_nodes_by_type(node_data, node_type, floor_id=None):
    """
    Filter nodes by type and optional floor.
    """
    matched = {}
    for node_id, data in node_data.items():
        if floor_id is not None and data.get('floor_id', data.get('floor')) != floor_id:
            continue
        if data.get('type') == node_type:
            matched[node_id] = data
    return matched


def get_nodes_for_floor(node_data, floor_id):
    """
    Return only nodes that belong to a given floor.
    """
    return {
        node_id: data
        for node_id, data in node_data.items()
        if data.get('floor_id', data.get('floor')) == floor_id
    }

def get_path_coordinates(node_data, path, scale=1.0):
    """
    Convert a list of node IDs to (x, y) coordinates for plotting.
    """
    coords = []
    for node_id in path:
        data = node_data[node_id]
        coords.append((data['x'] * scale, data['y'] * scale))
    return coords


def split_path_by_floor(node_data, path, scale=1.0):
    """
    Split a building-level path into floor-specific segments.
    """
    if not path:
        return []

    segments = []
    current_floor = None
    current_nodes = []

    for node_id in path:
        node_info = node_data[node_id]
        node_floor = node_info.get('floor_id', node_info.get('floor'))

        if current_floor is None:
            current_floor = node_floor
            current_nodes = [node_id]
            continue

        if node_floor == current_floor:
            current_nodes.append(node_id)
            continue

        segments.append({
            'floor_id': current_floor,
            'path': list(current_nodes),
            'coords': get_path_coordinates(node_data, current_nodes, scale=scale)
        })

        current_floor = node_floor
        current_nodes = [node_id]

    if current_nodes:
        segments.append({
            'floor_id': current_floor,
            'path': list(current_nodes),
            'coords': get_path_coordinates(node_data, current_nodes, scale=scale)
        })

    return segments


def find_multifloor_path(config_path, start_floor, start_x, start_y, destination_name, destination_floor=None, top_k=3):
    """
    Load the building graph from config and compute a path across floors.

    Returns:
        dict with graph, nodes, path, segments, start_node, destination_node
        or None if no valid route can be found.
    """
    graph, node_data, _ = load_building_graph(config_path)

    start_floor_nodes = get_nodes_for_floor(node_data, start_floor)
    if not start_floor_nodes:
        return None

    target_floor = destination_floor
    if target_floor is None:
        destination_node = get_node_by_name(node_data, destination_name)
    else:
        destination_node = get_node_by_name(node_data, destination_name, floor_id=target_floor)

    if destination_node is None:
        return None

    start_node, best_path = find_best_start_node(
        graph,
        start_floor_nodes,
        start_x,
        start_y,
        destination_node,
        top_k=top_k
    )

    if not best_path:
        return None

    return {
        'graph': graph,
        'nodes': node_data,
        'start_node': start_node,
        'destination_node': destination_node,
        'path': best_path,
        'segments': split_path_by_floor(node_data, best_path)
    }

def project_point_on_segment(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    
    # Vector AB
    dx = bx - ax
    dy = by - ay
    
    if dx == 0 and dy == 0:
        return a
        
    # Vector AP
    apx = px - ax
    apy = py - ay
    
    t = (apx * dx + apy * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    
    return (ax + t * dx, ay + t * dy)

def lookahead_segment(x, y, path_coords, lookahead=90.0):
    """Pure-pursuit aim segment for a stable travel bearing.

    Returns ``(from_point, aim_point)`` where:
      • ``from_point`` is (x, y) projected onto the nearest point of the route,
      • ``aim_point`` is `lookahead` pixels *forward* of that projection.

    The travel bearing should be measured ``from_point → aim_point`` (the path
    *tangent*), NOT ``user → aim_point``. Using the projection as the origin
    cancels the user's lateral offset from the corridor centreline, so the AR
    ribbon points straight whenever the user faces along the corridor — no
    matter which side of it they stand on. Walking forward of the projection
    also stops the bearing from jittering on top of a node or flipping backward
    when the start node is slightly behind the user.

    Falls back to the destination (last coord) when the remaining path is
    shorter than `lookahead`. Returns ``None`` for an empty path.
    """
    if not path_coords:
        return None
    if len(path_coords) == 1:
        return path_coords[0], path_coords[0]

    # 1. Find the nearest segment and the projection of (x, y) onto it.
    min_dist = float('inf')
    best_i = 0
    best_proj = path_coords[0]
    for i in range(len(path_coords) - 1):
        proj = project_point_on_segment((x, y), path_coords[i], path_coords[i + 1])
        dist = math.hypot(x - proj[0], y - proj[1])
        if dist < min_dist:
            min_dist = dist
            best_i = i
            best_proj = proj

    # 2. Walk forward from the projection until we have travelled `lookahead`.
    remaining = float(lookahead)
    cur = best_proj
    aim = path_coords[-1]
    for i in range(best_i, len(path_coords) - 1):
        nxt = path_coords[i + 1]
        seg_len = math.hypot(nxt[0] - cur[0], nxt[1] - cur[1])
        if seg_len >= remaining:
            t = remaining / seg_len if seg_len > 0 else 0.0
            aim = (cur[0] + t * (nxt[0] - cur[0]), cur[1] + t * (nxt[1] - cur[1]))
            break
        remaining -= seg_len
        cur = nxt

    return best_proj, aim


def _nearest_on_path(x, y, path_coords):
    """Return (segment_index, projection_point) of (x, y) onto the polyline."""
    min_dist = float('inf')
    best_i = 0
    best_proj = path_coords[0]
    for i in range(len(path_coords) - 1):
        proj = project_point_on_segment((x, y), path_coords[i], path_coords[i + 1])
        dist = math.hypot(x - proj[0], y - proj[1])
        if dist < min_dist:
            min_dist = dist
            best_i = i
            best_proj = proj
    return best_i, best_proj


def _forward_point(path_coords, start_i, start_pt, dist):
    """Walk `dist` px forward along the polyline from start_pt (on segment start_i)."""
    remaining = float(dist)
    cur = start_pt
    for i in range(start_i, len(path_coords) - 1):
        nxt = path_coords[i + 1]
        seg_len = math.hypot(nxt[0] - cur[0], nxt[1] - cur[1])
        if seg_len >= remaining:
            t = remaining / seg_len if seg_len > 0 else 0.0
            return (cur[0] + t * (nxt[0] - cur[0]), cur[1] + t * (nxt[1] - cur[1]))
        remaining -= seg_len
        cur = nxt
    return path_coords[-1]


def _strip_start_stub(path_coords, stub_len=16.0, min_angle=40.0):
    """Drop a short leading segment that bends sharply into the route.

    find_best_start_node can pick a room/access node *beside* the corridor as
    the route's first node; the tiny stub from it into the corridor then reads as
    a fake 90° turn while the user is simply walking straight. Stripping it lets
    "walking straight" correctly show no turn. Only removes a first segment that
    is both SHORT and bends by >= `min_angle` (a real corridor segment is longer
    or straight, so it is kept).
    """
    if not path_coords or len(path_coords) < 3:
        return path_coords
    p0, p1, p2 = path_coords[0], path_coords[1], path_coords[2]
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) >= stub_len:
        return path_coords
    a1 = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
    a2 = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
    d = ((a2 - a1 + 180.0) % 360.0) - 180.0
    return path_coords[1:] if abs(d) >= min_angle else path_coords


def next_turn_info(x, y, path_coords, min_angle=30.0):
    """Find the next real corner ahead of the user and how far it is.

    Walks the route from the user's on-path projection and returns the first
    vertex whose heading change exceeds `min_angle`:
        {'dir': -1 left | +1 right, 'dist': px, 'angle': deg, 'at': [px,py]}
    or None if there's no turn ahead.

    `dist` is the STRAIGHT-LINE distance from the user to the corner vertex — not
    the path arc length. find_best_start_node can place the route's first node
    ahead of the user, which makes arc length underestimate how far the corner
    really is (the turn then fires too early and inconsistently). Straight-line
    distance is measured from the user's actual position, so the turn fires at a
    consistent real distance before every corner.
    """
    if not path_coords or len(path_coords) < 3:
        return None
    path_coords = _strip_start_stub(path_coords)
    if len(path_coords) < 3:
        return None
    best_i, proj = _nearest_on_path(x, y, path_coords)
    pts = [(float(proj[0]), float(proj[1]))] + [(float(px), float(py)) for px, py in path_coords[best_i + 1:]]
    for k in range(1, len(pts) - 1):
        ax, ay = pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]
        bx, by = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
        if (ax == 0 and ay == 0) or (bx == 0 and by == 0):
            continue
        a1 = math.degrees(math.atan2(ay, ax))
        a2 = math.degrees(math.atan2(by, bx))
        d = ((a2 - a1 + 180.0) % 360.0) - 180.0
        if abs(d) >= min_angle:
            dist = math.hypot(x - pts[k][0], y - pts[k][1])
            return {'dir': 1 if d > 0 else -1, 'dist': float(dist), 'angle': float(d),
                    'at': [float(pts[k][0]), float(pts[k][1])]}
    return None


def path_points_ahead(x, y, path_coords, step=15.0, maxf=180.0):
    """Resample the route ahead of the user into evenly spaced floor-plan points
    (px), starting at the on-path projection and walking `step` px forward up to
    `maxf`. Used to build the true-AR ribbon centreline before projecting to the
    camera image.
    """
    if not path_coords:
        return []
    if len(path_coords) == 1:
        return [(float(path_coords[0][0]), float(path_coords[0][1]))]
    best_i, proj = _nearest_on_path(x, y, path_coords)
    end = path_coords[-1]
    pts, d = [], 0.0
    while d <= maxf:
        p = _forward_point(path_coords, best_i, proj, d)
        pts.append((float(p[0]), float(p[1])))
        if p[0] == end[0] and p[1] == end[1]:
            break
        d += step
    return pts


def simplify_collinear(path_coords, eps=6.0):
    """Drop interior vertices that sit within `eps` px of the straight line
    between their neighbours. Removes small surveying jogs / door-access offsets
    that would otherwise render as spurious little kinks, while keeping real
    corners (whose vertices deviate far more than `eps`).
    """
    if not path_coords or len(path_coords) <= 2:
        return list(path_coords) if path_coords else []
    out = [path_coords[0]]
    for i in range(1, len(path_coords) - 1):
        a = out[-1]
        b = path_coords[i]
        c = path_coords[i + 1]
        proj = project_point_on_segment(b, a, c)
        if math.hypot(b[0] - proj[0], b[1] - proj[1]) >= eps:
            out.append(b)
    out.append(path_coords[-1])
    return out


def local_path_ahead(x, y, path_coords, max_forward=190.0, step=14.0, tangent_base=26.0):
    """Path geometry ahead, expressed in the user's local frame, for the AR
    ribbon to render the *actual route shape* (not a single steer angle).

    Returns a list of ``[forward, lateral]`` points (px) relative to the user's
    on-path projection, where ``forward`` runs along the immediate corridor
    tangent and ``lateral`` is the signed sideways offset (>0 = user's right,
    <0 = left). A straight corridor yields lateral ≈ 0 at every depth (the
    ribbon draws perfectly straight); a corner shows up as lateral growing at
    the depth where the corner actually is — so the ribbon bends *at the corner*
    instead of leaning the whole road early.

    The frame origin is the on-path projection (not the raw user position), so
    lateral position jitter does not wobble the ribbon.
    """
    if not path_coords or len(path_coords) < 2:
        return []
    path_coords = simplify_collinear(_strip_start_stub(path_coords))
    best_i, proj = _nearest_on_path(x, y, path_coords)
    base = _forward_point(path_coords, best_i, proj, tangent_base)
    fx, fy = base[0] - proj[0], base[1] - proj[1]
    norm = math.hypot(fx, fy)
    if norm < 1e-6:
        return []
    fx, fy = fx / norm, fy / norm
    rx, ry = -fy, fx  # right-perpendicular in image (y-down) frame

    out = []
    d = 0.0
    end = path_coords[-1]
    while d <= max_forward:
        p = _forward_point(path_coords, best_i, proj, d)
        vx, vy = p[0] - proj[0], p[1] - proj[1]
        forward = vx * fx + vy * fy
        lateral = vx * rx + vy * ry
        out.append([round(forward, 1), round(lateral, 1)])
        if p[0] == end[0] and p[1] == end[1]:
            break
        d += step
    return out


def path_turn_angle(x, y, path_coords, near=12.0, far=40.0):
    """Signed turn (deg) the path makes ahead of the user — pure geometry.

    Compares the corridor direction at the user's feet (projection → `near` px
    ahead) with the direction `far` px ahead. The result is independent of the
    noisy PnP yaw, so the AR ribbon reads *straight on a straight corridor* and
    only bends when the route itself bends.

      0  ⇒ straight ahead
      >0 ⇒ route bends to the user's right
      <0 ⇒ route bends to the user's left

    Frame: image pixels (0=East, clockwise positive) — same as the map and the
    `calculate_direction` heading, so the sign matches a first-person view.
    """
    if not path_coords or len(path_coords) < 2:
        return 0.0

    path_coords = simplify_collinear(_strip_start_stub(path_coords))
    best_i, proj = _nearest_on_path(x, y, path_coords)
    p_near = _forward_point(path_coords, best_i, proj, near)
    p_far  = _forward_point(path_coords, best_i, proj, far)

    # Degenerate when the remaining path is too short to define a direction.
    if (p_near[0] == proj[0] and p_near[1] == proj[1]):
        return 0.0
    if (p_far[0] == p_near[0] and p_far[1] == p_near[1]):
        return 0.0

    near_dir = math.degrees(math.atan2(p_near[1] - proj[1],   p_near[0] - proj[0]))
    far_dir  = math.degrees(math.atan2(p_far[1]  - p_near[1], p_far[0]  - p_near[0]))
    turn = ((far_dir - near_dir + 180.0) % 360.0) - 180.0
    return float(turn)


def remaining_path_length(x, y, path_coords):
    """Distance (px) from the user's projection to the end of the route."""
    if not path_coords:
        return 0.0
    if len(path_coords) == 1:
        return math.hypot(x - path_coords[0][0], y - path_coords[0][1])
    best_i, proj = _nearest_on_path(x, y, path_coords)
    total = math.hypot(path_coords[best_i + 1][0] - proj[0],
                       path_coords[best_i + 1][1] - proj[1])
    for i in range(best_i + 1, len(path_coords) - 1):
        total += math.hypot(path_coords[i + 1][0] - path_coords[i][0],
                            path_coords[i + 1][1] - path_coords[i][1])
    return float(total)


def snap_to_path(x, y, path_coords):
    """
    Project (x, y) strictly onto the nearest segment of the navigation path 
    to prevent wandering into walls or outside corridors.
    """
    if not path_coords:
        return x, y
        
    if len(path_coords) == 1:
        return path_coords[0][0], path_coords[0][1]
        
    min_dist = float('inf')
    best_proj = (x, y)
    
    # Usually the user is at the start of the path, so checking the first 3 segments is enough
    # and prevents snapping to a different part of the map if the path loops around.
    segments_to_check = min(3, len(path_coords) - 1)
    
    for i in range(segments_to_check):
        a = path_coords[i]
        b = path_coords[i+1]
        proj = project_point_on_segment((x, y), a, b)
        
        dist = math.sqrt((x - proj[0])**2 + (y - proj[1])**2)
        if dist < min_dist:
            min_dist = dist
            best_proj = proj
            
    return float(best_proj[0]), float(best_proj[1])

if __name__ == "__main__":
    # Test block
    json_path = 'json_map/floor5.json'
    G, nodes = load_graph(json_path)
    
    # Test 1: Nearest Node
    test_x, test_y = 250, 300
    nearest, dist = find_nearest_node(G, nodes, test_x, test_y)
    print(f"Nearest node to ({test_x}, {test_y}) is {nearest} ({nodes[nearest]['name']}), dist: {dist:.2f}")
    
    # Test 2: Pathfinding
    start = nearest
    end = get_node_by_name(nodes, "509")
    
    if end:
        print(f"Calculating path from {nodes[start]['name']} to {nodes[end]['name']}...")
        path = find_path(G, start, end)
        if path:
            print(f"Path found: {[nodes[n]['name'] for n in path]}")
            coords = get_path_coordinates(nodes, path)
            print(f"Path coords: {coords}")
        else:
            print("No path found.")
    else:
        print("Target node not found.")
