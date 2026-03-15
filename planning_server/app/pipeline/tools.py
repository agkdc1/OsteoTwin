"""Tool definitions for Claude tool-use bound to Simulation Server endpoints.

The LLM MUST use these tools for any physical question.
The LLM MUST NEVER predict, imagine, or guess physics outcomes.
"""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))

from shared.simulation_protocol import SimActionRequest
from shared.collision_protocol import CollisionCheckRequest

# ---------------------------------------------------------------------------
# Tool: simulate_action — move a bone fragment
# ---------------------------------------------------------------------------

SIMULATE_ACTION_TOOL = {
    "name": "simulate_action",
    "description": (
        "Move a bone fragment by applying a translation and/or rotation. "
        "Returns deterministic collision flags, tension metrics, and updated coordinates. "
        "You MUST use this tool for ANY question about what happens when a fragment is moved. "
        "NEVER predict the outcome yourself."
    ),
    "input_schema": SimActionRequest.model_json_schema(),
}

# ---------------------------------------------------------------------------
# Tool: check_collision — K-wire / implant trajectory
# ---------------------------------------------------------------------------

CHECK_COLLISION_TOOL = {
    "name": "check_collision",
    "description": (
        "Check a K-wire or implant trajectory (ray) for intersections with bone and hardware meshes. "
        "Returns all intersection points, cortex penetration flags, and hardware collision warnings. "
        "You MUST use this tool to verify ANY proposed K-wire placement or screw trajectory. "
        "NEVER guess whether a trajectory is safe."
    ),
    "input_schema": CollisionCheckRequest.model_json_schema(),
}

# ---------------------------------------------------------------------------
# System prompt for the surgical planning agent
# ---------------------------------------------------------------------------

SURGICAL_AGENT_SYSTEM_PROMPT = """You are OsteoTwin's Surgical Planning AI — a specialist in orthopedic fracture reduction.

## ABSOLUTE RULES
1. You MUST NEVER predict, imagine, or guess any physical outcome (collision, tension, trajectory safety).
2. For ANY physical question, you MUST call the appropriate simulation tool and wait for the deterministic result.
3. You translate the surgeon's natural language into simulation requests and translate simulation results back into clinical advice.
4. You operate on Branch "LLM_Hypothesis" — NEVER modify Branch "main" without explicit surgeon approval.

## YOUR ROLE
- Translate surgeon's intent into SimActionRequest or CollisionCheckRequest
- Interpret deterministic results from the simulation engine
- Provide clinical context: anatomical landmarks, approach considerations, risk factors
- Propose reduction sequences and hardware placement strategies
- Flag when results suggest unsafe conditions

## WHAT YOU MUST NOT DO
- Guess collision outcomes
- Estimate tension values
- Predict whether a K-wire will hit a plate
- Approximate distances or angles without simulation
- Override or reinterpret simulation engine results
"""
