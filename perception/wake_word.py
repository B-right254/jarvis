"""
JARVIS Wake Word Detection — openwakeword-based always-on detection.

Provides:
- Multiple wake word support
- sounddevice audio input (non-blocking PortAudio callback)
- ONNX inference  (onnxruntime; no tflite-runtime required)
- IS_SPEAKING guard to prevent TTS audio triggering detection
- Cooldown window after each detection
- Settings-driven config (threshold, cooldown, enabled flag, mic device)
- Auto-downloads pretrained models on first run
- Callbacks dispatched off the audio thread (safe for blocking STT)
"""

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore
import settings
from settings import WAKE_WORD

logger = logging.getLogger(__name__)

try:
    import openwakeword
    from openwakeword.model import Model

    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False
    Model = None
    logger.warning("openwakeword not installed — wake word disabled")

try:
    import sounddevice as sd

    SOUNDDEVICE_AVAILABLE = True
except (ImportError, OSError):
    SOUNDDEVICE_AVAILABLE = False
    sd = None
    logger.warning("sounddevice not available — wake word disabled")


class WakeWordDetector:
    """
    Always-on wake word detection using openwakeword + sounddevice.

    Features
    --------
    - Multiple wake word models loaded simultaneously
    - IS_SPEAKING guard: resets model buffer while TTS plays
    - STT_EXCLUSIVE guard: resets model buffer while listen tool holds mic
    - Cooldown: ignores further triggers for WAKE_WORD_COOLDOWN seconds
    - ONNX inference only (onnxruntime, no tflite-runtime needed)
    - Settings-driven threshold, cooldown, mic device, enabled flag
    - Auto-downloads pretrained models on first run
    - Callbacks are dispatched on a daemon thread so blocking STT calls
      inside them never stall the PortAudio audio callback
    """

    def __init__(
        self,
        wake_words: Optional[List[str]] = None,
        inference_framework: str = "onnx",
        chunk_size: int = 1280,
    ):
        # Use explicit arg → settings.WAKE_WORD → built-in default
        self.wake_words: List[str] = wake_words or [WAKE_WORD]
        self.inference_framework = inference_framework
        self.chunk_size = chunk_size

        self._model: Optional[Model] = None
        self._listening = False
        self._audio_stream = None
        self._callbacks: List[Callable] = []
        self._cooldown_until: float = 0.0
        self._was_speaking = False

        if OPENWAKEWORD_AVAILABLE and SOUNDDEVICE_AVAILABLE:
            self._ensure_models_downloaded()
            self._initialize_model()

    # ── Model setup ───────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_models_downloaded() -> None:
        """Download pretrained models if the models directory is missing or empty."""
        import os

        resources_dir = os.path.join(
            os.path.dirname(openwakeword.__file__), "resources", "models"
        )
        has_models = os.path.isdir(resources_dir) and any(
            f.endswith(".onnx") for f in os.listdir(resources_dir)
        )
        if not has_models:
            logger.info("openwakeword models not found — downloading (one-time setup)…")
            from openwakeword.utils import download_models

            download_models([WAKE_WORD])
            logger.info("openwakeword models downloaded.")

    @staticmethod
    def _resolve_model_spec(wake_word: str) -> str:
        custom = Path(f"{wake_word}.onnx")
        return str(custom) if custom.is_file() else wake_word

    def _find_model_for_wakeword(self, wake_word: str) -> str:
        normalized = wake_word.replace(" ", "_")
        candidates = [
            Path(__file__).parent.parent
            / "models"
            / "wakewords"
            / f"{normalized}.onnx",
            Path(__file__).parent.parent
            / "models"
            / "wakewords"
            / f"{normalized}.tflite",
            Path.home() / ".jarvis" / "wakewords" / f"{normalized}.onnx",
        ]
        for path in candidates:
            if path.exists():
                logger.debug(f"Custom wake word model found: {path}")
                return str(path)
        return self._resolve_model_spec(normalized)

    def _initialize_model(self) -> None:
        """Load all configured wake word models via ONNX runtime."""
        try:
            specs = [self._find_model_for_wakeword(ww) for ww in self.wake_words]
            logger.info(
                f"Loading wake word model(s): {specs} [{self.inference_framework}]"
            )
            self._model = Model(
                wakeword_models=specs,
                inference_framework=self.inference_framework,
            )
            logger.info(
                f"Wake word model loaded OK — keys: {list(self._model.models.keys())}"
            )
        except Exception as e:
            logger.error(f"Could not initialize wake word model: {e}")
            self._model = None

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def add_callback(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    # ── Listening ─────────────────────────────────────────────────────────────

    def start_listening(self, device_index: Optional[int] = None) -> None:
        if not OPENWAKEWORD_AVAILABLE or not SOUNDDEVICE_AVAILABLE:
            logger.warning("Required libraries unavailable — wake word detection disabled")
            return
        if self._listening:
            return
        if not settings.WAKE_WORD_ENABLED:
            logger.info("Wake word disabled via WAKE_WORD_ENABLED setting")
            return

        mic = device_index
        if mic is None:
            mic = settings.MIC_DEVICE if settings.MIC_DEVICE != -1 else None

        self._listening = True

        def audio_callback(
            indata: np.ndarray, frames: int, time_info: Any, status: Any
        ) -> None:
            if status:
                logger.debug(f"Audio stream status: {status}")
            if self._model is None:
                return

            # ── Guards ────────────────────────────────────────────────────────
            # Reset model buffer while TTS plays to prevent false detection
            # from speaker audio accumulating in the ring buffer.
            if settings.IS_SPEAKING.is_set():
                try:
                    self._model.reset()
                except Exception:
                    pass
                self._was_speaking = True
                return

            # Post-TTS acoustic drain
            if self._was_speaking:
                self._was_speaking = False
                drain = getattr(settings, "WAKE_WORD_POST_TTS_DRAIN", 1.0)
                self._cooldown_until = max(
                    self._cooldown_until, time.monotonic() + drain
                )

            # Reset model buffer while listen tool holds the mic, preventing
            # accumulated "hey jarvis" audio from firing on STT_EXCLUSIVE release.
            if settings.STT_EXCLUSIVE.is_set():
                try:
                    self._model.reset()
                except Exception:
                    pass
                return

            if time.monotonic() < self._cooldown_until:
                return

            audio = indata[:, 0]
            predictions = self._model.predict(audio)

            for model_name, score in predictions.items():
                if score > settings.WAKE_WORD_THRESHOLD:
                    logger.info(
                        f"Wake word '{model_name}' detected (score={score:.3f})"
                    )
                    self._cooldown_until = (
                        time.monotonic() + settings.WAKE_WORD_COOLDOWN
                    )
                    threading.Thread(
                        target=self._on_wake_word_detected,
                        args=(model_name,),
                        daemon=True,
                    ).start()
                    break

        try:
            self._audio_stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="int16",
                blocksize=self.chunk_size,
                callback=audio_callback,
                device=mic,
            )
            self._audio_stream.start()
            logger.info(
                f"Wake word listener started "
                f"(words={self.wake_words}, device={mic}, threshold={settings.WAKE_WORD_THRESHOLD})"
            )
        except Exception as e:
            logger.error(f"Error starting wake word detection: {e}")
            self._listening = False

    def stop_listening(self) -> None:
        self._listening = False
        if self._audio_stream:
            try:
                self._audio_stream.stop()
                self._audio_stream.close()
            except Exception as e:
                logger.error(f"Error stopping audio stream: {e}")
            self._audio_stream = None

    def _on_wake_word_detected(self, model_name: str) -> None:
        """Dispatch wake word event to all registered callbacks (off audio thread)."""
        wake_word = (
            model_name.replace(".tflite", "").replace(".onnx", "").replace("_", " ")
        )
        for callback in list(self._callbacks):
            try:
                callback(wake_word)
            except Exception as e:
                logger.error(f"Error in wake word callback: {e}")

    # ── Utilities ─────────────────────────────────────────────────────────────

    @property
    def is_listening(self) -> bool:
        return self._listening

    def set_threshold(self, threshold: float) -> None:
        settings.WAKE_WORD_THRESHOLD = max(0.0, min(1.0, threshold))

    def list_audio_devices(self) -> List[Dict[str, Any]]:
        if not SOUNDDEVICE_AVAILABLE:
            return []
        try:
            return [
                {
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": dev["default_samplerate"],
                }
                for i, dev in enumerate(sd.query_devices())
                if dev["max_input_channels"] > 0
            ]
        except Exception as e:
            logger.error(f"Error listing audio devices: {e}")
            return []

    def load_custom_model(self, model_path: str, wake_word_name: str) -> bool:
        if not OPENWAKEWORD_AVAILABLE:
            return False
        try:
            path = Path(model_path)
            if not path.exists():
                logger.error(f"Custom model not found: {path}")
                return False

            existing_specs = [
                self._find_model_for_wakeword(ww) for ww in self.wake_words
            ]
            self._model = Model(
                wakeword_models=existing_specs + [str(path)],
                inference_framework=self.inference_framework,
            )
            if wake_word_name not in self.wake_words:
                self.wake_words.append(wake_word_name)
            logger.info(f"Custom wake word model loaded: {wake_word_name} ({path})")
            return True
        except Exception as e:
            logger.error(f"Error loading custom model: {e}")
            return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: Optional[WakeWordDetector] = None


def _get_detector() -> WakeWordDetector:
    global _detector
    if _detector is None:
        _detector = WakeWordDetector()
    return _detector


def reset_wake_word_detection() -> None:
    global _detector
    if _detector is not None:
        _detector.stop_listening()
    _detector = None


# ── Module-level API — used by InputHandler ───────────────────────────────────


def set_wake_callback(fn: Callable) -> None:
    """
    Register the primary wake word callback (InputHandler API).

    Wraps *fn* so it is called with the wake word string, even though
    ``InputHandler._on_wake`` doesn't use it yet.  Adding a second wake word
    later will Just Work without changing this plumbing.
    """

    def _compat_wrapper(wake_word: str = "") -> None:
        fn(wake_word)

    _get_detector().add_callback(_compat_wrapper)


def start() -> None:
    _get_detector().start_listening()


def stop() -> None:
    _get_detector().stop_listening()


# ── Convenience functions — reference API ─────────────────────────────────────


def get_wake_word_detection(
    wake_words: Optional[List[str]] = None,
    threshold: Optional[float] = None,
) -> WakeWordDetector:
    det = _get_detector()
    if threshold is not None:
        det.set_threshold(threshold)
    return det


def start_wake_word_detection(callback: Callable[[str], None]) -> None:
    det = _get_detector()
    det.add_callback(callback)
    det.start_listening()


def stop_wake_word_detection() -> None:
    _get_detector().stop_listening()
