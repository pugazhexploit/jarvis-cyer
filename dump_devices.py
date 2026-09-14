import sounddevice as sd

def dump_audio_devices():
    print("\n--- AUDIO DEVICE DUMP ---")
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        io = f"IN:{d['max_input_channels']} OUT:{d['max_output_channels']}"
        print(f"[{i}] {d['name']} ({io}) - {d['default_samplerate']}Hz")
    print("-------------------------\n")

if __name__ == '__main__':
    dump_audio_devices()
