"""Audio pipeline — STT (Whisper) and TTS (Google Cloud / OpenAI) integration.

Handles the Audio → Text → [Orchestrator] → Text → Audio lifecycle.

STT options:
  1. Local Whisper (openai-whisper): Free, runs on GPU, ~1-3s latency
  2. OpenAI Whisper API: $0.006/min, lower latency, no local GPU needed

TTS options:
  1. Google Cloud TTS: $4/1M chars, natural voices, multi-language
  2. OpenAI TTS: $15/1M chars, very natural, English-focused
  3. Edge TTS (free): Microsoft Edge voices, decent quality, no cost

Default: Local Whisper for STT + Edge TTS (free) for development,
         OpenAI Whisper API + Google Cloud TTS for production.
"""

from __future__ import annotations

import io
import logging
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("osteotwin.voice.audio")


class STTProvider(str, Enum):
    whisper_local = "whisper_local"
    whisper_api = "whisper_api"


class TTSProvider(str, Enum):
    google = "google"
    openai = "openai"
    edge = "edge"


# ---------------------------------------------------------------------------
# STT: Speech-to-Text
# ---------------------------------------------------------------------------


async def transcribe(
    audio_bytes: bytes,
    provider: STTProvider = STTProvider.whisper_local,
    language: str = "ko",
) -> dict:
    """Transcribe audio to text.

    Args:
        audio_bytes: Raw audio bytes (WAV, MP3, WEBM, etc.)
        provider: STT provider to use
        language: Language hint (ISO 639-1)

    Returns:
        Dict with 'text', 'language', 'duration_ms', 'provider'
    """
    t0 = time.time()

    if provider == STTProvider.whisper_local:
        text = await _transcribe_whisper_local(audio_bytes, language)
    elif provider == STTProvider.whisper_api:
        text = await _transcribe_whisper_api(audio_bytes, language)
    else:
        raise ValueError(f"Unknown STT provider: {provider}")

    elapsed = (time.time() - t0) * 1000
    logger.info("STT [%s]: '%s' (%.0fms)", provider.value, text[:80], elapsed)

    return {
        "text": text,
        "language": language,
        "duration_ms": round(elapsed, 1),
        "provider": provider.value,
    }


async def _transcribe_whisper_local(audio_bytes: bytes, language: str) -> str:
    """Transcribe using local Whisper model."""
    import whisper
    import numpy as np
    import soundfile as sf

    # Write audio to temp file (Whisper needs a file path)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        temp_path = f.name

    try:
        # Load model (cached after first call)
        model = whisper.load_model("base")  # Use "small" for better accuracy
        result = model.transcribe(temp_path, language=language)
        return result["text"].strip()
    finally:
        Path(temp_path).unlink(missing_ok=True)


async def _transcribe_whisper_api(audio_bytes: bytes, language: str) -> str:
    """Transcribe using OpenAI Whisper API."""
    import httpx

    from .. import config

    api_key = getattr(config, "OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured for Whisper API")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("audio.wav", audio_bytes, "audio/wav")},
            data={"model": "whisper-1", "language": language},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["text"].strip()


# ---------------------------------------------------------------------------
# TTS: Text-to-Speech
# ---------------------------------------------------------------------------


async def synthesize(
    text: str,
    provider: TTSProvider = TTSProvider.edge,
    language: str = "ko",
    voice: Optional[str] = None,
) -> dict:
    """Synthesize text to speech audio.

    Args:
        text: Text to synthesize
        provider: TTS provider to use
        language: Language code
        voice: Voice name (provider-specific, uses default if None)

    Returns:
        Dict with 'audio_bytes', 'content_type', 'duration_ms', 'provider'
    """
    t0 = time.time()

    if provider == TTSProvider.edge:
        audio_bytes, content_type = await _synthesize_edge(text, language, voice)
    elif provider == TTSProvider.google:
        audio_bytes, content_type = await _synthesize_google(text, language, voice)
    elif provider == TTSProvider.openai:
        audio_bytes, content_type = await _synthesize_openai(text, voice)
    else:
        raise ValueError(f"Unknown TTS provider: {provider}")

    elapsed = (time.time() - t0) * 1000
    logger.info(
        "TTS [%s]: %d chars -> %d bytes (%.0fms)",
        provider.value, len(text), len(audio_bytes), elapsed,
    )

    return {
        "audio_bytes": audio_bytes,
        "content_type": content_type,
        "duration_ms": round(elapsed, 1),
        "provider": provider.value,
    }


async def _synthesize_edge(
    text: str, language: str, voice: Optional[str]
) -> tuple[bytes, str]:
    """Synthesize using Microsoft Edge TTS (free, no API key needed)."""
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("Install edge-tts: pip install edge-tts")

    # Default voices per language
    default_voices = {
        "ko": "ko-KR-SunHiNeural",
        "en": "en-US-AriaNeural",
        "ja": "ja-JP-NanamiNeural",
    }
    voice_name = voice or default_voices.get(language, "en-US-AriaNeural")

    communicate = edge_tts.Communicate(text, voice_name)
    audio_data = b""

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]

    return audio_data, "audio/mpeg"


async def _synthesize_google(
    text: str, language: str, voice: Optional[str]
) -> tuple[bytes, str]:
    """Synthesize using Google Cloud TTS."""
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()

    # Default voices
    default_voices = {
        "ko": "ko-KR-Neural2-A",
        "en": "en-US-Neural2-J",
        "ja": "ja-JP-Neural2-B",
    }
    voice_name = voice or default_voices.get(language, "en-US-Neural2-J")

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice_params = texttospeech.VoiceSelectionParams(
        language_code=language,
        name=voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.0,
    )

    response = client.synthesize_speech(
        input=synthesis_input, voice=voice_params, audio_config=audio_config
    )

    return response.audio_content, "audio/mpeg"


async def _synthesize_openai(
    text: str, voice: Optional[str]
) -> tuple[bytes, str]:
    """Synthesize using OpenAI TTS API."""
    import httpx

    from .. import config

    api_key = getattr(config, "OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured for OpenAI TTS")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "tts-1",
                "input": text,
                "voice": voice or "alloy",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.content, "audio/mpeg"
