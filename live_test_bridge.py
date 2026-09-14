import sys
import time
import sounddevice as sd
from plugins.whatsapp_voice_bridge import WhatsAppVoiceBridge
from core.tts import TTSPlayer, EdgeTTSEngine
from core.stt import WhisperSTT
from core.llm_client import call_llm_stream, check_llm_readiness

class RealLLM:
    def __init__(self):
        check_llm_readiness(auto_pull=True)
        self.messages = [
            {"role": "system", "content": """You are JARVIS speaking naturally with a human over a live WhatsApp voice call.

Respond conversationally and naturally.
Keep responses concise (approximately 1 to 3 short sentences) for natural voice phone conversation.
Do not use markdown.
Do not produce lists unless specifically requested.
Do not sound like a text chatbot.
Do not repeat the user's question unnecessarily.
If the user asks a follow-up question, use the previous conversation context.
If the user interrupts or changes topic, follow the new topic naturally.
Ask a short follow-up question when appropriate.
Never use scripted or predefined responses."""}
        ]

    def __call__(self, text):
        turn_id = len(self.messages) // 2
        print(f"\n[MEMORY] user turn #{turn_id}")
        self.messages.append({"role": "user", "content": text})
        
        print(f"[LLM] generating response")
        out = ""
        for msg in call_llm_stream(self.messages):
            if msg['type'] == 'sentence':
                out += msg['text'] + " "
                
        final_response = out.strip()
        self.messages.append({"role": "assistant", "content": final_response})
        print(f"[LLM] response: {final_response}")
        print(f"[MEMORY] assistant turn #{turn_id}")
        return final_response

def dump_audio_devices():
    print("\n--- AUDIO DEVICE DUMP ---")
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            io = f"IN:{d['max_input_channels']} OUT:{d['max_output_channels']}"
            print(f"[{i}] {d['name']} ({io}) - {d['default_samplerate']}Hz")
    except Exception as e:
        print("Failed to query devices:", e)
    print("-------------------------\n")


def diagnostic_audio_test():
    print("--- AUDIO DIAGNOSTIC TEST ---")
    try:
        import soundcard as sc
        spk = sc.default_speaker()
        print(f"Default speaker: {spk.name}")
        mic = sc.get_microphone(spk.id, include_loopback=True)
        print(f"Loopback device: {mic.name}")
        with mic.recorder(samplerate=16000, channels=1) as recorder:
            print("Successfully opened loopback capture.")
            chunk = recorder.record(numframes=10)
            print("Successfully recorded test frames.")
        print("Audio backend is healthy.\n")
    except Exception as e:
        print(f"ERROR: Audio diagnostic failed: {e}")
        print("Cannot start live test.\n")
        sys.exit(1)

def run_live_test(contact_name, debug_audio=False):

    print("=============================================")
    print(f"Starting REAL LIVE TEST for WhatsApp Voice Bridge")
    print(f"Target: {contact_name}")
    print("=============================================\n")
    
    if debug_audio:
        dump_audio_devices()
    diagnostic_audio_test()
        
    bridge = WhatsAppVoiceBridge.get_instance()
    stt = WhisperSTT(model_name="tiny")
    tts = TTSPlayer(EdgeTTSEngine())
    llm = RealLLM()
    
    bridge.log = lambda msg: (bridge.diagnostic_log.append(msg), print(msg, flush=True))
    
    try:
        res = bridge.start_call_and_bridge(contact_name, stt_engine=stt, tts_engine=tts, llm_func=llm)
        print("\n--- CALL INITIATION RESULT ---")
        print(res)
        print("------------------------------\n")
        
        while bridge.state.name not in ["STOPPING", "ENDED", "ERROR", "IDLE"]:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n[USER ABORT] Ctrl+C pressed. Cleaning up...")
    finally:
        bridge.hang_up()
        print("\nFinal Bridge State:", bridge.state.name)
        print("=============================================")
        print("TEST COMPLETE")
        
if __name__ == '__main__':
    contact_name = 'my world'
    debug_audio = '--debug-audio' in sys.argv
    if len(sys.argv) > 1 and sys.argv[1] != '--debug-audio':
        contact_name = sys.argv[1]
    
    run_live_test(contact_name, debug_audio)

