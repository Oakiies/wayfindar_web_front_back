"""
AppState singleton — replaces all module-level mutable globals in the old app.py.
Every service imports `state` from here and reads/writes via `state.xxx`.
"""
import app.config as config


class AppState:
    def __init__(self):
        # Active floor localizer (convenience reference to localizers[current_floor_id])
        self.localizer = None

        # Per-floor Localizer cache: {floor_id: Localizer}
        self.localizers: dict = {}
        # Per-floor SuperPoint/SuperGlue localizer (debug comparison only)
        self.comparison_localizers: dict = {}

        # Active floor graph + nodes
        self.graph = None
        self.nodes = None

        # Cached floor graphs: {floor_id: (graph, nodes)}
        self.floor_graphs: dict = {}
        self.floor_nodes_map: dict = {}

        # Building-level merged graph (loaded from config/building.json)
        self.building_config = None
        self.floor_configs: dict = {}
        self.building_graph = None
        self.building_nodes = None

        # Active floor tracking
        self.default_floor_id: str = config.DEFAULT_FLOOR_ID
        self.current_floor_id: str = config.DEFAULT_FLOOR_ID

        # Active retrieval mode — mutable at runtime via switch_retrieval_mode()
        self.retrieval_mode: str = config.APP_RETRIEVAL_MODE

        # Active navigation sessions: {session_id: NavigationSession}
        self.sessions: dict = {}

    def get_latest_session(self):
        """Return the most recently created session, or None."""
        if not self.sessions:
            return None
        return list(self.sessions.values())[-1]


# Module-level singleton
state = AppState()
