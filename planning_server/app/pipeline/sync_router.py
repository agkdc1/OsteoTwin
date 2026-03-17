"""Bi-directional UI sync endpoint.

Receives SurgicalAction payloads from the frontend when the surgeon
manually manipulates fragments via drag-and-drop in the 3D viewer.

Responsibilities:
1. Validate the incoming SurgicalAction
2. Forward to the Simulation Server for deterministic physics
3. Append a context note to Claude's session so the AI stays aware
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import sys, pathlib

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)
)
from shared.schemas import SurgicalAction, ActionType
from shared.kinematics import surgical_action_to_sim_request

from ..simulation_client.client import sim_client

logger = logging.getLogger("osteotwin.sync")

router = APIRouter(prefix="/api/v1/simulation", tags=["ui-sync"])

# ---------------------------------------------------------------------------
# In-memory action log (appended to Claude's context on next query)
# ---------------------------------------------------------------------------

# case_id → list of context notes
_ui_action_log: dict[str, list[str]] = {}


def get_and_clear_ui_notes(case_id: str) -> list[str]:
    """Retrieve and clear pending UI action notes for a case.

    Called by the orchestrator before building Claude's messages
    so the AI is aware of manual manipulations since the last query.
    """
    notes = _ui_action_log.pop(case_id, [])
    return notes


def _append_note(case_id: str, note: str) -> None:
    _ui_action_log.setdefault(case_id, []).append(note)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class SyncUIActionResponse(BaseModel):
    success: bool
    action_type: str
    fragment_id: str
    engine_summary: str = ""
    context_note: str = Field(
        ..., description="The note appended to Claude's context"
    )


# Extend ActionType for manual drag (keep backward compat)
MANUAL_ACTION_TYPES = {
    "translate", "rotate", "translate_and_rotate",
    "manual_drag_translation", "manual_drag_rotation",
}


@router.post("/sync-ui-action", response_model=SyncUIActionResponse)
async def sync_ui_action(action: SurgicalAction) -> SyncUIActionResponse:
    """Receive a manual fragment manipulation from the 3D viewer.

    1. Validates the SurgicalAction payload
    2. Forwards to the Simulation Server for collision/tension check
    3. Appends a system note for Claude's next conversation turn
    """
    if action.action_type.value not in MANUAL_ACTION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unexpected action_type for UI sync: {action.action_type}",
        )

    case_id = action.case_id or "unknown"
    frag_id = action.target.fragment_id

    # Convert to SimActionRequest and forward to simulation server
    engine_summary = ""
    try:
        req = surgical_action_to_sim_request(action, case_id=case_id)
        result = await sim_client.simulate_action(req)
        engine_summary = result.engine_summary
        logger.info(
            "UI sync → sim complete: %s %s (collisions=%d)",
            frag_id, action.action_type.value, result.total_collisions,
        )
    except Exception as exc:
        logger.warning("UI sync → sim failed (non-blocking): %s", exc)
        engine_summary = f"Simulation unavailable: {exc}"

    # Build context note for Claude
    t = action.translation_mm
    r = action.rotation_deg
    parts = []
    if abs(t.x) > 0.01 or abs(t.y) > 0.01 or abs(t.z) > 0.01:
        parts.append(f"translated [{t.x:.1f}, {t.y:.1f}, {t.z:.1f}]mm (LPS)")
    if abs(r.x_deg) > 0.1 or abs(r.y_deg) > 0.1 or abs(r.z_deg) > 0.1:
        parts.append(f"rotated [{r.x_deg:.1f}, {r.y_deg:.1f}, {r.z_deg:.1f}]° (LPS)")

    context_note = (
        f"System Note: Surgeon manually {' and '.join(parts) or 'adjusted'} "
        f"`{frag_id}` ({action.target.color_code}) via 3D viewer."
    )
    if engine_summary:
        context_note += f" Sim: {engine_summary}"

    _append_note(case_id, context_note)

    return SyncUIActionResponse(
        success=True,
        action_type=action.action_type.value,
        fragment_id=frag_id,
        engine_summary=engine_summary,
        context_note=context_note,
    )
