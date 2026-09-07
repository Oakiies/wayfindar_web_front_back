# UI refresh (POC)

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
