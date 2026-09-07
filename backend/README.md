# Backend

FastAPI backend for the indoor navigation system. The localization, routing and
AR stack is `navigate_indoor`'s, ported into this repo's `app/` package layout —
see [`app/README_PORT.md`](app/README_PORT.md) for exactly what was copied,
what was adapted at the framework boundary, and what changed in behaviour.

## Run

```powershell
.un_backend.ps1
```

Serves on port 5000 by default (`NAV_SERVER_PORT` to override). The script frees
the port first unless `NAV_AUTO_FREE_PORT=0`.

Model and keyframe loading runs in a background thread, so the server binds
immediately and `GET /healthz` reports progress:

```json
{"status": "ok", "ready": true, "retrieval_mode": "megaloc", ...}
```

Full startup takes a few minutes — all five enabled floors are preloaded so
floor switches and multi-floor routes are instant afterwards.

## API

| Route | Purpose |
|-------|---------|
| `GET /healthz` | Readiness + active modes |
| `GET /api/floors` | Enabled floors and the default |
| `GET /api/rooms` | Destinations (`?floor_id=`, `?all=1`) |
| `GET /api/map-image` | Floor-plan image (`?floor_id=`); `/api/map` is an alias |
| `POST /api/upload-video` | Upload a walkthrough video |
| `POST /api/start-navigation` | Start a run; returns `session_id` |
| `GET /api/navigation-stream` | SSE event stream (`?replay=N` to backfill) |
| `GET /api/navigation-state` | Poll fallback when SSE is unavailable |
| `POST /api/stop-navigation` | End a run |
| `GET /api/export-trajectory` | Full history of a run |
| `POST /api/live-localize` | Single-frame localization (live camera) |
| `GET\|POST /api/retrieval-mode` | Read or switch the retrieval backend |
| `GET /api/debug/*`, `/api/keyframe/*` | Inspection endpoints (debug runs only) |

## Configuration

Everything lives in `app/config.py` and `app/localization_config.py`; each value
can be overridden by an environment variable.

| Variable | Default | Effect |
|----------|---------|--------|
| `NAV_RETRIEVAL_MODE` | `megaloc` | Global retrieval backend |
| `NAV_MATCHING_MODE` | `superpoint` | Local matching; production mode uses SuperPoint |
| `NAV_ACCEL` | `1` | Enables LightGlue + MegaLoc accelerated stack (needs the extra deps) |
| `NAV_SERVER_HOST` / `NAV_SERVER_PORT` | `0.0.0.0` / `5000` | Bind address |
| `NAV_APP_DEBUG` | `1` | Debug logging |

## Data

Floors are declared in `app/data/config/building.json`, a verbatim copy of
navigate_indoor's. Its relative paths are anchored to `app/data/` at load time
(`floor_service._absolutize_floor_paths`), so re-syncing that file from upstream
is a plain copy. Per-floor assets live in `app/data/map_data/result_floorN_M/`.

## Dependencies

```powershell
pip install -r requirements.txt
pip install git+https://github.com/cvg/Hierarchical-Localization   # hloc
```

`hloc` and `SuperGluePretrainedNetwork` are also vendored under
`app/third_party/` and `core/`, and put on `sys.path` by `app/__init__.py`.
Read the warning at the bottom of `requirements.txt` before installing the
accelerated stack — it can silently replace a CUDA torch build with a CPU one.
