import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import time

# Load the plugin
import importlib.util
plugin_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'plugins', 'ky_ufo_drone.py'))
spec = importlib.util.spec_from_file_location("ky_ufo_drone", plugin_path)
ky_ufo_drone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ky_ufo_drone)

class TestKYUFODrone(unittest.TestCase):
    def setUp(self):
        # Reset controller state
        ky_ufo_drone._controller = ky_ufo_drone.StandaloneDroneController(mode="REAL")

    def tearDown(self):
        if ky_ufo_drone._controller:
            ky_ufo_drone._controller._stop_hover()

    def test_default_mode_is_real(self):
        self.assertEqual(ky_ufo_drone._controller.mode, "REAL")

    @patch('socket.socket')
    @patch('time.sleep') # mock sleep to avoid 4s wait in tests
    def test_takeoff_triggers_calibration_and_countdown(self, mock_sleep, mock_socket):
        mock_player = MagicMock()
        res_str = ky_ufo_drone.run({"intent": "take off", "confirm_physical": True}, player=mock_player)
        
        # Verify socket was called for calibration AND takeoff (2 times total before hover kicks in)
        self.assertGreaterEqual(mock_socket.return_value.sendto.call_count, 2)
        
        # Check that calibration packet was sent
        calib_packet = bytes.fromhex("03 66 14 80 80 80 80 04 02 00 00 00 00 00 00 00 00 00 00 06 99")
        mock_socket.return_value.sendto.assert_any_call(calib_packet, ('192.168.1.1', 7099))
        
        # Check that takeoff packet was sent
        takeoff_packet = bytes.fromhex("03 66 14 80 80 80 80 01 02 00 00 00 00 00 00 00 00 00 00 03 99")
        mock_socket.return_value.sendto.assert_any_call(takeoff_packet, ('192.168.1.1', 7099))
        
        # Verify output text and state
        self.assertIn("Transmission: True", res_str)
        self.assertIn("AIRBORNE", res_str)
        
        # Verify hover thread is running
        self.assertTrue(ky_ufo_drone._controller.state["hovering"])
        self.assertIsNotNone(ky_ufo_drone._controller._hover_thread)
        
    @patch('socket.socket')
    @patch('time.sleep')
    def test_land_stops_hover(self, mock_sleep, mock_socket):
        # First takeoff
        ky_ufo_drone.run({"intent": "take off", "confirm_physical": True})
        self.assertTrue(ky_ufo_drone._controller.state["airborne"])
        
        # Then land
        res_str = ky_ufo_drone.run({"intent": "land", "confirm_physical": True})
        self.assertIn("GROUNDED", res_str)
        self.assertFalse(ky_ufo_drone._controller.state["airborne"])
        self.assertFalse(ky_ufo_drone._controller.state["hovering"])
        self.assertIsNone(ky_ufo_drone._controller._hover_thread)

    @patch('socket.socket')
    def test_no_automatic_takeoff_at_startup(self, mock_socket):
        res_str = ky_ufo_drone.run({"intent": "status"})
        self.assertIn("GROUNDED", res_str)
        mock_socket.assert_not_called()
        self.assertFalse(ky_ufo_drone._controller.state["airborne"])

if __name__ == "__main__":
    unittest.main()
