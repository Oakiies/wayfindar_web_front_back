# Backend port: navigate_indoor → WebNav_front_back

The localization/navigation stack in this backend is `navigate_indoor`'s, copied
in wholesale. The FastAPI shell, the package layout (`app.*`), and the data
location (`app/data/`) are this repo's and were kept.

Upstream source: `D:\wayfindar\navigate_indoor` (state as of 2026-08-22).
The previous backend code is archived at `backend/_archive_app_pre_port/`.

## Copied verbatim (only import paths rewritten to `app.*`)

| Here | Upstream |
|------|----------|
| `app/core/localization.py` | `core/localization.py` |
| `app/core/localizer.py` | `core/localizer.py` |
| `app/core/navigation.py` | `core/navigation.py` |
| `app/core/smoothing.py` | `core/smoothing.py` |
| `app/core/topology.py` | `core/topology.py` |
| `app/core/ar_geometry.py` | `core/ar_geometry.py` |
| `app/core/retrieval/` | `core/retrieval/` (new — pluggable backend registry) |
| `app/core/models/{netvlad,hloc_wrapper}.py` | `core/models/` |
| `app/localization_config.py` | `localization_config.py` (new here) |
| `app/services/{accel,ar_service,floor_detection,floor_service,localizer_service,nav_service,session,state,video_processor}.py` | `services/` |
| `app/utils/heading.py` | `utils/heading.py` |
| `app/data/{config,json_map,map,map_data}/` | `config/`, `json_map/`, `map/`, `map_data/` |
| `app/data/demo/floor5_fire_exit_1_ar_demo_v7.mp4` | `_ar_chevrons/` |

The import rewrite is purely mechanical: `import config` → `import app.config as
config`, `from core.x` → `from app.core.x`, and so on. No logic was changed.

## Adapted at the framework boundary

* **`app/api/*.py`** — upstream's Flask blueprints rewritten as FastAPI routers.
  Route paths, request handling and response bodies match upstream one for one;
  only the glue differs (`APIRouter`/`JSONResponse`/`UploadFile` instead of
  `Blueprint`/`jsonify`/`request.files`).
* **`app/main.py`** — FastAPI entrypoint, replacing upstream's `app_new.py`.
  Keeps upstream's background `initialize_system()` thread and its UTF-8 stdout
  reconfiguration (a Thai-locale console cannot encode the degree sign the EKF
  smoother logs, and the resulting `UnicodeEncodeError` kills the worker thread).
  Upstream's HTTPS/dev-cert and port-probing startup is dropped — uvicorn and
  `run_backend.ps1` handle both.
* **`app/config.py`** — upstream's `config.py` with paths anchored absolutely to
  the package dir instead of assuming the CWD is the repo root.
* **`app/services/floor_service.py`** — one added helper,
  `_absolutize_floor_paths()`. `building.json` is a byte-identical upstream copy
  whose paths (`map_data/result_floor5_6`) assume upstream's CWD; here the same
  assets live under `app/data/`, so the prefix is applied at load time rather
  than baked into the JSON. Re-syncing `building.json` stays a plain file copy.
* **`app/services/session.py`** — two additions on top of upstream, both for the
  existing frontend contract: `session_id` is a float (the frontend compares it
  numerically), and `queue` is a `ReplayQueue` that mirrors published events into
  a bounded deque so `?replay=` can backfill a reconnecting client.
* **`app/services/accel.py`** — `poc_megaloc_onnx` / `poc_lightglue` imports
  repointed at `app.core.models.megaloc_onnx` / `app.core.models.lightglue_matcher`,
  and the ONNX weight path at `app/data/models/megaloc_fp16.onnx`.

## Kept from this repo (not upstream)

* `app/__init__.py` — puts bundled `hloc` / `SuperGluePretrainedNetwork` on `sys.path`.
* `app/third_party/hloc/`, `backend/core/SuperGluePretrainedNetwork/` — vendored deps.
* `app/core/models/lightglue_matcher.py`, `app/core/models/megaloc_onnx/` — the
  accelerated stack, already ported here from upstream's `poc_*` directories.
* `app/utils/server.py` — `log_status` / `safe_print` / `get_lan_ip`. Upstream's
  `utils/server.py` is Flask-dev-server plumbing (SSL certs, port probing) and
  has no consumers here.
* `app/scripts/` — offline map-building scripts.
* `/api/navigation-state` and `?replay=` on `/api/navigation-stream` — frontend
  fallbacks with no upstream equivalent, both derived from the session so they
  cannot drift from the SSE stream.
* `/api/map` — alias for `/api/map-image`.

## Removed

`app/services/live_localize.py`, `app/services/sse_hub.py`, `app/api/schemas.py`.
These implemented the single-global-`navigation_state` model that upstream
replaced with per-run `NavigationSession` objects; they referenced state fields
that no longer exist. Available in `backend/_archive_app_pre_port/`.

## Behaviour changes to be aware of

* **Floors**: now the 5 enabled in upstream's `building.json`
  (`floor1`→`result_floor1_4`, `floor2`→`result_floor2_6`, `floor3`→`result_floor3_6`,
  `floor4`→`result_floor4_5`, `floor5`→`result_floor5_6`), default `floor5`.
  Previously 6 floors with `floor1`→`result_floor1` and `floor6` enabled. The old
  `result_floor1` and `result_floor6_2` directories are still on disk but unreferenced.
* **Accelerated mode is ON by default** (`NAV_ACCEL=0` only for an intentional
  legacy comparison), matching the deployed navigate_indoor stack. It needs `onnxruntime-gpu` and
  `lightglue` — see `requirements.txt`.
* **Retrieval modes** grew from `{netvlad, cosplace, megaloc}` to also include
  `salad8192`, `mixvpr4096`, `mixvpr512` via the new backend registry. The last
  two need an `external/MixVPR` checkout that is not bundled; they fail at
  model-load time if selected. Default is still `megaloc`.
* `utils/heading.calculate_direction()` prints a DEBUG line per call — upstream
  behaviour, kept deliberately. Remove it there if the log volume is a problem.
