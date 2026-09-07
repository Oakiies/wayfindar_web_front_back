from pathlib import Path
import threading
from app.services.state import state
from app.services.localizer_service import get_or_create_localizer
import app.core.topology as top
import app.config as config

# Path keys inside building.json that name a location on disk.
_FLOOR_PATH_KEYS = ('data_dir', 'graph_json', 'map_image')
_floor_switch_lock = threading.RLock()


def _absolutize_floor_paths(floor: dict) -> dict:
    """
    Anchor a floor entry's relative paths to the bundled data root.

    building.json is copied verbatim from navigate_indoor, where the server runs
    with its CWD at the repo root and 'map_data/result_floor5_6' resolves
    directly. Here the same assets live under backend/app/data/, so the prefix is
    applied at load time instead of being baked into the JSON — that keeps the
    config file a byte-identical upstream copy and re-syncing it a plain file
    copy. Absolute paths are passed through untouched.
    """
    resolved = dict(floor)
    for key in _FLOOR_PATH_KEYS:
        value = resolved.get(key)
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = config.DATA_DIR_ROOT / path
        resolved[key] = str(path)
    return resolved


def get_floor_config(floor_id: str | None = None) -> dict:
    selected_floor = floor_id or state.current_floor_id or state.default_floor_id
    if selected_floor in state.floor_configs:
        return state.floor_configs[selected_floor]
    if state.floor_configs and state.default_floor_id in state.floor_configs:
        return state.floor_configs[state.default_floor_id]
    return {
        'id': state.default_floor_id,
        'label': 'Floor 5',
        'order': 5,
        'map_image': str(config.MAP_IMAGE),
        'graph_json': str(config.JSON_MAP),
        'data_dir': str(config.LEGACY_DATA_DIR)
    }


def get_floor_map_image(floor_id: str | None = None) -> Path:
    return Path(get_floor_config(floor_id)['map_image'])


def get_keyframes_dir(floor_id: str | None = None, matching_mode: str = 'orb') -> Path:
    data_dir = Path(get_floor_config(floor_id)['data_dir'])
    if matching_mode == 'superpoint':
        candidate = data_dir / 'keyframes_superpoint'
        if candidate.exists():
            return candidate
    return data_dir / 'keyframes'


def get_floor_list() -> list:
    if state.floor_configs:
        return [
            {
                'id': floor['id'],
                'label': floor.get('label', floor['id']),
                'order': floor.get('order')
            }
            for floor in sorted(state.floor_configs.values(), key=lambda item: item.get('order', 0))
        ]
    return [{'id': state.default_floor_id, 'label': 'Floor 5', 'order': 5}]


def set_active_floor(floor_id: str | None = None) -> str:
    # Requests can arrive together during the initial camera-localization
    # retries. Serialize lazy floor/model initialization so two requests do
    # not construct duplicate GPU localizers for the same missing floor.
    with _floor_switch_lock:
        floor_config = get_floor_config(floor_id)
        selected_floor = floor_config['id']

        if selected_floor not in state.floor_graphs or selected_floor not in state.floor_nodes_map:
            state.floor_graphs[selected_floor], state.floor_nodes_map[selected_floor] = top.load_graph(
                floor_config['graph_json'], verbose=False
            )

        state.current_floor_id = selected_floor
        state.localizer = get_or_create_localizer(selected_floor)
        state.graph = state.floor_graphs[selected_floor]
        state.nodes = state.floor_nodes_map[selected_floor]
        return state.current_floor_id


def initialize_system():
    """Initialize localization and navigation systems."""
    if state.localizer is not None:
        print("System already initialized. Skipping...")
        return

    print("Initializing Indoor Navigation System...")
    print(f"[OK] Retrieval mode: {config.APP_RETRIEVAL_MODE}")

    if config.BUILDING_CONFIG_PATH.exists():
        state.building_config = top.load_building_config(str(config.BUILDING_CONFIG_PATH))
        enabled_floors = top.get_enabled_floors(state.building_config)
        state.floor_configs = {floor['id']: _absolutize_floor_paths(floor) for floor in enabled_floors}
        enabled_floors = [state.floor_configs[floor['id']] for floor in enabled_floors]

        if enabled_floors:
            requested_default = state.building_config.get('default_floor')
            state.default_floor_id = requested_default if requested_default in state.floor_configs else enabled_floors[0]['id']
            state.current_floor_id = state.default_floor_id
            state.building_graph, state.building_nodes, _ = top.load_building_graph(
                str(config.BUILDING_CONFIG_PATH), verbose=False
            )
            print(f"[OK] Building config loaded: {len(enabled_floors)} floors, {state.building_graph.number_of_nodes()} merged nodes")

    # Load the default floor first (synchronously). This also warms the shared
    # retrieval model cache so the parallel preload below reuses one model.
    set_active_floor(state.current_floor_id)
    print(f"[OK] Localizer initialized for {state.current_floor_id}")
    print(f"[OK] Topology loaded: {state.graph.number_of_nodes()} nodes, {state.graph.number_of_edges()} edges")
    if state.nodes:
        print(f"[OK] Nodes keys: {list(state.nodes.keys())[:5]}... (total {len(state.nodes)})")
    else:
        print("WARN: Nodes list is empty!")

    # Loading every floor duplicates large feature/model state and can exhaust
    # RAM on a mobile-navigation host. Load the selected floor now and the
    # remaining floors on demand when the user switches floors.
    if config.PRELOAD_ALL_FLOORS:
        _preload_remaining_floors()
    else:
        print("[INIT] Floor preload disabled; remaining floors load on demand")

    print("System ready!")


def _preload_remaining_floors() -> None:
    """Eagerly build localizers + per-floor graphs for all enabled floors except
    the (already-loaded) current one.

    Loaded sequentially, not in parallel: each floor's SuperPoint/SuperGlue
    models get moved onto CUDA during init, and doing that from several
    threads at once has been observed to deadlock partway through (stalls
    forever right after "Loaded SuperGlue model", 0% GPU util) — most likely
    concurrent CUDA context/model-transfer contention under WDDM. Loading one
    floor at a time is slower at startup but reliable.
    """
    floor_ids = [fid for fid in state.floor_configs if fid != state.current_floor_id]
    if not floor_ids:
        return

    print(f"[INIT] Preloading {len(floor_ids)} floor(s): {floor_ids}")
    for floor_id in floor_ids:
        try:
            get_or_create_localizer(floor_id)
            if floor_id not in state.floor_graphs or floor_id not in state.floor_nodes_map:
                floor_config = get_floor_config(floor_id)
                state.floor_graphs[floor_id], state.floor_nodes_map[floor_id] = top.load_graph(
                    floor_config['graph_json'], verbose=False
                )
            print(f"[OK] Floor preloaded: {floor_id}")
        except Exception as exc:
            print(f"[WARN] Floor preload failed for {floor_id}: {exc}")
