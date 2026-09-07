"""
FastAPI entrypoint for the indoor navigation backend.

Native FastAPI (no Flask/WSGI). Heavy model + keyframe-database loading runs in
a background thread during startup so the server can bind quickly; /healthz
reports readiness. Routers preserve the original /api/* paths.

The localization stack under core/ and services/ is navigate_indoor's; see
app/README_PORT.md for what was adapted at the framework boundary.
"""
import sys
import threading
import traceback
from contextlib import asynccontextmanager

# Force UTF-8 console output before anything else can print.
#
# Windows picks the console encoding from the system locale (cp874 on a Thai
# install), which cannot represent characters this codebase already prints —
# the EKF smoother logs a degree sign on every initialization, and various
# diagnostics use arrows and math symbols. Encoding one of those raises
# UnicodeEncodeError ("character maps to <undefined>") from inside print(),
# which would kill the navigation worker thread over a log line.
# errors='replace' is the final backstop so an exotic glyph degrades to '?'
# instead of taking the server down.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass  # already wrapped/redirected by the host - leave it alone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.config as config
from app.services.floor_service import initialize_system
from app.api.localization import router as localization_router
from app.api.navigation import router as navigation_router
from app.api.floors import router as floors_router
from app.api.debug import router as debug_router

_init_done = threading.Event()
_init_error: Exception | None = None


def _bg_init() -> None:
    global _init_error
    try:
        initialize_system()
    except Exception as exc:  # noqa: BLE001
        _init_error = exc
        traceback.print_exc()
    finally:
        _init_done.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_bg_init, daemon=True, name='init').start()
    yield


app = FastAPI(
    title='Indoor Navigation Backend',
    version='2.0.0',
    description='FastAPI-native indoor navigation localization + routing API',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    """Keep 404/405 etc. as themselves — only unexpected errors become 500s."""
    return JSONResponse(
        {'success': False, 'error': exc.detail, 'status_code': exc.status_code},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def handle_api_exception(request: Request, exc: Exception):
    print(f"[ERROR] {request.method} {request.url.path} -> 500: {exc}")
    traceback.print_exc()
    return JSONResponse({'success': False, 'error': str(exc) or 'Internal server error',
                         'status_code': 500}, status_code=500)


@app.get('/healthz')
def healthz():
    return {
        'status': 'ok' if _init_done.is_set() and _init_error is None else 'initializing',
        'runtime': 'fastapi',
        'ready': _init_done.is_set() and _init_error is None,
        'init_error': str(_init_error) if _init_error else None,
        'retrieval_mode': config.APP_RETRIEVAL_MODE,
        'matching_mode': config.MATCHING_MODE,
        'accel_mode': config.ACCEL_MODE,
        'preload_all_floors': config.PRELOAD_ALL_FLOORS,
    }


app.include_router(localization_router)
app.include_router(navigation_router)
app.include_router(floors_router)
app.include_router(debug_router)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host=config.SERVER_HOST, port=config.SERVER_PORT,
                reload=False, log_level='info')
