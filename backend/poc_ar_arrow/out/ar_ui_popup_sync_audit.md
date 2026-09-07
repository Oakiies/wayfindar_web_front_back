# AR popup sync audit

Files checked:

- Source/replay clip: `ar_poc_v37_superpoint_lightglue_megaloc.avi`
- Popup preview: `ar_ui_popup_preview_5s_synced_v2.mp4`
- Localization metrics: `ar_poc_metrics_v37_superpoint_lightglue_megaloc_from_start_to_destination.csv`

## Timeline mapping

The source clip and popup preview are both 20 FPS. The metrics were recorded
at 60 FPS and contain every third frame, so the correct mapping is:

`preview_frame = metric_frame / 3`

Equivalently, at preview frame `n`, read metrics frame `n * 3`.

| Clip time | Preview frame | Metrics frame | Position `(x, y)` | Localization state |
|---:|---:|---:|---:|---|
| 0.00 s | 0 | 0 | unavailable | no_fix |
| 0.05 s | 1 | 3 | unavailable | no_fix |
| 0.10 s | 2 | 6 | `(286.0, 458.9)` | no_ribbon |
| 1.00 s | 20 | 60 | `(286.4, 459.2)` | no_ribbon |
| 3.00 s | 60 | 180 | `(289.6, 460.2)` | ok |
| 4.95 s | 99 | 297 | `(291.6, 463.9)` | hold_no_ribbon |

## Conclusion

The corrected `synced_v2` preview is timestamp-aligned. However, the
localization data itself moves only about 5.6 map pixels in X and 5.0 pixels
in Y during the first 4.85 seconds. Therefore the user marker should remain
near the starting point in this section of the clip.

The first two frames have no measured position. The production live UI keeps
the marker hidden until the first live position arrives; a preview should do
the same if it needs to represent the no-fix state exactly.
