# Frontend-Backend Integration Plan

## Scope
Integrate `web_nav/web_nav` React frontend with the Flask backend in `app.py` to support:
- Floor and room data loading
- Destination search from backend data
- Route planning preview from real map data
- Real-time navigation updates (live camera or uploaded video)

## Current State
- Frontend is currently mock-driven (hardcoded map markers and static route metadata).
- Backend already exposes production-like APIs for localization, routing, and event streaming.
- Camera logic already exists on frontend (`NavigationView`) and can be reused for backend live localization.

## Backend Endpoints Available (from app.py)
- `GET /api/floors`
  - Response: `{ floors: Floor[], default_floor: string }`
- `GET /api/rooms?floor_id=<id>&all=1`
  - Response: `{ rooms: Room[] }`
- `GET /api/map-image?floor_id=<id>`
  - Returns map image for floor
- `POST /api/live-localize` (multipart)
  - Form fields: `frame`, optional `floor_id`, `destination`, `destination_floor`
  - Response includes: `position`, `orientation`, `direction`, `relative_bearing`, `path`, `path_segments`, `destination_coords`, `map_image_url`
- `POST /api/upload-video` (multipart)
  - Form field: `video`
  - Response includes uploaded filename and metadata
- `POST /api/start-navigation`
  - JSON body includes `video_filename`, `destination`, optional `origin`, `interval`, `start_floor`, `destination_floor`, `debug_mode`
- `GET /api/navigation-stream`
  - SSE stream with event payloads (`start`, `update`, `warning`, `error`, `complete`)
- `POST /api/stop-navigation`

## Integration Architecture
1. Add a frontend API layer (`src/services/`) that wraps all backend calls.
2. Add typed backend models (`src/types/backend.ts`) to avoid ad-hoc payload parsing.
3. Keep UI components mostly presentational; move networking/state orchestration to container hooks.
4. Use one state source for navigation session:
   - idle -> preparing -> navigating -> completed/error
5. Keep mock map rendering as fallback until backend map and path are fully wired.

## Phase Plan

### Phase 0: Connection Setup (0.5 day)
- Add `VITE_API_BASE_URL` config.
- Create shared fetch helper with timeout + normalized error parsing.
- Add CORS/base URL health check script.

Deliverable:
- Frontend can call backend locally and receive JSON without manual URL edits.

### Phase 1: Replace Store/Room Source (1 day)
- Replace `stores.csv` as primary source with `GET /api/rooms`.
- Map backend room type/category to search filters.
- Keep CSV as fallback when backend is unavailable.

Deliverable:
- `SearchView` shows backend rooms per selected floor.

### Phase 2: Route Planning Data Binding (1 day)
- In `RoutePlanningView`, call backend for floors/rooms and destination floor selection.
- Replace static `routeTime`/`routeMeta` with backend-derived metrics (if available) or computed placeholders from path length.
- Load map image via `/api/map-image?floor_id=...`.

Deliverable:
- Route planning screen uses real floor/destination context.

### Phase 3A: Live Camera Navigation (recommended first, 1-2 days)
- Capture video frame from existing camera stream every 300-600ms.
- Send frame to `POST /api/live-localize`.
- Render backend `path`, `relative_bearing`, `nav_text`, and `destination_coords` in `NavigationView`.
- Add retry/backoff and UI status (`localizing`, `lost`, `recovered`).

Deliverable:
- Real-time turn guidance from live camera.

### Phase 3B: Uploaded Video Navigation (optional parallel path, 1 day)
- Add upload flow (`/api/upload-video` -> `/api/start-navigation`).
- Subscribe to `/api/navigation-stream` via `EventSource`.
- Update map/AR overlay from `update` events.

Deliverable:
- Offline navigation playback from recorded video.

### Phase 4: Reliability + UX Hardening (1 day)
- Error states for each API call and stream disconnect handling.
- Session lifecycle controls (stop/reset/restart).
- Persist last successful floor/destination in local storage.
- Add loading skeletons and empty states.

Deliverable:
- Robust user flow for unstable network/localization cases.

## Data Contracts to Implement in Frontend
Define strict TypeScript interfaces for:
- `Floor`, `Room`
- `LiveLocalizeResponse`
- `StartNavigationResponse`
- `NavigationStreamEvent` union by `type`

This prevents runtime mismatches and makes refactoring safer.

## Suggested Frontend File Changes
- `src/config/env.ts`
  - Resolve `VITE_API_BASE_URL`
- `src/services/http.ts`
  - `fetchJson`, multipart helper, timeout wrapper
- `src/services/navigationApi.ts`
  - Backend API wrappers
- `src/hooks/useNavigationSession.ts`
  - SSE + polling orchestration
- `src/App.tsx`
  - Replace hardcoded route metadata with backend session state

## Risks and Mitigations
- Coordinate mismatch (frontend SVG vs backend map coordinate system)
  - Mitigation: render backend map image first, then overlay backend coordinates directly.
- Camera/browser permission instability on mobile
  - Mitigation: keep current camera fallback UI + explicit retry button.
- SSE disconnects on weak networks
  - Mitigation: reconnect policy with jitter and max retry window.
- Large frame upload latency for `/api/live-localize`
  - Mitigation: downscale capture frame client-side before upload.

## Definition of Done
- User selects floor + destination from backend room list.
- Navigation screen receives live backend position/orientation/path.
- UI updates continuously with no hardcoded mock path dependency.
- Network and localization failures are visible and recoverable from UI.
