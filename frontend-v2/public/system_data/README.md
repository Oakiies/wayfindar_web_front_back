# system_data

Copied from:
`D:\webanv\web_navigate_indoor_superpoint_superglue`

Included data:
- `config/building.json`
- `map/floor1.jpg` `map/floor2.jpg` `map/floor3.jpg` `map/floor4.jpg` `map/floor5.jpg` `map/floor6.jpg`
- `json_map/floor1.json` `json_map/floor2.json` `json_map/floor3.json` `json_map/floor4.json` `json_map/floor5.json` `json_map/floor6.json`

Notes:
- `json_map` files were slimmed for web usage by removing `graph.metadata.floor_images` (embedded base64 image payload) while preserving graph nodes/edges.
- `floor1` and `floor6` now include graph data for floor switching and route calculation in the web UI.
