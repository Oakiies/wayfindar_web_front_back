import unittest
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from poc_cross_camera.render_registration_replay import interpolate_camera


def payload(translation=(0.0, 0.0, 0.0), metres_per_unit=1.0):
    return {
        'R': np.eye(3).tolist(),
        't': list(translation),
        'K': [1000.0, 1000.0, 960.0, 540.0],
        'imgWH': [1920, 1080],
        'metres_per_unit': metres_per_unit,
    }


def sample(timestamp, world=None):
    return {'timestamp': timestamp, 'current_floor': 'floor1', 'method': 'PnP',
            'ar_world': world if world is not None else payload()}


class ReplayGapBridgeTests(unittest.TestCase):
    def test_plausible_three_second_buffered_gap_is_interpolated(self):
        result = interpolate_camera(sample(36.02), sample(39.02, payload((-3, 0, 0))), 37.52)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['t'][0], -1.5)

    def test_implausible_speed_is_rejected(self):
        result = interpolate_camera(sample(0), sample(3, payload((-20, 0, 0))), 1.5)
        self.assertIsNone(result)

    def test_gap_beyond_replay_budget_is_rejected(self):
        self.assertIsNone(interpolate_camera(sample(0), sample(3.2), 1.0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
