"""API routes for the surgical planning pipeline."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth.dependencies import get_current_user
from ..database import User
from fastapi.responses import JSONResponse

from .orchestrator import run_surgical_query
from .debate import run_debate
from .pubsub import publish_simulation_task

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


class SurgicalQueryRequest(BaseModel):
    query: str = Field(..., description="Natural-language surgical planning query")
    case_id: str = Field(..., description="FractureCase ID")
    ao_code: Optional[str] = Field(None, description="AO classification code")


class DebateRequest(BaseModel):
    case_summary: str = Field(..., description="Clinical description of the fracture")
    case_id: str = Field(..., description="FractureCase ID")
    ao_code: Optional[str] = Field(None, description="AO classification code")
    max_rounds: int = Field(default=3, ge=1, le=5)


@router.post("/query")
async def surgical_query(req: SurgicalQueryRequest, user: User = Depends(get_current_user)):
    """Send a natural-language surgical query to the LLM with simulation tools."""
    result = await run_surgical_query(
        req.query,
        req.case_id,
        ao_code=req.ao_code,
    )
    return result


@router.post("/debate")
async def start_debate(req: DebateRequest, user: User = Depends(get_current_user)):
    """Start a multi-agent debate (Claude vs Gemini) for a fracture case."""
    debate = await run_debate(
        req.case_summary,
        req.case_id,
        ao_code=req.ao_code,
        max_rounds=req.max_rounds,
    )
    return debate.model_dump(mode="json")


class AsyncSimRequest(BaseModel):
    task: dict = Field(..., description="SimActionRequest or CollisionCheckRequest as dict")
    task_type: str = Field(default="action", description="'action' or 'collision'")


@router.post("/simulate/async", status_code=202)
async def submit_async_simulation(
    req: AsyncSimRequest,
    user: User = Depends(get_current_user),
):
    """Submit a simulation task for async processing (Pub/Sub → Worker).

    Returns HTTP 202 Accepted with a task_id for polling.
    Falls back to direct HTTP if Pub/Sub is not configured.
    """
    task = {**req.task, "task_type": req.task_type}
    result = await publish_simulation_task(task)

    status_code = 202 if result["status"] == "queued" else 200
    return JSONResponse(content=result, status_code=status_code)
