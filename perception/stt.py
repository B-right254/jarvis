"""
Speech-to-Text: Google STT primary, local Whisper fallback.
Respects IS_SPEAKING mute flag to prevent acoustic feedback.
"""

import logging

import settings
from settings import STT_LANGUAGE, STT_SAMPLE_RATE

logger = logging.getLogger(__name__)

try:
    import speech_recognition as sr

    _recognizer = sr.Recognizer()
    _recognizer.dynamic_energy_threshold = False  # use fixed threshold from calibration
    _stt_available = True
except ImportError:
    _stt_available = False
    logger.warning("SpeechRecognition not installed — STT disabled")

try:
    import whisper as _whisper_lib

    _whisper_available = True
    _whisper_model = None  # lazy-loaded once
except ImportError:
    _whisper_available = False
    _whisper_model = None

# Cache mic device list — expensive PortAudio query on Windows
_mic_names: list[str] | None = None


def _get_mic_names() -> list[str]:
    global _mic_names
    if _mic_names is None:
        _mic_names = sr.Microphone.list_microphone_names()
    return _mic_names


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None and _whisper_available:
        _whisper_model = _whisper_lib.load_model("tiny")
    return _whisper_model


def _calibrate_once():
    """One-shot ambient noise calibration at module init."""
    if not _stt_available:
        return
    # If a mic is available, calibrate once to set a sane energy_threshold
    try:
        mic = sr.Microphone(
            sample_rate=STT_SAMPLE_RATE,
            device_index=settings.MIC_DEVICE if settings.MIC_DEVICE != -1 else None,
        )
        with mic as source:
            _recognizer.adjust_for_ambient_noise(source, duration=0.5)
        logger.debug("STT: ambient noise calibrated once at init")
    except Exception:
        pass  # will calibrate on first use if needed


_calibrate_once()


def _capture(timeout: float, phrase_limit: int) -> tuple:
    """
    Shared mic capture path. Returns (audio_data, error_string).
    On success, error_string is None. On failure, error_string is set.
    """
    if not _get_mic_names():
        return None, "No microphones available"

    try:
        mic = sr.Microphone(
            sample_rate=STT_SAMPLE_RATE,
            device_index=settings.MIC_DEVICE if settings.MIC_DEVICE != -1 else None,
        )
    except (OSError, IOError, AttributeError) as e:
        return None, f"Microphone not available — {e}"

    with mic as source:
        try:
            audio = _recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
        except sr.WaitTimeoutError:
            return None, "timeout"

    return audio, None


def _transcribe(audio) -> str:
    """Try Google STT, fall back to Whisper local. Returns text or ''."""
    try:
        text = _recognizer.recognize_google(audio, language=STT_LANGUAGE)
        logger.info(f"STT: '{text}'")
        return text.strip()
    except sr.UnknownValueError:
        logger.debug("STT: could not understand audio")
        return ""
    except sr.RequestError:
        logger.warning("STT: Google API error — trying local Whisper fallback")
        return _whisper_fallback(audio)


def listen(timeout: float = 5.0) -> str:
    """
    Listen for speech and return transcribed text.
    Returns empty string if no speech detected or if IS_SPEAKING is True.
    """
    if settings.IS_SPEAKING.is_set():
        logger.debug("STT muted — system is speaking")
        return ""
    if not _stt_available:
        return ""

    audio, err = _capture(timeout, 10)
    if err:
        return ""
    return _transcribe(audio)


def transcribe_once(timeout: float = 10.0) -> str:
    """
    Single-shot capture for the listen tool (holds STT_EXCLUSIVE).
    Does NOT check IS_SPEAKING. Returns empty string on failure/silence.
    """
    if not _stt_available:
        return ""

    audio, err = _capture(timeout, 15)
    if err:
        return ""
    return _transcribe(audio)


def _whisper_fallback(audio) -> str:
    """
    Transcribe audio using local OpenAI Whisper 'tiny' model (cached).
    """
    if not _whisper_available:
        logger.debug("STT: Whisper not installed — skipping fallback")
        return ""
    if audio is None:
        return ""

    import os
    import tempfile

    model = _get_whisper_model()
    if model is None:
        return ""

    tmp_path = None
    try:
        wav_bytes = audio.get_wav_data()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        result = model.transcribe(tmp_path, language=None, fp16=False)
        text = (result.get("text") or "").strip()
        if text:
            logger.info(f"STT(whisper): '{text}'")
        return text
    except Exception as exc:
        logger.error(f"STT: Whisper fallback failed — {exc}")
        return ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
