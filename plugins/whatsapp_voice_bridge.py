import threading
import time
import queue
import re
import numpy as np
import sounddevice as sd
from enum import Enum
from plugins.whatsapp_desktop_call import WhatsAppDesktopController

class CallState(Enum):
    IDLE = "IDLE"
    CALLING = "CALLING"
    CALLING_UNVERIFIED = "CALLING_UNVERIFIED"
    CONNECTING = "CONNECTING"
    CONNECTED_UNVERIFIED = "CONNECTED_UNVERIFIED"
    CONVERSATION = "CONVERSATION"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    STOPPING = "STOPPING"
    ENDED = "ENDED"
    ERROR = "ERROR"

class WhatsAppVoiceBridge:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = WhatsAppVoiceBridge()
        return cls._instance

    def __init__(self):
        self.state = CallState.IDLE
        self.wa_controller = WhatsAppDesktopController()
        self.diagnostic_log = []
        
        self.wa_mic_device = None
        self.wa_speaker_device = None
        
        self._stop_event = threading.Event()
        self._audio_thread = None
        self._turn_lock = threading.Lock()
        
        self._is_speaking = False
        self._interrupted = False
        self._cooldown_until = 0.0
        
        self.sample_rate = 16000
        self.utterance_queue = queue.Queue()
        self._worker_thread = None
        
        # Robust VAD configuration
        self.VAD_MIN_THRESHOLD = 1.2       # Base minimum threshold (ignore ambient line noise)
        self.VAD_THRESHOLD = 1.2           # Active threshold (dynamically adapted)
        self.VAD_SILENCE_FRAMES = 14       # ~0.9s of silence to finalize turn
        self.VAD_MIN_SPEECH_FRAMES = 5     # ~0.32s of continuous speech to trigger start
        self.VAD_MAX_SPEECH_FRAMES = 160   # ~10.2s max utterance (prevents runaway background recording)
        self.VAD_PREROLL_FRAMES = 6        # ~0.38s of pre-roll audio

        self.stt_engine = None
        self.tts_engine = None
        self.llm_func = None
        
    def log(self, msg):
        self.diagnostic_log.append(msg)
        print(msg)
        
    def _detect_virtual_audio_cable(self):
        try:
            devices = sd.query_devices()
            input_cable = None
            output_cable = None
            output_cable_name = None
            for i, d in enumerate(devices):
                name = d['name'].lower()
                if 'cable' in name or 'virtual' in name or 'voicemeeter' in name:
                    if d['max_input_channels'] > 0 and input_cable is None:
                        input_cable = i
                    if d['max_output_channels'] > 0 and output_cable is None:
                        output_cable = i
                        output_cable_name = d['name']
            return input_cable, output_cable, output_cable_name
        except Exception:
            return None, None, None

    def _enable_whatsapp_tts_routing(self, out_cable):
        try:
            import core.tts
            core.tts.TTS_OUTPUT_DEVICE = out_cable
            self.log(f"[TTS] routing enabled (device {out_cable})")
        except ImportError:
            pass

    def _disable_whatsapp_tts_routing(self):
        try:
            import core.tts
            core.tts.TTS_OUTPUT_DEVICE = None
            self.log("[TTS] routing restored")
        except ImportError:
            pass

    def start_call_and_bridge(self, contact_name, stt_engine=None, tts_engine=None, llm_func=None):
        if self.state in [CallState.CONVERSATION, CallState.CONNECTING, CallState.CALLING_UNVERIFIED, CallState.CONNECTED_UNVERIFIED]:
            return "[JARVIS-WA] Already in conversation."
            
        self.stt_engine = stt_engine
        self.tts_engine = tts_engine
        self.llm_func = llm_func

        self.state = CallState.CALLING
        self.log("[CALL] initiating WhatsApp call")
        self.log("[CALL] call initiation requested")
        logs = ["[CALL] initiating WhatsApp call", "[CALL] call initiation requested"]
        
        if not self.wa_controller.is_whatsapp_running():
            self.state = CallState.ERROR
            return "Error: WhatsApp Desktop is not running or could not be focused."
        
        matches = self.wa_controller.search_contact(contact_name)
        
        if len(matches) > 1:
            self.state = CallState.ERROR
            return f"Multiple contacts found for '{contact_name}': {matches}"
        elif len(matches) == 0 and len(self.wa_controller.diagnostic_log) > 0 and "UIA blind" not in self.wa_controller.diagnostic_log[-1]:
            self.state = CallState.ERROR
            return f"Contact '{contact_name}' not found."
            
        success_open = self.wa_controller.open_contact(contact_name, matches)
        if not success_open:
            self.state = CallState.ERROR
            log_output = "\n".join(self.wa_controller.diagnostic_log)
            return f"Failed to open chat for {contact_name}.\nLogs:\n{log_output}"
            
        success_call = self.wa_controller.start_voice_call(contact_name)
        if not success_call or "Failed" in success_call:
            self.state = CallState.ERROR
            return f"Failed to start voice call for {contact_name}."
            
        if success_call == "SUCCESS_VERIFIED":
            self.state = CallState.CONNECTING
            self.log("[JARVIS-WA] Call verified as CONNECTING/OUTGOING via UIA.")
            logs.append("[JARVIS-WA] Call verified as CONNECTING/OUTGOING via UIA.")
            self.log("[CALL] waiting for remote answer/audio")
            logs.append("[CALL] waiting for remote answer/audio")
        else:
            self.state = CallState.CALLING_UNVERIFIED
            self.log("[JARVIS-WA] Call initiated (UIA blind).")
            logs.append("[JARVIS-WA] Call initiated (UIA blind).")
            self.log("[CALL] waiting for remote answer/audio")
            logs.append("[CALL] waiting for remote answer/audio")
            
        self._stop_event.clear()
        self._is_speaking = False
        
        in_cable, out_cable, out_name = self._detect_virtual_audio_cable()
        
        if out_cable is None:
            self.log("[JARVIS-AUDIO] WARNING: No Virtual Audio Cable detected.")
            self.log("[JARVIS-AUDIO] Exact limitation: WhatsApp Desktop uses Windows audio endpoints. To inject JARVIS's voice into the call, and to capture the remote person's voice without acoustic echo, a Virtual Audio Cable (like VB-Audio Cable) is REQUIRED.")
            self.log("[JARVIS-AUDIO] Configuration needed: Install VB-Cable. Set WhatsApp Mic -> CABLE Output. Keep WhatsApp Speaker -> System Default.")
            logs.extend(["[JARVIS-AUDIO] WARNING: No Virtual Audio Cable detected.", "[JARVIS-AUDIO] Exact limitation...", "[JARVIS-AUDIO] Configuration needed..."])
            self.wa_mic_device = None
        else:
            self.log(f"[JARVIS-AUDIO] WhatsApp TTS output device: {out_name} (Index: {out_cable})")
            logs.append(f"[JARVIS-AUDIO] WhatsApp TTS output device: {out_name} (Index: {out_cable})")
            self.wa_mic_device = out_cable
            
        self._audio_thread = threading.Thread(target=self._capture_and_process_loop, daemon=True)
        self._audio_thread.start()
        self._worker_thread = threading.Thread(target=self._processing_worker_loop, daemon=True)
        self._worker_thread.start()
        
        return "\n".join(logs)
        
    def stop_conversation(self):
        active_states = [
            CallState.CONVERSATION, CallState.CONNECTING, 
            CallState.CALLING_UNVERIFIED, CallState.CONNECTED_UNVERIFIED,
            CallState.LISTENING, CallState.PROCESSING, CallState.SPEAKING
        ]
        if self.state not in active_states:
            return "[JARVIS-WA] Not currently in a conversation."
            
        self.log("[JARVIS-WA] Stopping conversation mode...")
        self.state = CallState.STOPPING
        self._stop_event.set()
        
        self._disable_whatsapp_tts_routing()
        
        if self.tts_engine:
            try:
                self.tts_engine.stop()
            except Exception:
                pass
                
        self._is_speaking = False
        if self._audio_thread:
            self._audio_thread.join(timeout=2.0)
            
        self.state = CallState.ENDED
        return "[JARVIS-WA] Conversation loop stopped."
        
    def hang_up(self):
        self.stop_conversation()
        if self.wa_controller.is_whatsapp_running():
            self.wa_controller.end_call()
        return "[JARVIS-WA] Call ended and conversation stopped."
        

    def _processing_worker_loop(self):
        while not self._stop_event.is_set():
            try:
                audio_data = self.utterance_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            if self._stop_event.is_set():
                break
                
            self._process_speech(audio_data)
            self.utterance_queue.task_done()


    def _capture_and_process_loop(self):
        chunk_size = 1024
        audio_buffer = []
        speaking = False
        silence_frames = 0
        speech_frames = 0
        
        noise_baseline = 0.0
        baseline_frames = 0
        
        try:
            while not self._stop_event.is_set():
                try:
                    import soundcard as sc
                    import sounddevice as sd
                    import warnings
                    
                    default_speaker = sc.default_speaker()
                    loopback_mic = sc.get_microphone(default_speaker.id, include_loopback=True)
                    self.log(f"[AUDIO] initializing WASAPI loopback")
                    self.log(f"[AUDIO] loopback device: {loopback_mic.name}")
                    self.log(f"[AUDIO] loopback capture started")
                    self.log(f"[CALL] call remains active")
                    
                    with loopback_mic.recorder(samplerate=self.sample_rate, channels=1) as mic:
                        while not self._stop_event.is_set():
                            try:
                                with warnings.catch_warnings():
                                    warnings.simplefilter("ignore")
                                    chunk = mic.record(numframes=chunk_size)
                            except Exception as e:
                                continue
                                
                            if chunk is None or len(chunk) == 0:
                                continue
                                
                            try:
                                volume_norm = np.linalg.norm(chunk) * 10
                            except Exception:
                                continue
                                
                            # Continuously track and adapt noise floor during non-speech
                            if not speaking:
                                if baseline_frames < 30:
                                    noise_baseline = ((noise_baseline * baseline_frames) + volume_norm) / (baseline_frames + 1)
                                    baseline_frames += 1
                                else:
                                    noise_baseline = 0.95 * noise_baseline + 0.05 * volume_norm
                                    
                            adaptive_threshold = max(self.VAD_MIN_THRESHOLD, noise_baseline * 2.2 + 0.5)
                            self.VAD_THRESHOLD = adaptive_threshold
                            
                            # CRITICAL: Prevent self-hearing. If JARVIS is speaking, processing, or in cooldown, discard audio
                            if self._is_speaking or time.time() < self._cooldown_until or self.state in [CallState.PROCESSING, CallState.SPEAKING]:
                                speaking = False
                                silence_frames = 0
                                speech_frames = 0
                                audio_buffer = []
                                continue
                            
                            # Remote audio detection for call connect
                            if self.state in [CallState.CALLING_UNVERIFIED, CallState.CONNECTING]:
                                if volume_norm > adaptive_threshold:
                                    self.log(f"[CALL] remote audio detected (RMS: {volume_norm:.2f} > THRESH: {adaptive_threshold:.2f}, noise floor: {noise_baseline:.2f})")
                                    self.state = CallState.LISTENING
                                    self.log("[STATE] CONNECTING -> LISTENING")
                                    if self.wa_mic_device is not None:
                                        self._enable_whatsapp_tts_routing(self.wa_mic_device)
                            
                            if self.state == CallState.LISTENING:
                                if volume_norm > adaptive_threshold:
                                    if not speaking:
                                        self.log(f"[VAD] speech started (RMS: {volume_norm:.2f} > THRESH: {adaptive_threshold:.2f}, noise floor: {noise_baseline:.2f})")
                                        speaking = True
                                        silence_frames = 0
                                    
                                    speech_frames += 1
                                    silence_frames = 0
                                    audio_buffer.append(chunk)
                                else:
                                    if speaking:
                                        silence_frames += 1
                                        audio_buffer.append(chunk)
                                        
                                        if silence_frames > self.VAD_SILENCE_FRAMES or len(audio_buffer) > self.VAD_MAX_SPEECH_FRAMES:
                                            duration = len(audio_buffer) * chunk_size / self.sample_rate
                                            self.log(f"[VAD] speech ended: {duration:.2f}s (utterance finalized, buffer size: {len(audio_buffer)})")
                                            speaking = False
                                            
                                            if len(audio_buffer) > self.VAD_MIN_SPEECH_FRAMES:
                                                self.state = CallState.PROCESSING
                                                self.log(f"[STATE] LISTENING -> PROCESSING")
                                                self.log(f"[AUDIO-RX] sending {duration:.2f} seconds to STT")
                                                
                                                audio_data = np.concatenate(audio_buffer)
                                                self.utterance_queue.put(audio_data)
                                            else:
                                                self.log("[VAD] utterance too short, ignoring.")
                                                
                                            audio_buffer = []
                                            speech_frames = 0
                                            silence_frames = 0
                                    else:
                                        speech_frames = 0
                                        audio_buffer.append(chunk)
                                        if len(audio_buffer) > self.VAD_PREROLL_FRAMES:
                                            audio_buffer.pop(0)
                except Exception as e:
                    if self._stop_event.is_set():
                        break
                    self.log(f"[AUDIO] loopback capture crashed: {e}. Retrying in 2s...")
                    time.sleep(2)
                    
        finally:
            self._disable_whatsapp_tts_routing()
            self.log("[JARVIS-WA] Conversation stopped.")

    def _process_speech(self, audio_data):
        try:
            if self._stop_event.is_set():
                return
            
            if not self.stt_engine:
                self.log("[JARVIS-WA] STT not configured")
                self.state = CallState.LISTENING
                self.log(f"[STATE] PROCESSING -> LISTENING")
                return
                
            self.log("[STT] transcribing...")
            audio_flat = audio_data.flatten().astype(np.float32)
            transcript = self.stt_engine.transcribe(audio_flat)
            if not transcript.strip():
                self.log("[JARVIS-STT] Transcript empty, ignoring.")
                self.state = CallState.LISTENING
                self.log(f"[STATE] PROCESSING -> LISTENING")
                return
                
            self.log(f"[STT] transcript: {transcript}")
            
            if self.llm_func:
                self.log("[LLM] generating response")
                response = self.llm_func(transcript)
                
                if self.tts_engine and response:
                    self.state = CallState.SPEAKING
                    self.log(f"[STATE] PROCESSING -> SPEAKING")
                    self.log("[TTS] speaking started")
                    self._is_speaking = True
                    self._interrupted = False
                    
                    def on_tts_done():
                        self._is_speaking = False
                        self._cooldown_until = time.time() + 0.6
                        self.log("[TTS] speaking finished")
                        self.log("[TTS] routing remains active")
                        self.log("[JARVIS-AUDIO] Flushing stale capture frames")
                        self.log("[JARVIS-VAD] Reset")
                        if not self._stop_event.is_set():
                            self.state = CallState.LISTENING
                            self.log(f"[STATE] SPEAKING -> LISTENING")
                    
                    self.log(f"[AUDIO-TX] TTS device index: {self.wa_mic_device}")
                    self.tts_engine.speak(response, on_start=None, on_done=on_tts_done)
                else:
                    self.state = CallState.LISTENING
                    self.log(f"[STATE] PROCESSING -> LISTENING")
            else:
                self.state = CallState.LISTENING
                self.log(f"[STATE] PROCESSING -> LISTENING")
        except Exception as e:
            self.log(f"[JARVIS-WA] Pipeline error: {e}")
            if not self._stop_event.is_set():
                self.state = CallState.LISTENING
                self.log(f"[STATE] ERROR -> LISTENING")
PLUGIN = {
    "name": "whatsapp_voice_bridge",
    "description": (
        "Provides a 2-way AI voice bridge for WhatsApp calls. "
        "Use this when the user asks JARVIS to 'Call [X] and talk to them', "
        "'Stop talking to them', or 'Hang up the WhatsApp call'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "intent": {
                "type": "STRING", 
                "description": "The specific intent: 'call_and_talk', 'stop_talking', or 'hang_up'."
            },
            "contact_name": {
                "type": "STRING",
                "description": "The name of the contact, required for 'call_and_talk'."
            }
        },
        "required": ["intent"],
    }
}

def extract_contact_name(text):
    patterns = [
        r"call\s+(.+?)\s+and\s+talk",
        r"talk\s+to\s+(.+?)\s+on\s+whatsapp"
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            return name
    return None

def run(parameters: dict, player=None, session_memory=None) -> str:
    raw_intent = parameters.get("intent", "").lower().strip()
    contact_name = parameters.get("contact_name", "").strip()

    if not contact_name and "call_and_talk" in raw_intent:
        contact_name = extract_contact_name(raw_intent) or ""

    bridge = WhatsAppVoiceBridge.get_instance()
    
    if raw_intent == "hang_up":
        return bridge.hang_up()
        
    if raw_intent == "stop_talking":
        return bridge.stop_conversation()
        
    if raw_intent == "call_and_talk":
        if not contact_name:
            return "Error: Contact name not specified."
            
        stt_mock = None
        tts_mock = None
        llm_mock = None
        
        if player and hasattr(player, 'stt'):
            stt_mock = player.stt
        if player and hasattr(player, 'tts'):
            tts_mock = player.tts
            
        def _llm_func(text):
            try:
                from core.llm_client import call_llm_stream
                messages = [{"role": "system", "content": "You are JARVIS. Have a brief voice call conversation."}, 
                            {"role": "user", "content": text}]
                out = ""
                for msg in call_llm_stream(messages):
                    if msg['type'] == 'sentence':
                        out += msg['text'] + " "
                return out.strip()
            except:
                return "I'm having trouble thinking right now."
                
        llm_mock = _llm_func
        
        return bridge.start_call_and_bridge(contact_name, stt_mock, tts_mock, llm_mock)

    return "Error: Unknown intent for whatsapp_voice_bridge."
