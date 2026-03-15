"""Voice Assistant API endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.dependencies import get_current_user
from .orchestrator import VoiceAgentOrchestrator

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
