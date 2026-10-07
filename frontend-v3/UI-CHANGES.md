# UI refresh (POC)

## 2026-09-13 — Accent + button shape from Apple's DESIGN.md

Source: [Apple DESIGN.md](https://getdesign.md/apple/design-md), via
[awesome-design-md](https://github.com/VoltAgent/awesome-design-md). Preview:
`public/apple-theme-preview.html`.

Three token-level changes in `src/index.css`, following Apple's stated
principles ("one accent colour drives all interactivity", "exactly one
drop-shadow exists", "pill-shaped primary CTAs; secondary ghost variants"):

- `--color-accent` `#0d6efd` → `#0066cc` (Action Blue), `--color-accent-soft`
  updated to match. `MapCanvas.tsx`'s `ROUTE_COLOR` / `POSE_COLOR` are
  hardcoded hex (canvas 2D can't read CSS custom properties) and were updated
  by hand to stay in sync.
- `.btn-primary` / `.btn-secondary` go pill-shaped (`border-radius: 999px`);
  secondary switches from a filled surface to a ghost outline.
- `--shadow-card` / `--shadow-float` lightened — Apple's hierarchy comes from
  surface-colour transitions and backdrop blur, not shadow depth.
- `--font-sans` now leads with `-apple-system, BlinkMacSystemFont` so Apple
  devices render actual SF Pro; Inter stays the loaded fallback everywhere
  else.

Not touched: card/sheet radii (`--radius-sm|lg|xl`), `.glass`/`.glass-dark`,
Apple's 18px product-grid card radius (no matching surface in this app yet).

## 2026-09-11 — Live-causal tracker status

- Video navigation now uses one causal KLT/PnP pipeline for every floor and destination; replay ignores future pose samples and keeps the 0.15s live pose-age gate.
- Test Localize exposes user-facing tracking state and the backend AR visibility reason, separating tracking loss from map/navigation state.

A visual pass over the five app screens. **No navigation, routing, camera or AR
logic was touched** — every prop, handler and state machine is unchanged. What
changed is the styling layer, plus three small usability fixes noted below.

Original sources are kept at `../_archive/frontend-v3-src-before-ui-poc/`.

## 1. One design system instead of five

Before, each screen carried its own palette and its own inline styles:

| Screen | Background | Accent | Font |
| --- | --- | --- | --- |
| Main map | `#ececec` | `#8a7d6e` | inherited |
| Search | `#f0eeea` | `#1c1c1c` | inherited |
| Store detail | `#f0eeea` | `#3b82f6` | `DM Sans` (never loaded) |
| Route planning | `#ececec` / `#f7f7f6` | `#1c1c1c` | `Helvetica Neue` |
| Navigation | `#f0eeea` | `blue-500` + slate/rose/amber/emerald | inherited |

`src/index.css` now defines the whole system as Tailwind v4 theme tokens:

- **Surfaces** — `paper`, `paper-2`, `surface`, `surface-2`
- **Ink** — `ink`, `ink-2`, `ink-3`, `ink-4` (four steps, no more ad-hoc greys)
- **Lines** — `line`, `line-2`
- **Accent** — a single `accent` (`#0d6efd`), the same blue the map canvas already
  drew the route in, plus `danger` / `warn` / `ok` for states only
- **Radii** — `--radius-sm|md|lg|xl` (10 / 14 / 20 / 28px)
- **Elevation** — exactly two shadows, `--shadow-card` and `--shadow-float`
- **Type** — Inter, loaded in `index.html`, with a real system fallback stack

Component classes: `.glass`, `.glass-dark`, `.btn-primary`, `.btn-secondary`,
`.field`, `.eyebrow`, `.press`, `.tap`.

## 2. Shared primitives

| New file | Replaces |
| --- | --- |
| `components/ui/IconButton.tsx` | four hand-rolled 38px circles with differing inline styles |
| `components/ui/BottomSheet.tsx` | the drag-and-snap sheet logic duplicated in StoreDetail and RoutePlanning (~60 lines each) |
| `components/ui/FloorRail.tsx` | the floor switcher rebuilt separately in MainMap and Navigation |
| `lib/floorLabel.ts` | three copies of the `"Floor 2" -> "F2"` helper |

## 3. Usability fixes

1. **Search header** had a back arrow *and* an X that both closed the view. The X
   now clears the query instead — one job each.
2. **Store detail header** had the same duplicate (back arrow and X both called
   `resetToMap`). The X is gone; the freed width goes to the search field.
3. **Store detail sheet** showed a phone and a share button with no handlers
   behind them. They are replaced by the store's `address` — a real field on the
   `Store` record that the UI had never displayed. (`hours` was tried here too
   but removed: it read as opening times without saying so.)
4. **Navigation top bar** read `FLOOR  Floor 1` — the eyebrow repeated what
   `activeFloorLabel` already says. The eyebrow is gone.
5. **Navigation destination card** was a flat emoji + four equally-weighted text
   lines. It now uses the same logo tile as the store sheet, a `Heading to`
   eyebrow, a hairline divider, and an ETA where the number carries the weight
   (`2` at 26px, `min` small and muted beside it). `routeMeta` is parsed so
   `"120 m (mock)"` renders as `120 m` plus a small `mock` chip instead of
   inline parentheses, and `"45 m | 2 floors"` uses a `·` separator.
6. **Route planning sheet** now centres the estimate across the full width
   (`2` at 46px with `min` beside it, distance below) instead of pairing it with
   a right-aligned `To` block — the From / To card at the top of the screen
   already names both ends, so the sheet was repeating it. Same number parsing
   and `mock` chip as the navigation card.

## 3b. Map symbols (position, heading, destination pin)

- **Heading** was three stacked layers: a 60-degree field-of-view cone at
  `opacity="0.28"`, a solid triangle, and the pose dot. The translucent cone is
  gone. One hard-edged wedge now states the bearing — no transparency anywhere
  in the symbol, so it reads the same over a light or dark floor plan.
- **Position** is drawn casing-first: the white wedge and white disc are laid
  down, then the accent wedge and accent disc on top. The two accent shapes
  merge into a single silhouette with one even white outline, instead of a dot
  with a separate arrow stuck to it. Pose radius went 11 -> 7 px.
- **Re-localising** no longer teleports the marker: the pose group carries a
  320 ms transition on its translate. Only the translate — animating the
  rotation would spin the long way round each time the heading wraps past 360.
- **Destination pin**: hairline casing (0.2 -> 0.16 of radius) and a smaller
  hole, so it stays a flat teardrop rather than a heavy blob.
- **Origin marker**: dropped the third concentric circle; a white casing plus a
  ring is enough and matches the pose symbol's weight.
- Dead `pulse-ring` / `pulsing-dot` CSS removed — nothing referenced it.

## 3c. Telling "me" apart from "the route"

The position marker was invisible in the AR map popup, and the reason was not
subtlety - the pose and a route dot were *the same symbol*: an accent disc in a
white casing, 7 units against 4. Making the pose bigger, or adding a halo and a
shadow to it, only papered over that. The fix was to stop drawing the route as
discs at all.

- **The route is one straight stroke.** An accent `4 px` line over a `7.4 px`
  white casing, round joins, following the route's own vertices. No sampling, no
  spacing constant, and no per-dot geometry to keep in step with the pose.
- **The pose is a small bare disc plus a radar fan.** Disc `r 7` - smaller than
  the old marker, not bigger - with a `±32°`, `r 30` sector for the bearing. A
  line and a dot-with-a-fan are different *shapes*, so sharing the accent colour
  costs nothing.
- **The disc has no white casing.** A casing is what carries a symbol over a
  dark ground, and the pose is always *on* the route, which runs down corridors:
  the bare disc scores 3.81 against the corridor grey `#ececec` and 3.13 against
  `#d7d7d7`. It would fall to 1.80 inside a turquoise room, and a walker is
  never in one. Losing the ring also lets the disc sit continuously on the line
  instead of punching a white hole through it. The route keeps its casing - it
  does cross room thresholds - and so does the origin ring, which can be
  anywhere. `design/dot-ring.png` shows the symbol on every ground it can land
  on, with and without.
- **The fan is flat**: one fill at `0.32` and one outline at `0.62`, no gradient.
  A cone that fades to nothing is what sank the original version - it vanished
  over the dark parts of a floor plan. The outline is what carries it there.
- **Symbol sizes are real screen pixels.** `s()` divided by `MAP_SIZE`, which is
  only correct when the canvas happens to be 500 px wide. A `ResizeObserver`
  measures the drawn square (the shorter side, because of
  `preserveAspectRatio="meet"`) and `s()` divides by that, so 7 units is 7 px in
  a 180 px popup and in a full-screen map alike. This fixed every symbol at
  once, the destination pin included.

Colour was left alone on purpose. Blue-means-you is worth keeping; what failed
was shape, so that is what changed.

`public/map-symbols.html` carries six candidate pose symbols - radar sector,
long beam, radar with range rings, chevron on the ring, wide torch, compass
needle - switchable against the live floor plan, with the route line and dotted
trail both available for comparison. The shipping symbol is the radar sector.
`design/render_pose_variants.py` renders the same six to a PNG for review away
from a dev server.

**Colour is still open.** The plan itself is 60% light grey `#ececec` and 12%
turquoise rooms (`#a5d8d9` / `#6dc8c9`). Measured against the darker turquoise,
`#0d6efd` scores **1.80** - the route is legible there because of its white
casing, not because of its colour, and a lighter blue (`#7fa8e8`, 1.03) would
disappear entirely. Five palettes are proposed in the same page and rendered to
`design/colour-schemes.png`, three of them green.

Green is the crowded one on this plan: the rooms are mint (`#58cbac`, hue 164),
the lifts are neon lime (`#94ff01`, hue 85), and `NavigationView` already spends
`#22c55e` on the lift transition marker - which scores 1.10 on the turquoise and
sits 0 degrees from that marker. Only a dark green clears all three, so green
belongs on the route (`#14532d`, 3.65) rather than on the pose.

Orange is squeezed rather than crowded: the stairs marker is `#f59e0b`
(hue 38) and the destination pin is `#e5484d` (hue 358), so every orange sits
13-23 degrees from one and 17-29 from the other. `#ea580c` (hue 21) is the
widest gap on offer. Its contrast on the turquoise is only 1.42, but for the
pose that matters less than it does for the route - the disc has a white ring
and the fan has an outline, and against a blue or a dark-green path the
separation is carried by hue, which reads faster than a contrast ratio. The
open question with orange is the destination pin: they become the only two warm
things on the map, told apart by shape (disc plus fan vs teardrop with a hole)
rather than by colour. Orange also means the pose needs its own token - the
palette stops having a single accent.

The standing recommendation is **B, two-step blue**: route `#0a49c4` (3.04) under pose `#0d6efd`, which puts a real contrast
number on the path, keeps blue-means-you, and stays inside one hue so the token
system still has a single accent.

## 4. Other adjustments

- **AR fusion minimap**: render the floor plan as a DOM image beneath the
  transparent marker canvas. This keeps the right-side minimap visible on
  mobile browsers even when canvas image decoding is delayed. The calibrated
  floor 5 base map is also shown while the first localization request is in
  progress, instead of waiting for `running` to become true.
- **AR fusion startup diagnostics**: guard the initial localize call from PDR
  retries, time out camera-frame capture, and show whether the page is waiting
  for a frame or the localization request itself.
- **AR fusion continuous tracking**: start the PDR/render loop before the first
  VaL response, anchor the marker on fix #1 with a provisional scale, and keep
  the live PoC on the PDR-updated overlay instead of freezing a single
  world-registered camera pose between corrections.
- **AR fusion marker/startup tuning**: reduce the minimap user marker and
  heading fan slightly, and schedule the PDR/render loop before sensor and
  camera permission so cold floor-localizer loading does not delay motion
  tracking.
- **AR fusion world-payload wiring**: feed the backend `poc_ar_arrow_v2`
  ribbon/caret payload into the shared `ARFloorThreeOverlay` when a routed
  pose is available; retain the PDR overlay when the world pose is unavailable.
- **AR fusion anchor sequencing**: keep PDR inactive while the initial VaL
  request establishes the map anchor, then attach/consume motion sensors and
  start PDR from that accepted fix so AR movement cannot begin from an
  unlocalized origin.
- **AR fusion layer isolation**: hide the legacy blue stylized AR group when
  the PoC has a selected route, so only the `poc_ar_arrow_v2` ribbon/caret layer
  is visible on the AR fusion page.
- **AR fusion PDR world tracking**: pass the high-rate PDR displacement through
  the stabilized camera-floor basis from the VaL payload and apply it smoothly
  to the POC AR camera every render frame; camera orientation stays on the
  stabilized visual pose, matching the PoC, and VaL corrections continue to
  reset the anchor.
- **AR camera-fit registration**: keep the AR projection consistent with each
  camera element's `object-fit`; live `object-cover` pages now compensate the
  intrinsic matrix for the cropped image instead of using the replay
  `object-contain` layout.

- `Walkthrough replay` now passes `strictWorldAr` to `ARFloorThreeOverlay`.
  The replay therefore follows the PoC world-AR contract: missing or weak
  camera-pose payloads hide the world overlay for that frame instead of
  switching to the screen-fixed fallback, which could show a turn cue using a
  different projection/logic from `poc_ar_arrow`.
- The replay world renderer now forces a Three.js camera-world update after
  applying each PoC `R/t` pose, matching the original `ar_world.js` projection
  path before the frame is drawn.
- The working Walkthrough cadence remains `0.05s` (~20 FPS). The `1.5s` cadence
  is isolated as a PoC experiment in
  `backend/poc_ar_arrow/out/poc_interval_1p5_experiment.avi` and its metrics
  CSV, so it does not change the existing replay behavior.

- Every interactive control is at least 44x44px (`.tap` / `IconButton`).
- `aria-label`, `aria-pressed` and `aria-expanded` added to icon-only controls;
  search results are a real `<ul>`.
- Safe-area insets (`env(safe-area-inset-*)`) applied to all top and bottom
  chrome, not just the home screen.
- Turn cues in navigation use neutral ink; colour is reserved for off-route
  (warn) and arrival (ok), so it means something.
- Loading and error screens restyled to match; `src/App.css` (unused Vite
  boilerplate) deleted.
- `MapCanvas` origin/destination marker colours nudged onto the token values.
- `index.html`: real title, `theme-color`, `viewport-fit=cover`, overscroll lock.

## Not touched

`VideoTestPanel` and `ARFloorThreeOverlay` keep their existing look — the first
is a developer tool on its own dark theme, the second draws into WebGL.

Three pre-existing lint errors remain (`react-hooks/set-state-in-effect` in the
NavigationView map-popup effects, `react-hooks/refs` in `MapCanvas`). They are
in logic this pass deliberately left alone.
- AR calibration-size consistency: live world AR now lays out and projects against the same calibration image size used by backend PnP, preventing a 1280x720 camera stream from being projected with 1920x1080 intrinsics and shifted to the side.
- Camera capture consistency: live camera requests 1920×1080 and always uploads a 1920×1080 frame (with a safe lower-resolution device fallback), matching the floor calibration.
- PDR startup: sensor samples are processed immediately after permission, while position remains unanchored until the first VaL fix; the first fix no longer resets the warmed sensor state. The POC now reports whether an AR payload is ready or a destination is missing.
- AR route activation: selecting a destination while the POC is already running now triggers an immediate localization request, so route geometry is not delayed until the next PDR drift threshold.
- AR diagnostics visibility: localization/AR payload status now remains visible alongside the continuously updating PDR counters instead of being hidden by the per-frame debug text.
@@
### AR fallback visibility

### Frontend home comparison preview

- Added `public/frontend-home-versions.html` to compare the first Map screen of
  `frontend`, `frontend-v2`, and `frontend-v3` side by side.
- The preview uses the real floor map assets, supports switching floors across
  all three cards, and keeps the comparison responsive for phone and desktop.

- Removed the screen-space POC fallback from the AR fusion page. It now shows
  only world-registered AR geometry from `poc_ar_arrow` so a cue is never
  mistaken for something attached to the real floor.
- The live AR status pill now distinguishes world AR, waiting for a stable
  world pose, and the no-destination state.
- Portrait camera frames now use the same `+90°` camera-to-landscape rotation
  as the working mobile PoC before localization, preventing the world AR
  projection from shifting laterally relative to the displayed camera view.
- PDR-to-world AR translation now anchors at the same VaL map point that seeds
  the fused position, instead of mixing it with the stabilized pose anchor;
  this removes a false sideways offset after a localization correction.
- Added a PDR yaw bridge around the AR payload's floor normal. The world route
  now remains fixed while the phone rotates between visual localization fixes,
  instead of following the camera's view.
- Smoothed world-camera pose corrections over the render loop and added a small
  yaw deadband, preventing new VaL fixes and indoor compass noise from making
  the floor AR jump or wobble while walking straight.
- Extended the world AR lookahead without changing the original caret spacing,
  and kept the continuous floor ribbon visible farther ahead, so guidance
  covers a longer route instead of appearing only near the current position.
- Added a continuous PDR prediction PoC: stride length is distributed across
  the current step interval and emitted every render frame, while VaL remains
  the drift correction source. This follows WebARNav's high-frequency PDR
  behavior instead of moving the AR only at footfall events.
- Added a live world-AR hold for short localization/AR-gate dropouts. The last
  trustworthy floor payload remains visible and continues receiving PDR motion
  instead of being cleared when a valid localization response has no new AR
  geometry.
- Reduced only the distant caret density: near-floor carets keep the original
  spacing, while carets beyond roughly 8 m are thinned to every second station.
  The continuous floor ribbon and total route lookahead remain unchanged.
- Added an in-page Dataset recorder to the AR Fusion PoC. After the camera/PDR
  starts, the user can record the camera stream plus timestamped PDR samples
  and localization responses, then download the video, JSONL logs, and manifest
  directly from the mobile page.
- Added `ar-video-localize.html`, a standalone video replay page for testing
  visual localization and world AR without browser PDR or IMU. It reuses the
  existing upload/replay pipeline and world-AR overlay.
- AR map popup: the live `NavigationView` minimap now appears only after the
  camera is active and AR is running in landscape, with an accessible region
  label and 44px expand control. The map remains draggable and expandable.
- AR map popup: changed the preview to a square, top-down floor-plan card that
  uses the full map image area, with the live route, user position, and heading
  drawn directly over the floor plan to match the reference UI.
- Added `public/frontend-map-versions.html` to compare the top-down map treatment
  used by `frontend`, `frontend-v2`, and `frontend-v3` with the same Floor 5 data.
- Finalized the map symbols as one accent: `Dotted trail + casing` for the
  route and `Radar sector` for the live user pose. `MapCanvas.tsx` now renders
  the route as evenly spaced accent dots with a white casing.
- Added the final reference treatment: the live radar-sector pose now has a
  white casing, matching the route dots' casing while keeping the same accent.
- Locked the AR minimap to the upper-right corner so it no longer drifts when
  dragged; clicking it still toggles between the compact and expanded sizes.
- Kept the AR control chrome aligned with the existing `IconButton` system:
  close on the upper-left, camera-off and map controls on the upper-right,
  each 44px with accessible labels.
- Unified AR Fusion heading conversion: backend/MapCanvas use map angles
  (0° = right/east, +90° = down/south), while PDR keeps its compass-like
  heading (0° = up). The calibration now converts between these frames once,
  so the minimap fan, fused position, and AR turn direction stay aligned.
- Corrected visual heading at the source: derive the camera's forward vector
  from the PnP rotation, project it onto the calibrated floor/map basis, and
  use that map angle directly. Motion displacement is no longer used to bend
  the facing direction at corners.

### Frontend home comparison colour alignment

- Updated the `frontend-v3` floor rail in
  `public/frontend-home-versions.html` to use the same warm selected-floor
  colour as `frontend`.

### Frontend-v3 floor rail colour

- Applied the original `frontend` selected-floor colours to the real
  `frontend-v3` `FloorRail` component via shared CSS tokens:
  warm beige background, taupe text, and a soft beige border.

### Mobile remote access preparation

- Removed the `Test video localize` entry point from the real home map and the
  standalone frontend comparison preview so the mobile navigation surface only
  exposes the production map actions.

### Navigation destination summary sizing

- Reduced the mobile destination summary card slightly: tighter padding and
  gap, smaller logo tile, destination title, and ETA while keeping the card's
  readability and landscape sizing unchanged.

### Landscape gate before live localization

- Live camera localization now waits until the screen is in landscape, so the
  backend never receives portrait frames from the production navigation flow.
- Added an explicit rotate-phone message in AR mode and an
  `awaiting_landscape` tracking state while the camera remains active.

### Remote HTTPS development access

- Added `npm run dev:remote` to serve the frontend over HTTPS and expose the
  frontend/backend pair through a Cloudflare Quick Tunnel for mobile testing
  from another network.

### Standalone camera calibration position viewer

- Added `public/camera-calibration-position-viewer.html` as a separate static
  experiment viewer for `floor1_wide_pare.MOV`.
- The viewer compares the query frame with Map K and Estimated K positions on
  the floor map, with frame navigation, playback, and per-frame metrics.

### Video localization test menu restored

- Restored a visible `Test` item in the frontend-v3 map bottom navigation.
- The item opens the existing video localization test panel without changing
  the production navigation flow.

### Test Localizer entry point made explicit

- Added a prominent `Test Localizer` action below the map search control.
- Renamed the bottom navigation label to `Localizer` so the video test purpose
  is clear on small screens.
- Added `/?test=localizer` deep-link support to open the video test panel
  immediately, plus a shortcut from the standalone calibration viewer.


## 2026-09-08 ? Test Localize replay camera registration

- VideoTestPanel disables camera easing with `smoothCameraPose={false}` so the AR camera follows the selected video pose immediately.
- Timeline selection no longer looks 0.05 seconds into the future. World AR is hidden when the selected pose is older than 0.15 seconds; map/text remain available.
- Backend replay now uses accepted frame poses without EMA and clears world AR on missing poses.
- Tradeoff: PnP noise and gaps become visible; this removes artificial lag but does not establish camera calibration accuracy.
- Validation: TypeScript and targeted ESLint passed; six backend regression tests passed. Full lint has existing errors in MapCanvas/useRoutePlanning. Browser/full-video validation remains pending.
- Details: `../backend/poc_cross_camera/out/IMG_6955_REPLAY_REGISTRATION_FIX.md`.


## 2026-09-08 ? M21 replay at the confirmed 1.5-second interval

- Supersedes the freshness-only behavior above: default interval is 1.5 seconds as confirmed by the user.
- Buffered replay interpolates world camera centres and rotations between valid adjacent anchors, up to a 1.65-second gap. Geometry and navigation text remain tied to the current event.
- No interpolation across held/missing poses, floor changes, or long gaps; world AR is hidden after 0.15 seconds when no valid bracket is available. This is an estimate for recorded replay, not live visual tracking.
- Four frontend pose tests, TypeScript and targeted lint passed. Fresh 0?60s production navigation yielded 35 updates (32 PnP, 3 holds); destination m21 resolved to M21_A.
- Offline review: straight corridor guidance improves, but distant geometry around 31?33s still points toward a wall. Spatial alignment is not fully validated. No claim of a complete AR accuracy fix.
- Evidence: `../backend/poc_cross_camera/out/replay_registration_1p5s/M21_1P5S_REVIEW.md`.


## 2026-09-08 ? Pin replay route stations in world coordinates

- Video replay now calls the AR builder with `pin_route=True`, eliminating per-fix lateral translation of the entire route to follow the camera.
- Keeps the confirmed 1.5-second sampling interval and camera interpolation. Legacy live/PoC defaults remain compatible.
- Ten backend regression tests passed. Cached accepted poses reveal up to 20.6164 map pixels of artificial world translation between updates in the old recentering policy; the pinned policy removes that term.
- This is not a claim of zero screen-space drift: PnP noise, sparse camera interpolation, and map/floor alignment remain separate limitations.
- Evidence: `../backend/poc_cross_camera/out/replay_registration_1p5s/world_pinned/STABILITY_FIX.md`.


## 2026-09-08 ? Honest replay status and recovery guidance

- Labels the replay AR mode as experimental and its route as an estimated preview.
- Missing world AR now takes precedence over stale TURN/GO STRAIGHT text; the card directs users to the map and removes turn emphasis while the pose is unavailable.
- Arrival copy describes the destination area and asks users to verify the room sign.
- Status uses polite live announcements. No per-frame tracker is claimed or introduced by this copy change.
- Architecture/UX review: `../backend/poc_cross_camera/out/replay_registration_1p5s/AR_UPDATE_APPROACH_REVIEW.md`.


## 2026-09-09 — Route-aware AR for shallow corridor bends

- Compared the replay camera view against the floor-1 node graph and top-down
  user position for every frame from 24–50 seconds (782/782 frames).
- The selected route follows `Intersection 1 → M23_B`; its largest deflection
  is 22.96° and navigation reports `GO STRAIGHT`, so this is a continuous
  corridor bend rather than a discrete turn.
- Backend AR guidance now classifies the bend from the user's on-route position
  and sends the continuous floor ribbon without repeated turn carets.
- The Three.js renderer treats an explicit `carets: []` as authoritative and
  falls back to legacy `chevrons` only when the `carets` field is absent.
- Evidence: `../backend/poc_cross_camera/out/ar_reasonableness_poc/round_02_exhaustive_graph/RESULT.md`.


## 2026-09-09 — Reject screen-fixed KLT as world AR

- Marked the V2 screen-space KLT/homography result as rejected: optical-flow
  acceptance does not establish floor registration or depth approach.
- Added a replay comparison that keeps route geometry fixed in world
  coordinates and reprojects it from the buffered camera pose each frame.
- World AR is hidden when no bounded pose is available; it is never held as a
  frozen polygon over a different camera frame.
- This validates recorded replay behavior only. Live camera AR still requires
  target-frame tracked-landmark PnP rather than future-pose interpolation.
- Evidence: `../backend/poc_cross_camera/out/ar_reasonableness_poc/round_03_world_approach/RESULT.md`.


## 2026-09-09 — Bridge plausible replay pose gaps without holding AR

- Replay camera lookup now skips `HOLD_LAST_FIX` events when finding the two
  valid camera anchors around the current video time. Map position and
  navigation text still follow the current timeline event.
- A buffered gap up to 3.10 seconds is interpolated only on the same floor and
  only when implied motion stays below 3 m/s and 45 degrees/s. Otherwise world
  AR is hidden.
- This removes the disappearance in the 37.5–39.0 second recorded replay gap
  without freezing a polygon on the image.
- A centered pose smoother was evaluated but not promoted: median jerk changed
  only 47.951 -> 47.763 px/frame² while p95 worsened from 28000.702 to
  41858.641 px/frame².
- Target-frame tracked-landmark PnP recovered 51/63 gap frames versus 2/63 for
  the old buffered policy. It remains a PoC because 12 frames still fail the
  safety gates.
- Validation: five frontend pose tests, TypeScript, targeted ESLint, production
  build, and 17 backend regression tests passed.
- Evidence: `../backend/poc_cross_camera/out/ar_reasonableness_poc/round_04_pose_stability/RESULT.md`
  and `../backend/poc_cross_camera/out/ar_reasonableness_poc/round_05_gap_tracked_pnp/RESULT.md`.


## 2026-09-09 — VideoTestPanel default frame interval lowered 1.5s -> 0.5s

- `intervalSeconds` default in `VideoTestPanel.tsx` now matches the backend's
  own new default (`app/api/navigation.py`), 0.5s instead of 1.5s. The input
  is still user-editable; this only changes what the panel opens with.
- Root cause traced on a fresh test walk (`IMG_6955.MOV` -> destination M21,
  floor1): at 1.5s a 1-2s human turn got 0-1 fresh localizations, which reads
  as AR "freezing" independent of any route/geometry issue. Measured
  `localize()` cost on this deployment is ~0.17s median / 0.20s p90, so 0.5s
  keeps real headroom.
- Diagnosis and raw CSVs: `../backend/poc_ar_arrow/out/DIAGNOSIS_ar_m21_walk.md`.

## 2026-09-10 — Camera waits for backend readiness

- Live camera startup now polls `/healthz` before requesting the camera, so the
  first captured frame cannot race model/keyframe initialization.
- The live-localize and replay-start endpoints return HTTP 503 with a 250 ms
  retry hint while the localizer is still preparing.
- The readiness wait is cancelable when camera/navigation view is closed and
  has a 45 second failure deadline.
- The causal IMG_1895 replay in `../backend/new_ar/causal_0_60/` prepares models,
  reference-map ground anchors, and GPU kernels before camera time zero. It
  localized at source t=0.567 s (available wall t=0.724 s) and confirmed camera
  focal calibration at wall t=3.213 s while continuing to navigate.

## 2026-09-10 — Continuous video replay between backend keyframes

- VideoTestPanel now opens with a 1.5s backend keyframe interval, matching the
  intended live-camera request cadence.
- The backend reads native video frames and propagates the latest 2D–3D map
  correspondences with KLT optical flow plus PnP between global localizations.
- The interval control is labeled as a backend keyframe interval; the UI status
  explains that KLT/PnP fills native video frames between requests.

## 2026-09-10 — Test Localize uses the shared new_ar reference scene

- Floor 1 → M21/B now receives the same ground anchors, clipped caret geometry,
  camera payload, and online calibration state used by the causal `new_ar`
  renderer. This removes the previous PoC geometry branch from the parity path.
- The arrival state keeps the final approach arrows for this reference scene, so
  the last seconds match the reference clip instead of clearing the route early.

## 2026-09-10 — Transient localization misses are shown once

- Per-frame `Localization failed` events during initial visual search or a
  keyframe reseed no longer flood the Test Localize log. The panel shows one
  `Finding position` message and keeps the session alive; only errors without a
  frame remain fatal.

## 2026-09-10 — Causal replay status and pose display

- Test Localize now shows the frame currently presented in the video separately
  from the latest frame processed by the backend, so backend progress cannot be
  mistaken for the on-screen video time.
- AR pose selection uses only samples at or before the visible video timestamp;
  it no longer interpolates from a future pose.
- Replay startup/reconnect buffering is now 0.15/0.5 seconds, keeping the
  displayed video and backend processing on the same live-like timeline.
- The replay no longer pauses when the backend briefly falls behind. Video
  playback continues like a live camera while AR holds the latest causal pose
  until a newer update arrives.

## 2026-09-10 — High-FPS replay keeps pace with AR

- The backend now processes source clips above 30 FPS as a continuous 30 FPS
  tracking stream. The video remains at its native presentation rate while
  the overlay receives timestamped causal poses between 1.5s global keyframes.
- Floor5 → Fire Exit 1 uses the same prepared route as the AR scene, so the map
  position, route line, and world-registered chevrons start on the same
  corridor.
- Replay playback now always starts at `0.0s` after the backend has produced a
  small readiness buffer; it no longer seeks past the opening frames to the
  first localization timestamp.
- When a world-registered polygon is temporarily unavailable, the replay now
  shows the route cue from the current causal map pose. World AR takes over
  again automatically as soon as the next valid payload arrives, so a short
  visibility/reseed gap no longer looks like a permanent AR failure.
- The fallback is also allowed when the backend returns an empty world payload,
  preventing an empty `ar_world` object from suppressing both render paths.
## 2026-09-11 — AR visibility rework diagnostics

- World AR now sends only geometry that projects into the current camera frame; off-screen route geometry no longer suppresses the screen guidance fallback.
- Video navigation shows actionable messages for `route_behind_camera` and `tracking_lost`, and labels the backend state as AR payload readiness rather than claiming browser pixels were rendered.
## 2026-09-11 — Remove screen-space AR fallback

- Disabled the stylized map-based fallback chevrons in live camera and video replay AR.
- The overlay now renders only world-registered geometry from `arWorld`; tracking/payload gaps leave the canvas clear.
- Applied the strict setting to live navigation, video replay, and AR Fusion entry points.
- Kept backend reason/status text so `tracking_lost`, `no_ribbon`, off-screen, and behind-camera states remain diagnosable.

## 2026-10-01 — Label image navigation buttons

- Made the previous/next image controls in the Label page toolbar visibly labeled as `ย้อนกลับ` and `ไปข้างหน้า`, with accessible labels and tooltips.
- Kept the shared-coordinate anchor above fanned markers and slightly increased fan spacing as zoom rises, so the original location stays visible instead of being covered.
- Restyled the Label workspace closer to the legacy tool: a compact left image rail, `Stack` and `List` controls, an all-labels picker panel, and a horizontal metadata form with direction, heading, room, group, notes, Delete, Cancel, and Save actions.
- Changed overlapped-point spreading to a triangular fan: two points go left/right, three points form a triangle, and larger stacks fill triangular rows around the original coordinate.
- Kept saved and draft markers at a stable screen size while zooming, preventing enlarged pins from covering each other.
- Increased the marker screen scale slightly after feedback, while shrinking the shared-coordinate anchor to a small zoom-stable ring.
- Increased the triangular fan radius slightly so overlapped markers have a bit more breathing room.
- Increased displayed marker size by 2px and kept the connector line in the same marker layer, while preserving the smaller zoom-stable original-coordinate anchor.
- Added an optional `แม่เหล็ก` snap mode: clicks and drags within 20 screen pixels of another label use its exact x/y, making intentional same-location stacks land on one coordinate.
- Removed the visible `Stack` and `List` toolbar buttons; overlapping coordinate groups now show a zoom-stable `x2`, `x3`, etc. badge directly at the shared point.
- Moved overlap connector lines into a shared floor-plan layer and calculate them from the exact anchor coordinate to each fan point, keeping the circles and lines aligned in one 2D plane.
- Removed the unused Stack/List toolbar controls and their disconnected all-labels overlay from the Label page.
- Removed the direction selector and heading-degree input from the Label form; labels now only require the map position plus the remaining metadata.
- Changed image previous/next controls to icon-only arrow buttons, highlighted the active node with an error-colour ring and warning-orange marker, and used the same orange selection state for multi-select align.
- Moved the align/distribute controls from the page header into the floor-plan toolbar at the bottom.
- Tightened the selected-node red highlight to a small circle directly around the orange point, without ring offset.
- Removed the image position counter from the bottom toolbar.
- Placing a point near an existing label now snaps to that label automatically and turns on the `แม่เหล็ก` state.
- Kept the previous/next arrow controls visible at the left of the bottom toolbar, with stronger contrast and a scroll-safe toolbar layout.
- Removed the heading arrow above the selected node and its drag interaction; selected nodes now show only the small orange point with red circle.
- Reworked the selection highlight as a true small circular border around the marker itself instead of a wrapper ring.
- Turning on `แม่เหล็ก`, or auto-snapping a new point to an existing label, now also turns off visual point spreading so co-located points visibly overlap.
- Dragging an existing point near another label now auto-snaps to the nearby coordinate, updates the draft marker immediately, and enables the magnet state.
- Raised the active node above overlap badges, hid the `x2` badge while editing a point, and collapsed fan spreading when selecting a stacked node so the orange point remains easy to identify.
- Made selected align points use the same marker size and fan offset as normal points; selection now changes only the color and small highlight ring.
- Corrected selection behavior so choosing a point while the fan is visible no longer collapses or repositions the other points; spreading changes only when the user toggles the tool.
- Corrected overlap connector transforms so each line rotates around and stays centered on the marker anchor.
- Reworked connector thickness and offset to place the line center directly through the marker center at every zoom level.
- Attached each overlap connector to its marker's own center instead of drawing one separate anchor layer, keeping alignment stable while zooming.
- Removed inline baseline/line-height space from marker wrappers so connector centers use the exact visual circle box at every zoom level.
- Kept overlap spreading independent from magnet toggles and auto-snapping, cleared align selection on entry, and showed saved nodes as unselected until the user picks them.
- Allowed marker dragging while Hand mode is active; the pointer now drags a node when started on a marker and pans the map when started on empty space, with auto-snap enabled for draft-node drags too.

## 2026-10-01 — Diagnosis map zoom

- Added zoom out, reset percentage, and zoom in controls to the Diagnosis map.
- Added mouse-wheel zoom from 75% to 400% and an internal scroll area so enlarged label positions can be inspected without selecting an image.

## 2026-10-05 — Venue focus button (Siam Discovery floor 3)

- Added floor `floor_siamdis3` (`venue: "siamdis"` in `building.json`, map `siamdis_floor3.png`, graph `siamdis_floor3.json`). Its id starts with `floor` on purpose: `normalizeFloorId` turns a numeric `metadata.floor = 3` into `floor3`, which is the IT building's floor 3.
- New `Focus <floor label>` pill under `Test Localizer` on the map view (only shown when some floor has a `venue`). Pressed state is the accent fill; it toggles back to all floors.
- Focus filters the floor rail, store list and search to that venue, keeps the shown floor inside it, and POSTs `/api/focus` so the backend only ranks/loads floors of that venue (floor auto-detection and the cross-floor retry can no longer jump to the IT building, and a client still sending `floor1` is redirected to the focused floor).
- Focus is remembered in `localStorage` (`wayfindar.focusVenue`) and re-sent to the backend after reload. Backend focus is process-global state, so it is meant for single-tester use.

## 2026-10-06 — Floor plans that are not 500x500

- Cause of the odd Siam Discovery positions: `MapCanvas` stretched every plan to a 500x500 square (`preserveAspectRatio="none"`) while graph nodes, rooms and live poses were divided by a per-payload guess (`round(max / 500)`). A 1430x1100 plan was both distorted and misplaced, and the divisor could differ between two messages for the same floor.
- New `src/lib/mapFrame.ts`: a floor that declares `map_size: [w, h]` in `building.json` gets a frame — one uniform scale (500 / longer side, so headings are preserved) plus an offset that centres the plan in the 500-unit square. Floors without `map_size` keep the old behaviour (500x500, optional integer divisor) unchanged.
- The frame is applied to graph nodes, backend rooms, live `position` / `path` / `transition_target` (by `current_floor`) and the Test Localizer preview (route, pose, destination). `MapCanvas` takes `mapFrame` and draws the plan at its true aspect ratio with a blank band where the square is not covered.
- `floor_siamdis3` declares `map_size: [1430, 1100]` (backend + frontend `building.json`; `/api/floors` returns it as `map_size`). Restart the backend to pick up the config change.
- Not changed: `ArFusionPoc.tsx` and `ARFloorThreeOverlay.tsx` keep their own 500-unit assumptions.

### Follow window for large plans

- Instead of shrinking a large plan to fit 500x500, `MapCanvas` takes `followPose`: it shows a window of 500 source pixels on a side at the plan's true scale and slides it after the pose. The window stays still until the pose is within 35% of its half-extent from an edge, then glides (eased per frame) just far enough to bring the pose back inside; the first fix opens centred on the user.
- The window is clamped to the plan's frame, so it never scrolls into the blank band. Dragging or zooming pauses following until the pose is lost and found again. Plans that already fit in 500 map units are shown whole, so this is a no-op for floors 1-6.
- Enabled in `NavigationView` (both maps) and the Test Localizer preview.

## 2026-10-06 � Siam Discovery Floor 2/3 map refresh

- Added Siam Discovery Floor 2 using the supplied floor plan, graph, and localization data. Both Siam Discovery floor entries now declare their source image dimensions.
- Replaced the Siam Discovery Floor 3 plan and graph with the supplied v4 assets. Installed the new Floor 3 affine alignment matrix from D:\align\result_siam_dis_floor3_2\H_matrix_offset_affine.npy under the runtime matrix filename.
- Backend and frontend system data now carry matching Siam Discovery maps, graphs, and floor configuration.

## 2026-10-07 - Match world AR projection to the displayed video

- World AR scales the backend calibration intrinsics from `ar_world.imgWH` to the video native pixel size before laying out the Three.js camera. This keeps a 1920x1080 clip aligned when localization uses calibration size 1914x1102.
- Recalculates the display intrinsics when video metadata arrives or its native dimensions change, using the same fit mode as the video element.
- Kept the Floor 3 affine matrix: the alignment preview uses the supplied v4 floor plan, and a test frame localized at the matching start point.
