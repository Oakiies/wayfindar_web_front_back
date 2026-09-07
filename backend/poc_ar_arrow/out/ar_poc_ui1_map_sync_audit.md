# UI 1 map popup — timing audit

## Source and output

- Source: `navigate_indoor/uploads/floor5_2.mp4`
- Source video: 1920×1080, 59.94006 FPS, 19,881 frames (~331.63 s)
- Rendered source range: frames 2650–2950 inclusive, step 3
- Source start time: frame 2650 = **44.211 s**
- Output: `ar_poc_ui1_map.avi`, 1800×506, 20 FPS, 101 frames (~5.05 s)
- Output frame 0 = source frame 2650 = source 44.211 s
- Output time starts at 0.000 s; source time remains available separately in
  the metrics CSV.

## First visible map pose

The localizer's EKF needs its initial 3-frame buffer before producing a stable
position. Therefore the first map route and live pose appear at:

- Output frame 2 / output 0.100 s
- Source frame 2656 / source 44.311 s
- Position `(292.2, 289.0)` in Floor 5 map pixels
- Heading `177.2°`

This is expected startup latency, not an offset between the video and map.

## Position and hold behavior

- The popup route is locked from the first valid route calculation.
- The live pose uses the smoothed `(x, y)` from the same source frame being
  written to the output video.
- A localization dropout is held only briefly; after the hold budget the live
  pose is hidden instead of displaying a stale position.
- In this 5-second check, the popup pose is visible for 99/101 output frames.

## Metrics fields

`ar_poc_ui1_map_metrics.csv` includes `source_frame`, `source_t`,
`output_frame`, `output_t`, `x`, `y`, `map_pose_visible`, and `map_heading`.
Use `source_t` when matching the original recording and `output_t` when
scrubbing the generated AVI.

## Turn comparison

`ar_poc_ui1_map_continuous_turn_check_v2.avi` replays the continuous range from
source frame 2650 through 4099. The popup stays in the upper-right corner for
both straight and turn states. The close, camera-off, and map controls sit in
the top chrome above it, matching `frontend-v3/NavigationView`.
