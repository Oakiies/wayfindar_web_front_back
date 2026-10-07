"""Regression tests for shallow corridor guidance semantics."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poc_ar_arrow.ar_arrow_v2 import route_guidance_mode


class GuidanceModeTests(unittest.TestCase):
    def test_shallow_chamfer_is_continuous_corridor(self):
        mode, bend = route_guidance_mode(
            0.0,
            80.0,
            [(0.0, 0.0), (0.0, 100.0), (25.0, 159.0), (25.0, 240.0)],
        )
        self.assertEqual(mode, "gentle_corridor")
        self.assertGreater(bend, 7.0)
        self.assertLess(bend, 30.0)

    def test_ninety_degree_junction_keeps_directional_cue(self):
        mode, _ = route_guidance_mode(
            0.0,
            70.0,
            [(0.0, 0.0), (0.0, 100.0), (100.0, 100.0)],
        )
        self.assertEqual(mode, "directional")

    def test_real_m21_chamfer_stays_continuous_before_during_and_after_bend(self):
        path = [
            (313.0, 146.0),
            (313.0, 215.0),
            (313.0, 253.0),
            (338.0, 312.0),
            (338.0, 333.0),
            (338.0, 351.0),
            (338.0, 378.8486562942009),
            (338.0, 391.0),
            (338.0, 408.0),
        ]
        # Cached replay positions from the graph/map comparison. The old
        # short look-ahead classifier oscillated back to `directional` at the
        # middle and exit of this shallow two-vertex chamfer.
        positions = [
            (304.23, 216.12),
            (308.34, 255.60),
            (319.20, 291.30),
            (333.70, 310.30),
            (335.40, 347.50),
        ]
        for position in positions:
            with self.subTest(position=position):
                mode, bend = route_guidance_mode(*position, path)
                self.assertEqual(mode, "gentle_corridor")
                self.assertGreaterEqual(bend, 7.0)

    def test_straight_section_far_beyond_chamfer_restores_directional_cue(self):
        path = [
            (0.0, 0.0),
            (0.0, 100.0),
            (25.0, 159.0),
            (25.0, 300.0),
        ]
        mode, _ = route_guidance_mode(25.0, 260.0, path)
        self.assertEqual(mode, "directional")


if __name__ == "__main__":
    unittest.main(verbosity=2)
