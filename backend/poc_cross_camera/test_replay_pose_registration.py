"""Run without loading localization models; execute the real adapter functions.

AST isolation removes application startup imports only, not function bodies.
The builder is injected so the tests can inspect the camera-policy boundary.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

BACKEND = Path(__file__).resolve().parents[1]


def load_functions(relative_path, names, namespace):
    tree = ast.parse((BACKEND / relative_path).read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(tree, relative_path, 'exec'), namespace)
    return namespace


class ReplayRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.builder = Mock(return_value={'R': np.eye(3), 't': [0, 0, 0]})
        self.functions = load_functions('app/services/video_processor.py',
            {'_ar_world', '_ar_world_or_hold', '_is_implausible_visual_jump'},
            {'ar_service': SimpleNamespace(build_ar_world_poc=self.builder),
             '_ar_debug': Mock(), 'math': __import__('math'),
             'VISUAL_JUMP_MIN_PX': 28, 'VISUAL_MAX_SPEED_PX_PER_SECOND': 18})
        self.session = SimpleNamespace(ar_hold={'payload': {'old': True}, 'ts': 0})

    def test_current_camera_and_quality_pass_through_without_ema(self):
        pose = {'R': np.eye(3), 't': np.array([1., 2., 3.])}
        result = self.functions['_ar_world'](self.session, object(), 'floor1',
            pose, 10, 20, [(10, 20), (30, 40)], 40, (1920, 1080), 2.5)
        args = self.builder.call_args.args
        self.assertIs(args[2], pose)
        self.assertEqual(args[6:9], (40, (1920, 1080), 2.5))
        self.assertIsNone(args[9])
        self.assertTrue(self.builder.call_args.kwargs['pin_route'])
        self.assertIs(result, self.builder.return_value)

    def test_dropout_does_not_draw_old_camera_even_after_one_frame(self):
        result = self.functions['_ar_world_or_hold'](self.session, .033, None)
        self.assertIsNone(result)
        self.assertIsNone(self.session.ar_hold)

    def test_reacquisition_uses_new_payload(self):
        fresh = {'R': 'new camera'}
        self.assertIs(self.functions['_ar_world_or_hold'](self.session, 2, fresh), fresh)

    def test_builder_failure_hides_ar(self):
        self.builder.side_effect = ValueError('invalid pose')
        self.assertIsNone(self.functions['_ar_world'](
            self.session, None, 'floor1', {}, 0, 0, [], 0))

    def test_visual_jump_gate_still_rejects_outlier(self):
        gate = self.functions['_is_implausible_visual_jump']
        fix = {'timestamp': 0, 'raw_x': 0, 'raw_y': 0}
        self.assertTrue(gate(fix, 86, 0, 1.5))
        self.assertFalse(gate(fix, 10, 0, 1.5))

    def test_synthetic_turn_demonstrates_old_camera_registration_error(self):
        old = load_functions('poc_ar_arrow/ar_arrow_v2.py', {'PoseStabilizer'},
                             {'np': np, 'cv2': cv2, 'math': __import__('math')})
        smoother = old['PoseStabilizer'](alpha=.24, turn_alpha=.5,
            turn_follow_deg=6, expected_interval_s=1.5)
        smoother.update(np.eye(3), np.zeros(3))
        rotation = cv2.Rodrigues(np.array([0., np.deg2rad(20), 0.]))[0]
        filtered, _ = smoother.update(rotation, np.zeros(3))
        point = np.array([0., 0., 8.])
        def screen_x(r):
            p = r @ point
            return 1400 * p[0] / p[2]
        error = abs(screen_x(filtered) - screen_x(rotation))
        self.assertGreater(error, 250)
        print(f'Synthetic 20-degree turn: old EMA projection error={error:.2f}px; '
              'unfiltered camera error=0px (not a video accuracy metric)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
