"""Sarvam AI client — ASR (Saarika) + TTS (Bulbul) for Indic voice.

Primary voice engine for Telugu/Hindi/English code-mixed speech.
Falls back to existing Whisper ASR / MMS TTS when Sarvam is unavailable.
"""

import base64
import logging
from io import BytesIO

import httpx

from services.api.core.config import get_settings

logger = logging.getLogger(__name__)

SARVAM_BASE = "https://api.sarvam.ai"

# Language code mapping for Sarvam API
SARVAM_LANG_MAP = {
    "te": "te-IN",
    "hi": "hi-IN",
    "en": "en-IN",
    "te-IN": "te-IN",
    "hi-IN": "hi-IN",
    "en-IN": "en-IN",
}

# TTS speaker voices available in Bulbul
SARVAM_SPEAKERS = {
    "te": "meera",   # Telugu female
    "hi": "meera",   # Hindi female
    "en": "meera",   # English female
}


async def sarvam_asr(audio_bytes: bytes, language: str = "te") -> str | None:
    """Transcribe audio using Sarvam Saarika ASR.

    Args:
        audio_bytes: Raw audio bytes (WAV/MP3/WebM).
        language: Language code (te/hi/en or te-IN/hi-IN/en-IN).

    Returns:
        Transcribed text, or None on failure (caller should fall back).
    """
    settings = get_settings()
    if not settings.sarvam_api_key:
        return None

    lang_code = SARVAM_LANG_MAP.get(language, "hi-IN")

    try:
        # Sarvam ASR expects base64 audio in JSON body
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{SARVAM_BASE}/speech-to-text",
                headers={
                    "api-subscription-key": settings.sarvam_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "input": audio_b64,
                    "language_code": lang_code,
                    "model": "saarika:v2",
                    "with_timestamps": False,
                },
            )
            if resp.status_code != 200:
                logger.warning("Sarvam ASR returned %d: %s", resp.status_code, resp.text[:200])
                return None

            data = resp.json()
            transcript = data.get("transcript", "")
            if transcript:
                logger.info("Sarvam ASR success (%s): %s...", lang_code, transcript[:60])
                return transcript
            return None

    except Exception as exc:
        logger.warning("Sarvam ASR failed: %s", exc)
        return None


async def sarvam_tts(text: str, language: str = "te") -> bytes | None:
    """Synthesize speech using Sarvam Bulbul TTS.

    Args:
        text: Text to synthesize (max ~500 chars for free tier).
        language: Target language code.

    Returns:
        Audio bytes (WAV), or None on failure.
    """
    settings = get_settings()
    if not settings.sarvam_api_key:
        return None

    lang_code = SARVAM_LANG_MAP.get(language, "hi-IN")
    speaker = SARVAM_SPEAKERS.get(language, "meera")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{SARVAM_BASE}/text-to-speech",
                headers={
                    "api-subscription-key": settings.sarvam_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": [text[:500]],
                    "target_language_code": lang_code,
                    "speaker": speaker,
                    "model": "bulbul:v1",
                    "enable_preprocessing": True,
                },
            )
            if resp.status_code != 200:
                logger.warning("Sarvam TTS returned %d: %s", resp.status_code, resp.text[:200])
                return None

            data = resp.json()
            # Sarvam returns base64-encoded audio in "audios" array
            audios = data.get("audios")
            if audios and len(audios) > 0:
                audio_b64 = audios[0]
                audio_bytes = base64.b64decode(audio_b64)
                logger.info("Sarvam TTS success (%s), %d bytes", lang_code, len(audio_bytes))
                return audio_bytes
            return None

    except Exception as exc:
        logger.warning("Sarvam TTS failed: %s", exc)
        return None


async def transcribe_with_fallback(audio_bytes: bytes, language: str = "te") -> str:
    """Transcribe audio: Sarvam first, then existing Whisper fallback."""
    # Try Sarvam first
    transcript = await sarvam_asr(audio_bytes, language)
    if transcript:
        return transcript

    # Fallback to existing Whisper/HF ASR
    from services.api.services.asr import transcribe_audio
    return await transcribe_audio(audio_bytes, language=language)


async def synthesize_with_fallback(text: str, language: str = "te") -> bytes | None:
    """Synthesize speech: Sarvam first, then existing TTS fallback."""
    # Try Sarvam first
    audio = await sarvam_tts(text, language)
    if audio:
        return audio

    # Fallback to existing TTS (Kokoro / HF MMS)
    from services.api.services.tts import synthesize_speech
    result_b64 = await synthesize_speech(text, language=language)
    if result_b64:
        return base64.b64decode(result_b64)
    return None
