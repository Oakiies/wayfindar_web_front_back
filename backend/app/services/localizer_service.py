from app.services.state import state
import app.config as config


def get_or_create_localizer(floor_id: str | None = None):
    from app.core.localizer import Localizer
    from app.services.floor_service import get_floor_config

    floor_config = get_floor_config(floor_id)
    selected_floor = floor_config['id']

    if selected_floor not in state.localizers:
        # Accelerated mode runs SuperPoint+LightGlue; force the SuperPoint map so
        # LightGlue has features to match (localizer auto-falls-back to orb if a
        # floor lacks a SuperPoint map).
        matching = 'superpoint' if config.ACCEL_MODE else config.MATCHING_MODE
        state.localizers[selected_floor] = Localizer(
            floor_id=selected_floor,
            data_dir=floor_config['data_dir'],
            floor_plan_path=floor_config['map_image'],
            json_map_path=floor_config['graph_json'],
            matching_mode=matching,
            retrieval_mode=state.retrieval_mode
        )
        if config.ACCEL_MODE:
            from app.services.accel import accelerate_localizer
            accelerate_localizer(state.localizers[selected_floor])

    if selected_floor == state.current_floor_id:
        state.localizer = state.localizers[selected_floor]

    return state.localizers[selected_floor]


def get_or_create_comparison_localizer(floor_id: str | None = None):
    from app.core.localizer import Localizer
    from app.services.floor_service import get_floor_config

    floor_config = get_floor_config(floor_id)
    selected_floor = floor_config['id']

    if selected_floor not in state.comparison_localizers:
        state.comparison_localizers[selected_floor] = Localizer(
            floor_id=selected_floor,
            data_dir=floor_config['data_dir'],
            floor_plan_path=floor_config['map_image'],
            json_map_path=floor_config['graph_json'],
            matching_mode='superpoint',
            retrieval_mode=state.retrieval_mode
        )
        # In accel mode the comparison localizer runs per-frame in debug mode too;
        # accelerate it so debug view doesn't add a full SuperGlue pass (~570ms).
        if config.ACCEL_MODE:
            from app.services.accel import accelerate_localizer
            accelerate_localizer(state.comparison_localizers[selected_floor])

    return state.comparison_localizers[selected_floor]


def switch_retrieval_mode(mode: str) -> str:
    normalized = config.normalize_retrieval_mode(mode)
    if normalized == state.retrieval_mode:
        return state.retrieval_mode

    state.retrieval_mode = normalized
    state.localizers.clear()
    state.comparison_localizers.clear()
    state.localizer = None

    # Old retrieval models are no longer referenced — free them (incl. GPU mem).
    from app.core.localizer import clear_retrieval_model_cache
    clear_retrieval_model_cache()

    if state.current_floor_id:
        try:
            from app.services.floor_service import set_active_floor
            set_active_floor(state.current_floor_id)
        except Exception as exc:
            print(f"WARN: failed to reinitialize floor localizer after retrieval mode switch: {exc}")

    print(f"[OK] Retrieval mode switched to {state.retrieval_mode}")
    return state.retrieval_mode
