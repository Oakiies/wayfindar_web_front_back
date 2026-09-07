"""
Central configuration: paths, env-resolved runtime params, retrieval mode.

Ported from navigate_indoor/config.py. The only structural difference is path
anchoring: every path here is absolute, rooted at this package directory, so the
backend works regardless of the working directory uvicorn is launched from
(upstream runs `python app.py` from inside navigate_indoor/ and can use bare
relative paths).
"""
import os
import sys
from pathlib import Path

import app.localization_config as _lc
from app.core.retrieval import supported_modes as _retrieval_supported_modes

# ── Anchors ──────────────────────────────────────────────────────────────────
# BASE_DIR = backend/app/
BASE_DIR = Path(__file__).resolve().parent

# building.json and the localization package resolve their inner paths relative
# to the process CWD (e.g. 'data/json_map/floor1.json'). Anchor the CWD here so
# those relative paths resolve regardless of where uvicorn was launched from.
os.chdir(BASE_DIR)

# sys.path's '' entry is resolved against the *current* CWD, so the chdir above
# hides top-level packages that sit next to this one — notably `megaloc`, whose
# import failure silently drops retrieval to the NetVLAD fallback (and from
# there to no retrieval at all, which disables floor detection). Pin the repo
# root on sys.path so those imports keep working from any CWD.
_REPO_ROOT = str(BASE_DIR.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DATA_DIR_ROOT = BASE_DIR / 'data'
RUNTIME_DIR = BASE_DIR / 'runtime'

# ── Folder Paths ─────────────────────────────────────────────────────────────
UPLOAD_FOLDER = RUNTIME_DIR / 'uploads'
TEMP_FRAMES_FOLDER = RUNTIME_DIR / 'temp_frames'
DEMO_VIDEO_FILENAME = '__demo_ar__.mp4'
DEMO_VIDEO_PATH = DATA_DIR_ROOT / 'demo' / 'floor5_fire_exit_1_ar_demo_v7.mp4'
MAP_IMAGE = DATA_DIR_ROOT / 'map' / 'floor5.jpg'
JSON_MAP = DATA_DIR_ROOT / 'json_map' / 'floor5.json'
LEGACY_DATA_DIR = DATA_DIR_ROOT / 'map_data' / 'result_floor5_6'
BUILDING_CONFIG_PATH = DATA_DIR_ROOT / 'config' / 'building.json'

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
TEMP_FRAMES_FOLDER.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}

# ── Server Params (edit here to override env vars) ───────────────────────────
RETRIEVAL_MODE_PARAM = None          # None → use localization_config.RETRIEVAL_MODE or env var
SERVER_HOST_PARAM = '0.0.0.0'
SERVER_PORT_PARAM = 5000
APP_DEBUG_PARAM = True

DEFAULT_FLOOR_ID = 'floor5'  # pre-init fallback only; building.json 'default_floor' wins

# ── Localization Constants ───────────────────────────────────────────────────
RANSAC_REPROJ_THRESHOLD = 12.0
RANSAC_ITERATIONS = 2000
MIN_INLIERS = 8
TOP_K_RETRIEVAL = 20
USE_NETVLAD = True
USE_SUPERPOINT = True
USE_SUPERGLUE = True

SUPPORTED_RETRIEVAL_MODES: set[str] = _retrieval_supported_modes()


def normalize_retrieval_mode(mode: str) -> str:
    value = str(mode or '').strip().lower()
    if value not in SUPPORTED_RETRIEVAL_MODES:
        raise ValueError(
            f"Unknown retrieval mode {mode!r}; automatic NetVLAD fallback is disabled. "
            f"Supported modes: {sorted(SUPPORTED_RETRIEVAL_MODES)}"
        )
    return value


# ── Resolved Runtime Config ──────────────────────────────────────────────────
# Priority: RETRIEVAL_MODE_PARAM → env var NAV_RETRIEVAL_MODE → localization_config default
APP_RETRIEVAL_MODE: str = normalize_retrieval_mode(
    RETRIEVAL_MODE_PARAM
    if RETRIEVAL_MODE_PARAM is not None
    else os.getenv('NAV_RETRIEVAL_MODE', _lc.RETRIEVAL_MODE)
)

# Primary local-matching backend. The deployed stack from navigate_indoor is
# SuperPoint + LightGlue, so SuperPoint is the default. NAV_MATCHING_MODE may
# still be set explicitly to 'orb' for an intentional legacy comparison run;
# automatic fallback to ORB is disabled in the Localizer.
MATCHING_MODE: str = (str(os.getenv('NAV_MATCHING_MODE', 'superpoint')).strip().lower()
                      if os.getenv('NAV_MATCHING_MODE', 'superpoint').strip().lower() in ('orb', 'superpoint')
                      else 'superpoint')

# Accelerated mode (default ON, matching navigate_indoor). When enabled via
# NAV_ACCEL=1 the primary localizer runs the validated fast stack:
# SuperPoint + LightGlue matching, ONNX MegaLoc retrieval, GPU preprocessing,
# top_k=NAV_ACCEL_TOPK. ~4.4-5.9x faster with identical accuracy on floors that
# have a SuperPoint map. Component failures are fatal; the app must not silently
# change to SuperGlue/ORB/NetVLAD and produce a result from a different stack.
ACCEL_MODE: bool = os.getenv('NAV_ACCEL', '1').strip().lower() in ('1', 'true', 'yes', 'on')
ACCEL_TOP_K: int = int(os.getenv('NAV_ACCEL_TOPK', '4') or 4)
PRELOAD_ALL_FLOORS: bool = os.getenv('NAV_PRELOAD_ALL_FLOORS', '0').strip().lower() in ('1', 'true', 'yes', 'on')

SERVER_HOST: str = str(os.getenv('NAV_SERVER_HOST', SERVER_HOST_PARAM or '0.0.0.0')).strip() or '0.0.0.0'
SERVER_PORT: int = int(os.getenv('NAV_SERVER_PORT', SERVER_PORT_PARAM or 5000))
APP_DEBUG: bool = str(
    os.getenv('NAV_APP_DEBUG', '1' if APP_DEBUG_PARAM else '0')
).strip().lower() in {'1', 'true', 'yes', 'on'}
