import unittest
from unittest.mock import Mock
from backend.api.server import ControllerApplication
from backend.infrastructure.real_track import Z21TrackSystem
from backend.infrastructure.interfaces import CommandResult


class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.app = ControllerApplication.sample()

    def tearDown(self):
        self.app.close()

    def test_manual_stopped_train_changes_simulator_direction(self):
        self.app.command({'type': 'set_direction', 'train_id': 'train-3', 'direction': 'reverse'})
        train = next(t for t in self.app.runtime.track.get_snapshot().trains if t.train_id == 'train-3')
        self.assertEqual(train.direction, -1)
        self.assertEqual(train.target_speed, 0)
        self.assertEqual(next(t for t in self.app.trains if t['id'] == 'train-3')['direction'], 'reverse')

    def test_automatic_and_moving_and_invalid_rejected(self):
        for train, direction in [('train-101', 'reverse'), ('train-3', 'sideways')]:
            with self.assertRaises(ValueError):
                self.app.command({'type': 'set_direction', 'train_id': train, 'direction': direction})
        self.app.command({'type': 'set_speed', 'train_id': 'train-3', 'speed': 20})
        with self.assertRaises(ValueError):
            self.app.command({'type': 'set_direction', 'train_id': 'train-3', 'direction': 'reverse'})

    def test_ui_uses_actual_direction_after_layout_reload(self):
        self.app.command({'type': 'set_direction', 'train_id': 'train-3', 'direction': 'reverse'})
        self.app.save_layout('direction-test')
        self.app.load_layout('direction-test')
        train = next(t for t in self.app._ui_trains() if t['number'] == '3')
        self.assertEqual(train['direction'], 'Reverse')

    def test_drive_cannot_bypass_direction_guard(self):
        with self.assertRaises(ValueError):
            self.app.command({'type': 'drive', 'train_id': 'train-101', 'speed': 70, 'direction': 'reverse'})

    def test_z21_zero_speed_direction_and_rejection(self):
        transport = Mock()
        transport.send_dataset.return_value = CommandResult(True, 'drive', '')
        track = Z21TrackSystem(transport, train_addresses={'test': 3})
        track.set_train_direction('test', forward=False)
        packet = transport.send_dataset.call_args.args[0]
        self.assertEqual(packet[-2], 0)
        track.set_train_speed('test', .5)
        self.assertLess(transport.send_dataset.call_args.args[0][-2], 128)
        transport.send_dataset.return_value = CommandResult(False, 'drive', 'offline')
        self.assertFalse(track.set_train_direction('test', forward=True).accepted)
        self.assertFalse(track._train_directions['test'])
