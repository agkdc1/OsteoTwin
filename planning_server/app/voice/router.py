"""Voice Assistant API endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..auth.dependencies import get_current_user
from .orchestrator import VoiceAgentOrchestrator
from .audio import transcribe, synthesize, STTProvider, TTSProvider

logger = logging.getLogger("osteotwin.voice.router")

router = APIRouter(
    prefix="/api/v1/voice",
    tags=["voice"],
    dependencies=[Depends(get_current_user)],
)

# Active voice sessions (case_id -> orchestrator)
_sessions: dict[str, VoiceAgentOrchestrator] = {}


class VoiceQueryRequest(BaseModel):
    """Text query simulating STT output (or actual transcribed text)."""

    text: str = Field(
        ...,
        min_length=1,
        description="Transcribed speech or text query from the surgeon",
    )
    case_id: str = Field(..., description="Active fracture case ID")
    surgical_plan: Optional[str] = Field(
        default=None,
        description="Full surgical plan report (injected into system prompt on first query)",
    )


class VoiceQueryResponse(BaseModel):
    """Response for TTS playback."""

    response: str = Field(..., description="Clinical response text (for TTS)")
    tool_calls: list[dict] = Field(
        default_factory=list, description="Simulation tools called"
    )
    simulation_results: list[dict] = Field(
        default_factory=list, description="Deterministic simulation results"
    )
    processing_time_ms: float = Field(
        default=0.0, description="Total processing time"
    )
    session_active: bool = Field(
        default=True, description="Whether the voice session is still active"
    )


@router.post("/query", response_model=VoiceQueryResponse)
async def voice_query(req: VoiceQueryRequest) -> VoiceQueryResponse:
    """Process a voice query (text-in, text-out).

    The surgeon says something like "Osteo, check the K-wire trajectory"
    and this endpoint returns a concise clinical response suitable for TTS.

    Sessions are maintained per case_id — conversation context persists
    across queries within the same surgical session.
    """
    # Get or create voice session for this case
    if req.case_id not in _sessions:
        _sessions[req.case_id] = VoiceAgentOrchestrator(
            case_id=req.case_id,
            surgical_plan=req.surgical_plan,
        )
    elif req.surgical_plan:
        # Update surgical plan if provided
        session = _sessions[req.case_id]
        session.surgical_plan = req.surgical_plan
        from .prompts import build_voice_system_prompt

        session.system_prompt = build_voice_system_prompt(req.surgical_plan)

    orchestrator = _sessions[req.case_id]

    result = await orchestrator.process_text_query(req.text)

    return VoiceQueryResponse(
        response=result["response"],
        tool_calls=result.get("tool_calls", []),
        simulation_results=result.get("simulation_results", []),
        processing_time_ms=result.get("processing_time_ms", 0.0),
        session_active=True,
    )


@router.post("/reset")
async def reset_voice_session(case_id: str):
    """Reset the voice session for a case (clear conversation history)."""
    if case_id in _sessions:
        _sessions[case_id].reset_conversation()
        return {"reset": True, "case_id": case_id}
    return {"reset": False, "case_id": case_id, "reason": "No active session"}


@router.post("/speak")
async def voice_speak(
    audio: UploadFile = File(..., description="Audio file (WAV, MP3, WEBM)"),
    case_id: str = Form(...),
    surgical_plan: Optional[str] = Form(None),
    ao_code: Optional[str] = Form(None),
    language: str = Form("ko"),
    stt_provider: str = Form("whisper_local"),
    tts_provider: str = Form("edge"),
):
    """Full audio-in, audio-out voice pipeline.

    1. STT: Transcribe uploaded audio to text
    2. Orchestrator: Process query with simulation tools
    3. TTS: Synthesize response to audio

    Returns MP3 audio of the clinical response.
    """
    # Step 1: STT
    audio_bytes = await audio.read()
    stt_result = await transcribe(
        audio_bytes,
        provider=STTProvider(stt_provider),
        language=language,
    )
    transcribed_text = stt_result["text"]

    if not transcribed_text.strip():
        return Response(
            content=b"",
            media_type="audio/mpeg",
            headers={"X-Transcription": "", "X-Error": "Empty transcription"},
        )

    # Step 2: Process query
    if case_id not in _sessions:
        _sessions[case_id] = VoiceAgentOrchestrator(
            case_id=case_id,
            surgical_plan=surgical_plan,
            ao_code=ao_code,
        )

    orchestrator = _sessions[case_id]
    result = await orchestrator.process_text_query(transcribed_text)
    response_text = result["response"]

    # Step 3: TTS
    tts_result = await synthesize(
        response_text,
        provider=TTSProvider(tts_provider),
        language=language,
    )

    return Response(
        content=tts_result["audio_bytes"],
        media_type=tts_result["content_type"],
        headers={
            "X-Transcription": transcribed_text[:200],
            "X-Response-Text": response_text[:200],
            "X-STT-Provider": stt_result["provider"],
            "X-TTS-Provider": tts_result["provider"],
            "X-STT-Duration-Ms": str(stt_result["duration_ms"]),
            "X-Processing-Duration-Ms": str(result.get("processing_time_ms", 0)),
            "X-TTS-Duration-Ms": str(tts_result["duration_ms"]),
        },
    )


@router.get("/sessions")
async def list_voice_sessions():
    """List active voice sessions."""
    return {
        "sessions": [
            {
                "case_id": case_id,
                "conversation_length": len(orch.conversation_history),
                "has_surgical_plan": orch.surgical_plan is not None,
            }
            for case_id, orch in _sessions.items()
        ]
    }
