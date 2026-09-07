import json
import networkx as nx
import matplotlib.pyplot as plt
from pathlib import Path


def load_graph(json_path, verbose=True):
    """
    Load graph from new JSON format with 'graph' structure.
    Supports both old format (data array) and new format (graph object).
    """
    with open(json_path, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
    
    G = nx.Graph()
    nodes = {}
    
    # Detect format
    if 'graph' in data:
        # NEW FORMAT
        graph_data = data['graph']
        
        # Parse nodes
        for node_id, node_info in graph_data['nodes'].items():
            label = node_info.get('label', node_id)
            meta = node_info.get('metadata', {})
            pos = meta.get('position', {})
            x = pos.get('x', 0)
            y = pos.get('y', 0)
            
            nodes[node_id] = {
                'x': x,
                'y': y,
                'name': label,
                'type': meta.get('type', 'unknown'),
                'floor': meta.get('floor', 0)
            }
            G.add_node(node_id, pos=(x, y), label=label)
        
        # Parse edges
        for edge in graph_data.get('edges', []):
            source = edge['source']
            target = edge['target']
            meta = edge.get('metadata', {})
            distance = meta.get('distance', 1)
            
            # Avoid duplicate edges
            if not G.has_edge(source, target):
                G.add_edge(source, target, weight=distance)
                if verbose:
                    print(f"Added edge {nodes[source]['name']} <-> {nodes[target]['name']}, dist: {distance:.2f}")
    
    elif 'data' in data:
        # OLD FORMAT (legacy support)
        for item in data['data']:
            node_id = item['number']
            x = float(item['x'])
            y = float(item['y'])
            name = item.get('name', f"Node {node_id}")
            
            nodes[node_id] = {
                'x': x,
                'y': y,
                'name': name,
                'type': item.get('type'),
                'floor': item.get('floor')
            }
            G.add_node(node_id, pos=(x, y), label=name)
        
        for item in data['data']:
            u = item['number']
            links = item.get('link', [])
            for link in links:
                v = link['number']
                if not G.has_edge(u, v) and v in nodes:
                    import math
                    p1 = nodes[u]
                    p2 = nodes[v]
                    dist = math.sqrt((p1['x'] - p2['x'])**2 + (p1['y'] - p2['y'])**2)
                    G.add_edge(u, v, weight=dist)
                    if verbose:
                        print(f"Added edge {u} <-> {v}, dist: {dist:.2f}")
    else:
        raise ValueError("Unknown JSON format")

    return G, nodes


def load_building_config(config_path='config/building.json'):
    """
    Load the multi-floor building configuration.
    """
    config_file = Path(config_path)
    with open(config_file, 'r', encoding='utf-8-sig') as f:
        config = json.load(f)

    config['_config_path'] = str(config_file)
    return config


def get_enabled_floors(building_config):
    """
    Return enabled floor entries sorted by their floor order.
    """
    floors = [floor for floor in building_config.get('floors', []) if floor.get('enabled', True)]
    floors.sort(key=lambda floor: floor.get('order', 0))
    return floors


def _resolve_config_base_dir(config_path):
    config_file = Path(config_path)
    if config_file.parent.name == 'config':
        return config_file.parent.parent
    return config_file.parent


def _make_global_node_id(floor_id, local_node_id):
    return f"{floor_id}:{local_node_id}"


def _resolve_node_reference(node_data, node_ref):
    """
    Resolve a node either by explicit node_id or by exact label.
    """
    if not node_ref:
        return None

    node_id = node_ref.get('node_id')
    if node_id in node_data:
        return node_id

    node_label = node_ref.get('node_label')
    if node_label is None:
        return None

    for local_id, data in node_data.items():
        if data.get('name') == node_label:
            return local_id

    return None


def load_building_graph(config_path='config/building.json', verbose=False):
    """
    Merge all enabled floor graphs into a single building-level graph.

    Returns:
        building_graph: graph with global node ids like "floor5:node-123"
        building_nodes: metadata keyed by global node id
        floor_context: per-floor loaded graph and nodes for downstream use
    """
    building_config = load_building_config(config_path)
    config_file = Path(building_config['_config_path'])
    base_dir = _resolve_config_base_dir(config_file)

    building_graph = nx.Graph()
    building_nodes = {}
    floor_context = {}

    for floor in get_enabled_floors(building_config):
        floor_id = floor['id']
        graph_path = base_dir / floor['graph_json']

        if not graph_path.exists():
            if verbose:
                print(f"Warning: graph file missing for {floor_id}: {graph_path}")
            continue

        floor_graph, floor_nodes = load_graph(graph_path, verbose=False)
        floor_context[floor_id] = {
            'config': floor,
            'graph': floor_graph,
            'nodes': floor_nodes
        }

        for local_node_id, node_info in floor_nodes.items():
            global_node_id = _make_global_node_id(floor_id, local_node_id)
            merged_node = dict(node_info)
            merged_node['floor_id'] = floor_id
            merged_node['local_node_id'] = local_node_id
            merged_node['global_node_id'] = global_node_id
            building_nodes[global_node_id] = merged_node

            building_graph.add_node(
                global_node_id,
                pos=(node_info['x'], node_info['y']),
                label=node_info['name'],
                floor_id=floor_id,
                local_node_id=local_node_id
            )

        for source, target, edge_data in floor_graph.edges(data=True):
            global_source = _make_global_node_id(floor_id, source)
            global_target = _make_global_node_id(floor_id, target)
            weight = edge_data.get('weight', 1)
            building_graph.add_edge(
                global_source,
                global_target,
                weight=weight,
                edge_type='intra_floor',
                floor_id=floor_id
            )

    for link in building_config.get('connector_links', []):
        if link.get('enabled', True) is False:
            continue

        from_ref = link.get('from', {})
        to_ref = link.get('to', {})
        from_floor = from_ref.get('floor_id')
        to_floor = to_ref.get('floor_id')

        if from_floor not in floor_context or to_floor not in floor_context:
            if verbose:
                print(f"Skipping connector {link.get('id')}: floor not loaded")
            continue

        from_local = _resolve_node_reference(floor_context[from_floor]['nodes'], from_ref)
        to_local = _resolve_node_reference(floor_context[to_floor]['nodes'], to_ref)

        if from_local is None or to_local is None:
            if verbose:
                print(f"Skipping connector {link.get('id')}: node label/id not found")
            continue

        global_from = _make_global_node_id(from_floor, from_local)
        global_to = _make_global_node_id(to_floor, to_local)

        building_graph.add_edge(
            global_from,
            global_to,
            weight=link.get('weight', 1),
            edge_type=link.get('type', 'connector'),
            connector_id=link.get('id'),
            connector_group=link.get('group_id'),
            accessible=link.get('accessible', True)
        )

        if verbose:
            print(f"Added connector {link.get('id')}: {global_from} <-> {global_to}")

    return building_graph, building_nodes, floor_context

def visualize_graph(G, nodes_data, output_file='topology_with_map.png', map_file='map/floor5.jpg', scale=1.0):
    """
    Visualize graph on map image.
    Scale=1.0 for new format (coords are already in pixels).
    """
    pos = {n: (d['x'] * scale, d['y'] * scale) for n, d in nodes_data.items()}
    
    plt.figure(figsize=(10, 10))
    
    try:
        img = plt.imread(map_file)
        plt.imshow(img)
    except FileNotFoundError:
        print(f"Warning: Map file {map_file} not found. Plotting without background.")
    
    # Draw nodes
    nx.draw_networkx_nodes(G, pos, node_size=150, node_color='red', alpha=0.7)
    
    # Draw edges
    nx.draw_networkx_edges(G, pos, edge_color='blue', width=2, alpha=0.5)
    
    # Draw labels
    label_pos = {k: (v[0], v[1] - 10) for k, v in pos.items()} 
    labels = {n: nodes_data[n]['name'] for n in nodes_data}
    nx.draw_networkx_labels(G, label_pos, labels=labels, font_size=6, font_family='sans-serif', font_color='black')

    plt.title("Topological Map Overlay - Floor 5")
    plt.axis('off')
    
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Graph visualization saved to {output_file}")
    plt.close()

if __name__ == "__main__":
    json_file = 'json_map/floor5.json'
    map_file = 'map/floor5.jpg'
    try:
        graph, node_data = load_graph(json_file)
        print(f"Successfully loaded graph with {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges.")
        # New format uses pixel coordinates directly, scale=1
        visualize_graph(graph, node_data, map_file=map_file, scale=1.0)
    except Exception as e:
        print(f"An error occurred: {e}")
