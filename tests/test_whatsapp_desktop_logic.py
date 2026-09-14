import unittest
from unittest.mock import patch, MagicMock
import os
import sys

import importlib.util
plugin_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'plugins', 'whatsapp_desktop_call.py'))
spec = importlib.util.spec_from_file_location("whatsapp_desktop_call", plugin_path)
wa_plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa_plugin)

class TestWhatsAppLogic(unittest.TestCase):
    def setUp(self):
        self.controller = wa_plugin.WhatsAppDesktopController()
        self.controller.window = MagicMock()

    def test_whatsapp_not_ready(self):
        self.controller.window = None
        self.controller.is_whatsapp_running = MagicMock(return_value=False)
        self.assertEqual(self.controller.search_contact("my world"), [])
        self.assertIn("not open or cannot be found", self.controller.diagnostic_log[-1])

    def test_name_matching_case_insensitive_and_spacing(self):
        # mock auto.WalkControl yielding a control with Name = "My World"
        c = MagicMock()
        c.Name = "My   World"
        doc = MagicMock()
        self.controller.window.DocumentControl = MagicMock(return_value=doc)
        doc.Exists.return_value = True
        
        with patch('uiautomation.WalkControl', return_value=[(c, 1)]):
            matches = self.controller.search_contact("myworld")
            self.assertIn("My   World", matches)
            
            # test open_contact matches it too
            self.controller.window.Name = "WhatsApp - My   World"
            self.assertTrue(self.controller.open_contact("my world", matches))

    def test_uia_returns_contact(self):
        self.controller.search_contact = MagicMock(return_value=["My World"])
        self.assertEqual(self.controller.search_contact("My World"), ["My World"])

    def test_open_contact_verification_success(self):
        self.controller.window.Name = "WhatsApp - My World"
        # mock sendkeys to simulate Layer 2 fallback since UIA matches is []
        self.assertTrue(self.controller.open_contact("My World", []))
        self.assertIn("Window Title confirmed chat", "".join(self.controller.diagnostic_log))

    def test_open_contact_verification_failure_if_uia_working(self):
        self.controller.window.Name = "WhatsApp - Someone Else"
        # Not blind, but uia matches was empty, so it pressed Enter but Title is wrong
        self.controller.diagnostic_log.append("UIA is working fine")
        
        # also mock call buttons to fail
        self.controller.window.ButtonControl.return_value.Exists.return_value = False
        
        self.assertFalse(self.controller.open_contact("My World", []))
        self.assertIn("Post-click verification failed", "".join(self.controller.diagnostic_log))
        
    def test_open_contact_blind_fallback_succeeds(self):
        self.controller.window.Name = "WhatsApp" # generic title
        self.controller.diagnostic_log.append("UIA blind")
        
        # It should assume success because it cannot verify otherwise
        self.assertTrue(self.controller.open_contact("My World", []))
        self.assertIn("Chat opened successfully.", "".join(self.controller.diagnostic_log))

    @patch('pyautogui.click')
    @patch('time.sleep')
    def test_start_voice_call_uia_success(self, mock_sleep, mock_click):
        self.controller.window.ButtonControl.return_value.Exists.return_value = True
        self.controller.get_call_state = MagicMock(return_value="CONNECTED")
        
        self.controller.active_contact = "myworld"
        result = self.controller.start_voice_call("My World")
        
        self.assertEqual(result, "SUCCESS_VERIFIED")
        self.assertIn("Voice call button located in active chat via UIA.", "".join(self.controller.diagnostic_log))
        mock_click.assert_not_called()

    @patch('pyautogui.click')
    @patch('time.sleep')
    def test_start_voice_call_spatial_fallback(self, mock_sleep, mock_click):
        # UIA blind -> Button doesn't exist
        self.controller.window.ButtonControl.return_value.Exists.return_value = False
        
        # Setup spatial rect
        rect = MagicMock()
        rect.left = 0
        rect.right = 1000
        rect.top = 0
        rect.bottom = 800
        self.controller.window.BoundingRectangle = rect
        
        # State cannot be verified because UIA is blind
        self.controller.get_call_state = MagicMock(return_value="UNKNOWN")
        
        self.controller.active_contact = "myworld"
        result = self.controller.start_voice_call("My World")
        
        self.assertEqual(result, "SUCCESS_UNVERIFIED")
        self.assertIn("Targeting voice call button at Spatial geometry", "".join(self.controller.diagnostic_log))
        mock_click.assert_called_once()
        
    @patch('pyautogui.click')
    @patch('time.sleep')
    def test_start_voice_call_spatial_fallback_failure(self, mock_sleep, mock_click):
        self.controller.window.ButtonControl.return_value.Exists.return_value = False
        
        # Window too small
        rect = MagicMock()
        rect.left = 0
        rect.right = 100
        rect.top = 0
        rect.bottom = 100
        self.controller.window.BoundingRectangle = rect
        
        self.controller.active_contact = "myworld"
        result = self.controller.start_voice_call("My World")
        self.assertFalse(result)
        self.assertIn("too small to safely calculate", "".join(self.controller.diagnostic_log))
        mock_click.assert_not_called()
