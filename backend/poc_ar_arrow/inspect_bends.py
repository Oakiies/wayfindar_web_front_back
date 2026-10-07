"""One-off: print the raw path_coords and detected bend events for the m21
route, to see the actual polyline geometry behind the 27s gentle_corridor
freeze found in DIAGNOSIS_ar_m21_walk.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.floor_service import initialize_system, set_active_floor  # noqa: E402
from app.services.nav_service import compute_navigation_route              # noqa: E402
from app.core import navigation as nav                                      # noqa: E402
from poc_ar_arrow.ar_arrow_v2 import _route_progress_and_bends, route_guidance_mode  # noqa: E402

initialize_system()
floor = set_active_floor('floor1')

samples = [
    (19.512, 311.9, 193.8),
    (25.517, 305.3, 223.8),
    (36.02, 324.5, 302.5),
    (49.527, 335.4, 347.5),
]

route_info = compute_navigation_route(floor, samples[0][1], samples[0][2], 'm21', floor)
path_coords = route_info['path_coords']
print(f"path_coords ({len(path_coords)} pts):")
for p in path_coords:
    print(f"  ({p[0]:.1f}, {p[1]:.1f})")

path = nav.simplify_collinear(nav._strip_start_stub(path_coords))
print(f"\nsimplified path ({len(path)} pts):")
for p in path:
    print(f"  ({p[0]:.1f}, {p[1]:.1f})")

progress, bends = _route_progress_and_bends(samples[0][1], samples[0][2], path_coords)
print(f"\nbend events ({len(bends)}):")
for b in bends:
    print(f"  progress={b['progress']:.1f}px  angle={b['angle']:.1f} deg")

print("\nper-sample guidance_mode:")
for t, x, y in samples:
    mode, bend = route_guidance_mode(x, y, path_coords)
    progress, _ = _route_progress_and_bends(x, y, path_coords)
    print(f"  t={t:6.2f} pos=({x:.1f},{y:.1f}) progress={progress:.1f}px mode={mode} bend={bend:.1f}")
