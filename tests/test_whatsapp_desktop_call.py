import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Load the plugin
import importlib.util
plugin_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'plugins', 'whatsapp_desktop_call.py'))
spec = importlib.util.spec_from_file_location("whatsapp_desktop_call", plugin_path)
wa_plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa_plugin)

class TestWhatsAppDesktopCall(unittest.TestCase):
    def test_whatsapp_not_running(self):
        with patch.object(wa_plugin.WhatsAppDesktopController, 'is_whatsapp_running', return_value=False):
            res = wa_plugin.run({"intent": "call", "contact_name": "Arun"})
            self.assertIn("not running", res)

    def test_contact_not_found(self):
        with patch.object(wa_plugin, 'WhatsAppDesktopController') as mock_class:
            mock_instance = mock_class.return_value
            mock_instance.is_whatsapp_running.return_value = True
            mock_instance.search_contact.return_value = []
            mock_instance.diagnostic_log = ["UIA working"]
            
            res = wa_plugin.run({"intent": "voice_call", "contact_name": "Ghost"})
            self.assertIn("not found", res)
            mock_instance.open_contact.assert_not_called()

    def test_multiple_matching_contacts(self):
        with patch.object(wa_plugin, 'WhatsAppDesktopController') as mock_class:
            mock_instance = mock_class.return_value
            mock_instance.is_whatsapp_running.return_value = True
            mock_instance.search_contact.return_value = ["Arun 1", "Arun 2"]
            
            res = wa_plugin.run({"intent": "voice_call", "contact_name": "Arun"})
            self.assertIn("Multiple contacts found", res)
            mock_instance.open_contact.assert_not_called()

    def test_voice_call_intent_exact_match(self):
        with patch.object(wa_plugin, 'WhatsAppDesktopController') as mock_class:
            mock_instance = mock_class.return_value
            mock_instance.is_whatsapp_running.return_value = True
            mock_instance.search_contact.return_value = ["arun"]
            mock_instance.open_contact.return_value = True
            mock_instance.start_voice_call.return_value = "SUCCESS_UNVERIFIED"
            mock_instance.diagnostic_log = ["UIA working"]
            
            res = wa_plugin.run({"intent": "voice_call", "contact_name": "arun"})
            self.assertIn("Voice call button click executed", res)
            mock_instance.open_contact.assert_called_once_with("arun", ["arun"])
            mock_instance.start_voice_call.assert_called_once_with("arun")

    def test_end_call_intent(self):
        with patch.object(wa_plugin, 'WhatsAppDesktopController') as mock_class:
            mock_instance = mock_class.return_value
            mock_instance.is_whatsapp_running.return_value = True
            mock_instance.end_call.return_value = True
            
            res = wa_plugin.run({"intent": "end_call"})
            self.assertIn("Successfully executed end_call", res)
            mock_instance.end_call.assert_called_once()

    def test_ambiguous_command(self):
        res = wa_plugin.run({"intent": "random garbage intent"})
        self.assertIn("Ambiguous", res)
        
    def test_tanglish_nlp_mapping(self):
        with patch.object(wa_plugin, 'WhatsAppDesktopController') as mock_class:
            mock_instance = mock_class.return_value
            mock_instance.is_whatsapp_running.return_value = True
            mock_instance.search_contact.return_value = ["amma"]
            mock_instance.open_contact.return_value = True
            mock_instance.start_voice_call.return_value = "SUCCESS_VERIFIED"
            mock_instance.diagnostic_log = ["UIA working"]
            
            res = wa_plugin.run({"intent": "whatsapp la amma ku call pannu"})
            self.assertIn("Successfully initiated voice_call", res)
            mock_instance.search_contact.assert_called_once_with("amma")

    def test_search_diagnostic_intent(self):
        with patch.object(wa_plugin, 'WhatsAppDesktopController') as mock_class:
            mock_instance = mock_class.return_value
            mock_instance.is_whatsapp_running.return_value = True
            mock_instance.search_contact.return_value = ["My World"]
            mock_instance.open_contact.return_value = True
            mock_instance.diagnostic_log = ["Layer 2 (Keyboard) used."]
            
            res = wa_plugin.run({"intent": "whatsapp_search_test", "contact_name": "My World"})
            self.assertIn("Diagnostic Search Test Completed", res)
            self.assertIn("Layer 2 (Keyboard) used.", res)
            mock_instance.start_voice_call.assert_not_called()

    @patch('time.sleep', return_value=None)
    def test_spatial_calculations(self, mock_sleep):
        controller = wa_plugin.WhatsAppDesktopController()
        
        # Mock window and its rect for a 1600x852 window at (0,0)
        from unittest.mock import MagicMock
        mock_window = MagicMock()
        mock_rect = MagicMock()
        mock_rect.left = 0
        mock_rect.top = 0
        mock_rect.right = 1600
        mock_rect.bottom = 852
        mock_window.BoundingRectangle = mock_rect
        
        # Force UIA button to not exist to trigger spatial fallback
        mock_btn = MagicMock()
        mock_btn.Exists.return_value = False
        mock_window.ButtonControl.return_value = mock_btn
        
        controller.window = mock_window
        controller.get_call_state = MagicMock(return_value="UNKNOWN")
        
        with patch.dict('sys.modules', {'pyautogui': MagicMock()}):
            import pyautogui
            
            # Test Voice Call Coordinate Math
            controller.active_contact = "arun"
            res = controller.start_voice_call("Arun")
            pyautogui.click.assert_called_once_with(1452, 70)
            self.assertEqual(res, "SUCCESS_UNVERIFIED")

            # Test Video Call Coordinate Math
            pyautogui.click.reset_mock()
            controller.active_contact = "arun"
            res_video = controller.start_video_call("Arun")
            pyautogui.click.assert_called_once_with(1395, 70)
            self.assertEqual(res_video, "SUCCESS_UNVERIFIED")

if __name__ == '__main__':
    unittest.main()
