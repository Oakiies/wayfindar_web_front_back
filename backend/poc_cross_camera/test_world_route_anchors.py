"""A stationary world route must not move when the camera moves sideways."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.ar_service import chevron_anchors


class WorldRouteAnchorTests(unittest.TestCase):
    def test_sideways_camera_motion_does_not_translate_route(self):
        route = [(0, 0), (0, 180)]
        a = chevron_anchors(-4, 20, route, recenter=False)
        b = chevron_anchors(6, 20, route, recenter=False)
        self.assertTrue(a)
        self.assertEqual(a, b)

    def test_forward_motion_preserves_shared_station_positions(self):
        route = [(0, 0), (0, 180)]
        a = chevron_anchors(-4, 20, route, recenter=False)
        b = chevron_anchors(6, 35, route, recenter=False)
        self.assertTrue(set(a) & set(b))
        self.assertTrue(set(b).issubset(set(a)))

    def test_corner_stations_are_not_dragged_sideways(self):
        route = [(0, 0), (0, 60), (80, 60)]
        for x in (-4, 6):
            anchors = chevron_anchors(x, 20, route, recenter=False)
            self.assertTrue(anchors)
            self.assertTrue(all(abs(px) < 1e-8 or abs(py-60) < 1e-8 for px, py in anchors))

    def test_legacy_recenter_is_explicitly_preserved(self):
        route = [(0, 0), (0, 180)]
        self.assertNotEqual(chevron_anchors(-4,20,route), chevron_anchors(6,20,route))


if __name__ == '__main__':
    unittest.main(verbosity=2)
