# PoC — floor-glued AR arrow (v2)

Candidate replacement for the shipping AR chevron trail, plus the harness that
judges it against a real walk. Nothing here is wired into the app: `app/` is
untouched, and this folder imports from it.

## Why

Three complaints, and what each one turned out to be:

| Complaint | Cause found in the shipping overlay |
|---|---|
| "ลอย ๆ ไม่แนบพื้น" | The trail is a set of *isolated* carets. Nothing connects them to the ground between markings, so the eye reads them as cards hovering in mid-air even though the geometry is correctly on the floor plane. |
| "เข้าใกล้แล้วควรใหญ่ขึ้น" | The arrow *is* a fixed size in metres, so projection does grow it — but `ar_service._depth_alpha` fades it to zero below 3.4 m and it is fully invisible by 3.4 m. It is never seen at the size that would sell the effect. |
| "AR ไม่เสถียร / แกว่ง" | Every frame registers the overlay with that frame's **raw PnP pose**. Pose noise rotates the whole world under the trail. Nothing smooths R/t — only the map position is smoothed. |

## What v2 does

- **Continuous ribbon on the floor** through the same route stations, with the
  carets painted on top of it. A surface running unbroken from the walker's feet
  into the distance is the strongest available ground-contact cue.
- **Full opacity down to 1.6 m**, letting the frame edge remove a marking as it
  passes underfoot — so the nearest arrow is also the biggest one.
- **`PoseStabilizer`**: EMA on camera centre + rotation with a hold for
  implausible jumps, so residual movement is real movement.
- **3D near-plane clipping of the ribbon.** A strip is one polygon; a single
  vertex behind the camera projects to a wild coordinate and smears the fill
  across half the screen. The centre line is clipped in camera space *before*
  being given width.
- **Corner trim measured from the walker.** The shipping overshoot of two
  stations past a turn is invisible as floating carets but reads as a lane
  painted through a wall once it is a filled surface.

Anchor layout, the H_matrix inverse, the floor plane and the metres-per-world-unit
scale all still come from `app.services.ar_service` / `app.core.ar_geometry` —
only the parts under test differ.

## Run

```bash
cd backend
.venv/Scripts/python.exe poc_ar_arrow/render_poc.py                       # full segment
.venv/Scripts/python.exe poc_ar_arrow/render_poc.py --start 2760 --end 2830   # quick look
```

Clip: `navigate_indoor/uploads/floor5_2.mp4`, floor5, destination **510**,
frames 2650–4250 at step 3 (~20 AR updates/s) — the same walk and destination
the upstream AR work was validated on.

Outputs land in `poc_ar_arrow/out/`:

- `ar_poc_ui1_map.avi` — side-by-side, shipping left / v2 right, with the same
  square map popup on both panes. It stays top-right for the entire navigation
  run, below the AR controls. The popup uses style 1: one blue
  accent, dotted trail + white casing, radar sector, origin ring, and red pin.
- The AR preview chrome mirrors `frontend-v3/NavigationView`: close (top-left),
  camera-off (top-right), and map (top-right).
- `ar_poc_ui1_map_metrics.csv` — per-frame position, map heading, map visibility,
  and explicit source/output timing fields.

The first successful localization locks the full route shown in the popup.
The live dot uses the smoothed `(x, y)` from that exact source frame; after a
short localization gap it is hidden instead of showing a stale position. For
sync, output time `0.000s` maps to source frame `2650` (`44.211s`) by default.
The CSV keeps both `source_t` and `output_t`, so a frame can be checked against
the original recording without guessing.

## Destination marker

The marker was three unrelated pieces: an axis-aligned translucent quad on the
floor, a straight 5 px stem, and a hand-built diamond with a `HERSHEY` caption
in a black box - none of it anti-aliased, while the direction cards beside it
were already supersampled through PIL. It read as three stickers, not as a place.

It is now one object seen in perspective:

| part | what changed |
|---|---|
| floor | a real circle on the floor plane, projected - it lands as an ellipse that leans with the floor instead of a rectangle pasted flat on the screen. Two rings and a bullseye. |
| stem | tapered, wide at the floor and narrow at the head, the way a vertical post reads in perspective. |
| head | a true teardrop: a circle closed by its own tangent lines, the same construction `MapCanvas.tsx` uses for the map pin, so the AR marker and the map marker are the same shape. |
| label | the direction card's pill - near-white, hairline outline, soft shadow, real type - carrying the destination name and the distance left. |

Colour comes from the app's palette rather than a new one: `#e5484d` on the
approach, `#22c55e` with the lucide check on arrival. AR and map now name the
destination in the same colour.

Two things are deliberately not world-anchored. The head slides down its own
stem once the projected stem passes `PIN_STEM_MAX` of the frame height - at two
metres away a 1.15 m post projects to most of the screen and reads as a
lamppost; the ring on the floor is the part that has to stay registered, and the
head is a label for it. The label pill is screen-space and clamped into view.

Everything is drawn into one small RGBA tile at `PIN_SS` and downsampled once,
so the marker is anti-aliased without supersampling the frame.

## Restyling it without re-running the walk

`render_poc.py` writes the first pin pose it draws to `out/pin_pose.npz` and
`out/pin_pose_frame.png`. Replay that pose:

```bash
cd backend
.venv/Scripts/python.exe poc_ar_arrow/preview_destination_pin.py   # -> out/destination_pin_preview.png
```

It renders the approach, near and arrived states side by side in about a second
instead of after a localization pass. It is also the only way to see the
approach state on this clip: the pin only becomes visible once `arrived` is
already true, because the payload it needs has no anchors earlier in the walk.

## Metrics

`probe jitter` is the honest stability number. It takes one point **fixed in the
building** (a route point at a constant arc length), projects it through each
frame's pose, and reports the median second difference in pixels:

```
| p[i+1] - 2·p[i] + p[i-1] |
```

Any smooth walk gives ~0 here regardless of speed, so what is left is pose
error — the swing being complained about. It is reported for the raw pose (what
ships) and the stabilized pose (what v2 uses).

## Known limits

- The overlay has **no occlusion model**: it cannot know a wall is in front of
  the floor it is painting. The corner trim is a heuristic standing in for that.
- `M_PER_PX` and `CAMERA_HEIGHT_M` are dataset constants. A phone held much
  higher or lower than 1.5 m shifts the floor plane and the whole trail with it.
- The jitter probe measures pose stability, not absolute accuracy. A pose that
  is consistently 30 cm off scores perfectly here and still paints the lane 30 cm
  off the walkway; that part is judged from the video.
