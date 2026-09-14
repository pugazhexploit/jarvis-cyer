"""
Speech-to-Text engines for MARK XL.

Whisper  – offline transcription via faster-whisper (VAD-buffered)
Vosk     – offline streaming transcription (lighter)
"""
import json
import os
import sys
import numpy as np


def _setup_cuda_dll_paths() -> None:
    """Ensure CUDA and cuDNN DLLs in Python site-packages and PATH are discoverable on Windows."""
    if sys.platform != "win32":
        return

    import site

    candidate_dirs = set()

    site_dirs = []
    try:
        site_dirs.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            site_dirs.append(user_site)
    except Exception:
        pass

    for s_dir in site_dirs:
        nvidia_dir = os.path.join(s_dir, "nvidia")
        if os.path.isdir(nvidia_dir):
            for root, dirs, files in os.walk(nvidia_dir):
                if "bin" in dirs:
                    candidate_dirs.add(os.path.join(root, "bin"))
        torch_lib = os.path.join(s_dir, "torch", "lib")
        if os.path.isdir(torch_lib):
            candidate_dirs.add(torch_lib)

    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    for c_dir in sorted(candidate_dirs):
        if os.path.isdir(c_dir):
            try:
                os.add_dll_directory(c_dir)
            except Exception:
                pass
            if c_dir not in path_entries:
                path_entries.insert(0, c_dir)
    os.environ["PATH"] = os.pathsep.join(path_entries)


class WhisperSTT:
    """Offline transcription using faster-whisper with robust CUDA initialization and CPU fallback."""

    def __init__(self, model_name: str = "base", language: str | None = None):
        _setup_cuda_dll_paths()

        print(f"[STT] Loading Whisper '{model_name}'...")
        cuda_avail = False
        try:
            import torch
            cuda_avail = torch.cuda.is_available()
        except Exception:
            cuda_avail = False

        print(f"[STT] CUDA available: {cuda_avail}")

        self._model_name = model_name
        self._language = None if (not language or language.strip().lower() == "auto") else language.strip().lower()
        self._device = "cpu"
        self._model = None

        if cuda_avail:
            print("[STT] Initializing faster-whisper on CUDA...")
            try:
                model = self._load_model(model_name, device="cuda", compute_type="float16")
                # Probe CUDA execution to catch missing DLLs or driver errors before live audio
                probe_audio = np.zeros(1600, dtype=np.float32)
                _ = list(model.transcribe(probe_audio, language="en", beam_size=1)[0])
                self._model = model
                self._device = "cuda"
                print(f"[STT] Whisper '{model_name}' ready (cuda)")
            except Exception as cuda_err:
                print(f"[STT] CUDA initialization failed: {cuda_err}")
                print("[STT] Falling back to CPU int8 so the call remains alive.")
                self._model = self._load_model(model_name, device="cpu", compute_type="int8")
                self._device = "cpu"
                print(f"[STT] Whisper '{model_name}' ready (cpu)")
        else:
            self._model = self._load_model(model_name, device="cpu", compute_type="int8")
            self._device = "cpu"
            print(f"[STT] Whisper '{model_name}' ready (cpu)")

    def _load_model(self, model_name: str, device: str, compute_type: str):
        from faster_whisper import WhisperModel
        try:
            return WhisperModel(model_name, device=device, compute_type=compute_type)
        except Exception as _first_err:
            _e = str(_first_err).lower()
            _offline_keywords = (
                "offline", "not found", "cache", "localentry",
                "does not exist", "outgoing", "local_files_only",
            )
            if any(k in _e for k in _offline_keywords):
                print(f"[STT] Whisper '{model_name}' not in local cache — downloading (one-time, internet required)…")
                os.environ.pop("HF_HUB_OFFLINE", None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                os.environ.pop("HF_DATASETS_OFFLINE", None)
                try:
                    return WhisperModel(model_name, device=device, compute_type=compute_type)
                except Exception as _dl_err:
                    raise RuntimeError(
                        f"Whisper '{model_name}' model download failed.\n"
                        f"Internet access is required the first time to download the speech model (~75–290 MB).\n"
                        f"After the first download it runs fully offline.\n"
                        f"Details: {_dl_err}"
                    ) from _dl_err
            raise

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 mono 16 kHz numpy array. Returns transcript string."""
        try:
            segments, _ = self._model.transcribe(
                audio,
                language=self._language,
                beam_size=1,                       # greedy — 2-3x faster
                best_of=1,
                condition_on_previous_text=False,  # no hallucinations, faster
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            err_str = str(e).lower()
            if self._device == "cuda" and any(k in err_str for k in ("cublas", "cuda", "cudnn", "driver", "failed to load")):
                print(f"[STT] CUDA transcription error: {e}")
                print("[STT] Falling back to CPU int8 so the call remains alive.")
                try:
                    self._model = self._load_model(self._model_name, device="cpu", compute_type="int8")
                    self._device = "cpu"
                    print(f"[STT] Whisper '{self._model_name}' ready (cpu)")
                    segments, _ = self._model.transcribe(
                        audio,
                        language=self._language,
                        beam_size=1,
                        best_of=1,
                        condition_on_previous_text=False,
                        vad_filter=True,
                        vad_parameters={"min_silence_duration_ms": 300},
                    )
                    return " ".join(s.text for s in segments).strip()
                except Exception as fallback_err:
                    print(f"[STT] CPU transcription fallback error: {fallback_err}")
                    raise
            print(f"[STT] Transcription error: {e}")
            raise


class VoskSTT:
    """Streaming transcription using Vosk."""

    def __init__(self, model_path: str | None = None, language: str = "en-us"):
        from vosk import Model, KaldiRecognizer
        print("[STT] Loading Vosk model…")
        if model_path:
            model = Model(model_path)
        else:
            lang  = language.strip().lower() if language and language.strip().lower() != "auto" else "en-us"
            model = Model(lang=lang)
        self._rec = KaldiRecognizer(model, 16000)
        print("[STT] Vosk ready.")

    def process_chunk(self, audio_bytes: bytes) -> tuple[str, bool]:
        """Feed raw int16 LE PCM bytes. Returns (text, is_final)."""
        if self._rec.AcceptWaveform(audio_bytes):
            result = json.loads(self._rec.Result())
            return result.get("text", ""), True
        partial = json.loads(self._rec.PartialResult())
        return partial.get("partial", ""), False
