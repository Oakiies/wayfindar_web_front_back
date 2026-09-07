"""Route planning and destination resolution."""
import math
from app.services.state import state
import app.core.navigation as nav


def normalize_place_name(name: str) -> str:
    # Room labels are user input and may differ in case from the graph
    # (e.g. ``m21`` vs ``M21_A``).  Keep the suffix folding below, but make
    # the canonical form case-insensitive so aliases resolve consistently.
    value = str(name or '').strip().casefold()
    if '_' in value:
        base, suffix = value.rsplit('_', 1)
        if base and len(suffix) == 1 and suffix.isalpha():
            return base
    return value


def _destination_candidates(node_data: dict, destination_room: str, floor_id: str | None = None) -> list:
    if not destination_room:
        return []

    query = str(destination_room).strip()
    query_norm = normalize_place_name(query)
    candidates = []

    for node_id, data in node_data.items():
        node_floor = data.get('floor_id', data.get('floor'))
        if floor_id is not None and node_floor != floor_id:
            continue
        node_name = str(data.get('name', '')).strip()
        if not node_name:
            continue
        node_norm = normalize_place_name(node_name)
        if node_name == query or node_norm == query_norm:
            candidates.append(node_id)

    if candidates:
        return candidates

    # Partial-match fallback
    for node_id, data in node_data.items():
        node_floor = data.get('floor_id', data.get('floor'))
        if floor_id is not None and node_floor != floor_id:
            continue
        node_name = str(data.get('name', '')).strip()
        if query and query in node_name:
            candidates.append(node_id)

    return candidates


def _route_total_cost(graph_obj, node_data: dict, user_x: float, user_y: float, start_node, path: list) -> float:
    if start_node is None or not path:
        return float('inf')
    start_data = node_data.get(start_node)
    if not start_data:
        return float('inf')
    user_to_start = math.hypot(float(user_x) - float(start_data['x']), float(user_y) - float(start_data['y']))
    path_cost = 0.0
    for src, dst in zip(path, path[1:]):
        if graph_obj.has_edge(src, dst):
            path_cost += float(graph_obj[src][dst].get('weight', 1.0))
        else:
            src_data = node_data.get(src)
            dst_data = node_data.get(dst)
            if src_data and dst_data:
                path_cost += math.hypot(float(dst_data['x']) - float(src_data['x']), float(dst_data['y']) - float(src_data['y']))
    return user_to_start + path_cost


def resolve_destination_node(destination_room: str, destination_floor: str | None = None, current_floor: str | None = None):
    """Return (node_id, node_data) for the best match, or (None, None)."""
    target_floor = destination_floor or current_floor

    if state.building_nodes:
        candidates = _destination_candidates(state.building_nodes, destination_room, floor_id=target_floor)
        if candidates:
            dest_node = candidates[0]
            return dest_node, state.building_nodes[dest_node]

    if state.nodes:
        candidates = _destination_candidates(state.nodes, destination_room)
        if candidates:
            dest_node = candidates[0]
            return dest_node, state.nodes[dest_node]

    return None, None


def compute_navigation_route(start_floor: str | None, x: float, y: float, destination_room: str, destination_floor: str | None = None) -> dict | None:
    """Compute route from (x, y) on start_floor to destination_room. Returns route dict or None."""
    active_floor = start_floor or state.current_floor_id or state.default_floor_id

    if state.building_graph is not None and state.building_nodes:
        start_floor_nodes = nav.get_nodes_for_floor(state.building_nodes, active_floor)
        target_floor = destination_floor or active_floor
        dest_candidates = _destination_candidates(state.building_nodes, destination_room, floor_id=target_floor)

        best_route = None
        for dest_node in dest_candidates:
            start_node, full_path = nav.find_best_start_node(
                state.building_graph, start_floor_nodes, x, y, dest_node, top_k=3
            )
            if not full_path:
                continue
            total_cost = _route_total_cost(state.building_graph, state.building_nodes, x, y, start_node, full_path)
            if best_route is None or total_cost < best_route['cost']:
                best_route = {
                    'cost': total_cost,
                    'start_node': start_node,
                    'destination_node': dest_node,
                    'full_path': full_path
                }

        if start_floor_nodes and best_route is not None:
            start_node = best_route['start_node']
            dest_node = best_route['destination_node']
            full_path = best_route['full_path']

            segments = nav.split_path_by_floor(state.building_nodes, full_path)
            current_segment = next((seg for seg in segments if seg['floor_id'] == active_floor), None)
            path_coords = current_segment['coords'] if current_segment else []

            next_transition = None
            for index, segment in enumerate(segments):
                if segment['floor_id'] == active_floor and index + 1 < len(segments):
                    next_transition = {
                        'from_floor': active_floor,
                        'to_floor': segments[index + 1]['floor_id'],
                        'from_node': segment['path'][-1],
                        'to_node': segments[index + 1]['path'][0]
                    }
                    break

            return {
                'start_node': start_node,
                'destination_node': dest_node,
                'path_coords': path_coords,
                'full_path': full_path,
                'segments': segments,
                'next_transition': next_transition
            }

    if state.graph is None or state.nodes is None:
        return None

    dest_candidates = _destination_candidates(state.nodes, destination_room)
    if not dest_candidates:
        return None

    best_route = None
    for dest_node in dest_candidates:
        start_node, best_path = nav.find_best_start_node(state.graph, state.nodes, x, y, dest_node, top_k=3)
        if not best_path:
            continue
        total_cost = _route_total_cost(state.graph, state.nodes, x, y, start_node, best_path)
        if best_route is None or total_cost < best_route['cost']:
            best_route = {
                'cost': total_cost,
                'start_node': start_node,
                'destination_node': dest_node,
                'best_path': best_path
            }

    if best_route is None:
        return None

    start_node = best_route['start_node']
    dest_node = best_route['destination_node']
    best_path = best_route['best_path']
    path_coords = nav.get_path_coordinates(state.nodes, best_path)
    return {
        'start_node': start_node,
        'destination_node': dest_node,
        'path_coords': path_coords,
        'full_path': best_path,
        'segments': [{'floor_id': active_floor, 'path': best_path, 'coords': path_coords}],
        'next_transition': None
    }
