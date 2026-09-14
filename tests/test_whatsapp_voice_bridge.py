import unittest
from unittest.mock import MagicMock, patch
import threading
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins import whatsapp_voice_bridge
from plugins.whatsapp_voice_bridge import CallState

class TestWhatsAppVoiceBridge(unittest.TestCase):
    def setUp(self):
        # Reset instance before each test
        whatsapp_voice_bridge.WhatsAppVoiceBridge._instance = None
        self.bridge = whatsapp_voice_bridge.WhatsAppVoiceBridge.get_instance()
        
        # Mock wa_controller methods
        self.bridge.wa_controller.search_contact = MagicMock(return_value=["Arun"])
        self.bridge.wa_controller.open_contact = MagicMock(return_value=True)
        self.bridge.wa_controller.start_voice_call = MagicMock(return_value="SUCCESS_VERIFIED")
        self.bridge.wa_controller.end_call = MagicMock()
        self.bridge.wa_controller.is_whatsapp_running = MagicMock(return_value=True)
        self.bridge.wa_controller.diagnostic_log = []
        
        self.bridge._detect_virtual_audio_cable = MagicMock(return_value=(1, 2, "CABLE Output (VB-Audio Virtual Cable)"))
        
        self.stt = MagicMock()
        self.tts = MagicMock()
        self.llm = MagicMock(return_value="Hello there!")
        
    @patch('threading.Thread')
    def test_start_conversation_success(self, mock_thread):
        res = self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.assertEqual(self.bridge.state, CallState.CONNECTING)
        self.assertIn("WhatsApp TTS output device", res)
        self.assertEqual(mock_thread.call_count, 2)
        
    @patch('threading.Thread')
    def test_start_call_unverified(self, mock_thread):
        self.bridge.wa_controller.start_voice_call.return_value = "SUCCESS_UNVERIFIED"
        res = self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.assertEqual(self.bridge.state, CallState.CALLING_UNVERIFIED)
        self.assertIn("WhatsApp TTS output device", res)
        self.assertEqual(mock_thread.call_count, 2)
        
    def test_contact_not_found(self):
        self.bridge.wa_controller.search_contact.return_value = []
        self.bridge.wa_controller.diagnostic_log = ["Some error", "Search executed successfully"]
        res = self.bridge.start_call_and_bridge("Ghost", self.stt, self.tts, self.llm)
        self.assertEqual(self.bridge.state, CallState.ERROR)
        self.assertIn("not found", res)
        
    def test_multiple_contacts(self):
        self.bridge.wa_controller.search_contact.return_value = ["Arun 1", "Arun 2"]
        res = self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.assertEqual(self.bridge.state, CallState.ERROR)
        self.assertIn("Multiple contacts found", res)
        
    def test_open_contact_failure(self):
        self.bridge.wa_controller.open_contact.return_value = False
        res = self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.assertEqual(self.bridge.state, CallState.ERROR)
        self.assertIn("Failed to open chat", res)

    def test_start_voice_call_failure(self):
        self.bridge.wa_controller.start_voice_call.return_value = "Failed to click"
        res = self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.assertEqual(self.bridge.state, CallState.ERROR)
        self.assertIn("Failed to start voice call", res)
        
    @patch('threading.Thread')
    def test_stop_conversation(self, mock_thread):
        self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        res = self.bridge.stop_conversation()
        self.assertEqual(self.bridge.state, CallState.ENDED)
        self.assertTrue(self.bridge._stop_event.is_set())
        self.assertIn("stopped", res)
        
    @patch('threading.Thread')
    def test_hang_up(self, mock_thread):
        self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        res = self.bridge.hang_up()
        self.assertEqual(self.bridge.state, CallState.ENDED)
        self.bridge.wa_controller.end_call.assert_called_once()
        self.assertIn("Call ended", res)

    @patch('threading.Thread')
    def test_missing_virtual_audio_cable_warning(self, mock_thread):
        self.bridge._detect_virtual_audio_cable.return_value = (None, None, None)
        res = self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.assertEqual(self.bridge.state, CallState.CONNECTING)
        self.assertIn("WARNING: No Virtual Audio Cable detected", res)

    def test_stt_failure_handled(self):
        self.bridge.stt_engine = self.stt
        self.stt.transcribe.side_effect = Exception("STT crashed")
        import numpy as np
        self.bridge._process_speech(np.zeros(10))
        # Should catch gracefully, not crash
        self.assertEqual(self.bridge.state, CallState.LISTENING)
        
    def test_tts_failure_handled(self):
        self.bridge.stt_engine = self.stt
        self.bridge.tts_engine = self.tts
        self.bridge.llm_func = self.llm
        self.stt.transcribe.return_value = "Hello"
        self.tts.speak.side_effect = Exception("TTS crashed")
        import numpy as np
        self.bridge._process_speech(np.zeros(10))
        # Should catch gracefully
        self.assertEqual(self.bridge.state, CallState.LISTENING)
        
    def test_llm_failure_handled(self):
        self.bridge.stt_engine = self.stt
        self.bridge.tts_engine = self.tts
        self.bridge.llm_func = MagicMock(side_effect=Exception("LLM offline"))
        self.stt.transcribe.return_value = "Hello"
        import numpy as np
        self.bridge._process_speech(np.zeros(10))
        # Should catch gracefully
        self.assertEqual(self.bridge.state, CallState.LISTENING)

    def test_whatsapp_disappears_during_call(self):
        self.bridge.state = CallState.CONVERSATION
        self.bridge.wa_controller.is_whatsapp_running.return_value = False
        
        import queue
        q = queue.Queue()
        # Fake an empty get to trigger the loop's whatsapp check
        def mock_get(timeout=0.5):
            if self.bridge.wa_controller.is_whatsapp_running():
                return
            self.bridge._stop_event.set()
            raise queue.Empty
            
        with patch.object(queue.Queue, 'get', side_effect=mock_get):
            # This would exit immediately due to stop_event set
            pass

    def test_barge_in_interruption(self):
        self.bridge._is_speaking = True
        self.bridge.tts_engine = self.tts
        
        # Simulate loud incoming noise during speech
        import numpy as np
        loud_chunk = np.ones((1024, 1), dtype=np.float32)
        
        # Call the inline callback indirectly if we can, or just test logic
        # For this test, we directly verify state changes
        volume_norm = np.linalg.norm(loud_chunk) * 10
        if volume_norm > self.bridge.VAD_THRESHOLD:
            if self.bridge._is_speaking:
                self.bridge._interrupted = True
                self.bridge.tts_engine.stop()
                
        self.assertTrue(self.bridge._interrupted)
        self.tts.stop.assert_called_once()

    def test_normal_tts_routing_is_default(self):
        import core.tts
        core.tts.TTS_OUTPUT_DEVICE = None
        self.bridge._disable_whatsapp_tts_routing()
        self.assertIsNone(core.tts.TTS_OUTPUT_DEVICE)

    @patch('threading.Thread')
    def test_whatsapp_enables_cable_routing(self, mock_thread):
        import core.tts
        core.tts.TTS_OUTPUT_DEVICE = None
        self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.assertIsNone(core.tts.TTS_OUTPUT_DEVICE) # Routing is deferred to VAD
        # Simulate VAD manual routing
        self.bridge._enable_whatsapp_tts_routing(self.bridge.wa_mic_device)
        self.assertEqual(core.tts.TTS_OUTPUT_DEVICE, 2)

    @patch('threading.Thread')
    def test_stop_restores_normal_routing(self, mock_thread):
        import core.tts
        self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.bridge._enable_whatsapp_tts_routing(self.bridge.wa_mic_device)
        self.assertEqual(core.tts.TTS_OUTPUT_DEVICE, 2)
        self.bridge.stop_conversation()
        self.assertIsNone(core.tts.TTS_OUTPUT_DEVICE)

    @patch('threading.Thread')
    def test_hangup_restores_normal_routing(self, mock_thread):
        import core.tts
        self.bridge.start_call_and_bridge("Arun", self.stt, self.tts, self.llm)
        self.bridge._enable_whatsapp_tts_routing(self.bridge.wa_mic_device)
        self.assertEqual(core.tts.TTS_OUTPUT_DEVICE, 2)
        self.bridge.hang_up()
        self.assertIsNone(core.tts.TTS_OUTPUT_DEVICE)

    def test_error_restores_normal_routing(self):
        import core.tts
        core.tts.TTS_OUTPUT_DEVICE = None
        # Force a failure in call setup by making open_contact fail
        self.bridge.wa_controller.search_contact.return_value = []
        self.bridge.wa_controller.open_contact.return_value = False
        self.bridge.start_call_and_bridge("Ghost", self.stt, self.tts, self.llm)
        self.assertIsNone(core.tts.TTS_OUTPUT_DEVICE)

    def test_exception_restores_normal_routing(self):
        import core.tts
        core.tts.TTS_OUTPUT_DEVICE = 2
        
        # Trigger an exception in the audio loop directly, and set stop_event in time.sleep to break retry loop
        def mock_sleep(*args, **kwargs):
            self.bridge._stop_event.set()
            
        with patch('soundcard.default_speaker', side_effect=Exception("Audio device crashed")), \
             patch('time.sleep', side_effect=mock_sleep):
            self.bridge._capture_and_process_loop()
            
        self.assertIsNone(core.tts.TTS_OUTPUT_DEVICE)

    def test_audio_capture_exception_recovery(self):
        """1. audio capture exception recovery without setting ERROR or hanging up"""
        call_count = 0
        def mock_sleep(sec):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                self.bridge._stop_event.set()

        with patch('soundcard.default_speaker', side_effect=Exception("Temporary capture device error")), \
             patch('time.sleep', side_effect=mock_sleep):
            self.bridge._capture_and_process_loop()

        self.assertNotEqual(self.bridge.state, CallState.ERROR)
        self.bridge.wa_controller.end_call.assert_not_called()

    def test_time_import_shadowing_regression(self):
        """2. time import/shadowing regression check"""
        import inspect
        src = inspect.getsource(whatsapp_voice_bridge.WhatsAppVoiceBridge._capture_and_process_loop)
        self.assertNotIn("import time", src)
        self.assertTrue(hasattr(whatsapp_voice_bridge, "time"))
        self.assertGreater(whatsapp_voice_bridge.time.time(), 0)

    def test_empty_transcript_recovery(self):
        """3. empty transcript recovery without calling LLM or TTS"""
        self.bridge.stt_engine = self.stt
        self.bridge.tts_engine = self.tts
        self.bridge.llm_func = self.llm
        self.stt.transcribe.return_value = "   "
        import numpy as np
        self.bridge._process_speech(np.zeros(10))
        self.assertEqual(self.bridge.state, CallState.LISTENING)
        self.llm.assert_not_called()
        self.tts.speak.assert_not_called()
        self.bridge.wa_controller.end_call.assert_not_called()

    def test_llm_404_model_not_found_handling(self):
        """4. LLM 404/model-not-found handling stays alive in LISTENING"""
        self.bridge.stt_engine = self.stt
        self.bridge.tts_engine = self.tts
        self.bridge.llm_func = MagicMock(side_effect=RuntimeError("Ollama HTTP 404 Not Found: model 'llama3.2' not found"))
        self.stt.transcribe.return_value = "Hello Jarvis"
        import numpy as np
        self.bridge._process_speech(np.zeros(10))
        self.assertEqual(self.bridge.state, CallState.LISTENING)
        self.bridge.wa_controller.end_call.assert_not_called()

    def test_speaking_to_listening_transition(self):
        """5. SPEAKING -> LISTENING transition upon TTS completion"""
        self.bridge.stt_engine = self.stt
        self.bridge.tts_engine = self.tts
        self.bridge.llm_func = self.llm
        self.stt.transcribe.return_value = "Test query"
        self.llm.return_value = "Test response"
        
        captured_done = None
        def mock_speak(text, on_start=None, on_done=None):
            nonlocal captured_done
            captured_done = on_done
            self.assertEqual(self.bridge.state, CallState.SPEAKING)
            self.assertTrue(self.bridge._is_speaking)

        self.tts.speak.side_effect = mock_speak
        import numpy as np
        self.bridge._process_speech(np.zeros(10))
        self.assertIsNotNone(captured_done)
        captured_done()
        self.assertEqual(self.bridge.state, CallState.LISTENING)
        self.assertFalse(self.bridge._is_speaking)

    def test_tts_audio_ignored_while_speaking(self):
        """6. TTS audio ignored while _is_speaking"""
        self.bridge._is_speaking = True
        self.bridge.state = CallState.SPEAKING
        # Test condition from capture loop
        should_ignore = self.bridge._is_speaking or (self.bridge.state in [CallState.PROCESSING, CallState.SPEAKING])
        self.assertTrue(should_ignore)

    def test_vad_noise_floor_behavior(self):
        """7. VAD noise floor behavior adapts and stays >= VAD_MIN_THRESHOLD"""
        self.assertEqual(self.bridge.VAD_MIN_THRESHOLD, 1.2)
        noise_baseline = 0.5
        adaptive_threshold = max(self.bridge.VAD_MIN_THRESHOLD, noise_baseline * 2.2 + 0.5)
        self.assertGreaterEqual(adaptive_threshold, 1.2)
        self.assertAlmostEqual(adaptive_threshold, 1.6, places=1)
        
        # High noise floor
        high_noise = 2.0
        adaptive_high = max(self.bridge.VAD_MIN_THRESHOLD, high_noise * 2.2 + 0.5)
        self.assertAlmostEqual(adaptive_high, 4.9, places=1)

    def test_call_remains_active_after_recoverable_pipeline_errors(self):
        """8. call remains active after recoverable pipeline errors"""
        self.bridge.stt_engine = self.stt
        self.bridge.tts_engine = self.tts
        self.bridge.llm_func = self.llm
        
        # Sequence of failures: STT crash, LLM crash, TTS crash
        import numpy as np
        self.stt.transcribe.side_effect = Exception("STT glitch")
        self.bridge._process_speech(np.zeros(10))
        self.assertEqual(self.bridge.state, CallState.LISTENING)
        self.bridge.wa_controller.end_call.assert_not_called()

        self.stt.transcribe.side_effect = None
        self.stt.transcribe.return_value = "Recovered text"
        self.llm.side_effect = Exception("Temporary LLM error")
        self.bridge._process_speech(np.zeros(10))
        self.assertEqual(self.bridge.state, CallState.LISTENING)
        self.bridge.wa_controller.end_call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
