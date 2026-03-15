"""Schemas for the Multi-Agent (Claude vs Gemini) surgical plan debate."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    PRIMARY = "primary"  # Claude
    SECONDARY = "secondary"  # Gemini
    ARBITER = "arbiter"  # Tie-breaking / consensus


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class SurgicalPlan(BaseModel):
    """A single surgical plan proposed by an agent."""

    plan_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    plan_label: str = Field(..., description='e.g. "Plan A", "Plan B"')

    approach: str = Field(
        ..., description="Surgical approach description (e.g., dorsal, volar)"
    )
    reduction_sequence: list[str] = Field(
        ...,
        description="Ordered steps for fracture reduction",
    )
    hardware_recommendation: list[str] = Field(
        default_factory=list,
        description='e.g. ["Volar locking plate", "2x K-wires 1.6mm"]',
    )

    estimated_risk: RiskLevel = Field(default=RiskLevel.MODERATE)
    risk_justification: str = Field(
        default="", description="Why the agent assigned this risk level"
    )

    # Simulation-validated fields (filled after deterministic sim)
    simulation_id: Optional[str] = Field(
        None, description="Link to the ReductionSimulation that validated this plan"
    )
    collision_count: Optional[int] = None
    reduction_score: Optional[float] = Field(None, ge=0.0, le=1.0)


class AgentResponse(BaseModel):
    """A single agent's contribution to one round of debate."""

    agent: AgentRole
    model_id: str = Field(
        ..., description='Model identifier, e.g. "claude-opus-4-6-20250514"'
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    proposed_plans: list[SurgicalPlan] = Field(
        default_factory=list, description="Plans proposed in this round"
    )
    critique_of_other: Optional[str] = Field(
        None,
        description="Critique of the other agent's plan from the previous round",
    )
    consensus_notes: Optional[str] = Field(
        None, description="Areas of agreement between agents"
    )
    dissent_notes: Optional[str] = Field(
        None, description="Areas of disagreement requiring human judgment"
    )


class DebateRound(BaseModel):
    """One round of the multi-agent debate."""

    round_number: int = Field(..., ge=1)
    primary_response: AgentResponse
    secondary_response: AgentResponse


class AgentDebate(BaseModel):
    """Full multi-agent debate session for a fracture case."""

    debate_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    case_id: str = Field(..., description="Reference to the parent FractureCase")
    initiated_at: datetime = Field(default_factory=datetime.utcnow)

    # Debate configuration
    max_rounds: int = Field(default=3, ge=1, le=5)
    require_simulation_validation: bool = Field(
        default=True,
        description="If True, plans must pass deterministic simulation before acceptance",
    )

    # Debate content
    rounds: list[DebateRound] = Field(default_factory=list)

    # Outcome
    selected_plan: Optional[SurgicalPlan] = Field(
        None, description="The plan chosen after debate concludes"
    )
    surgeon_override: Optional[str] = Field(
        None, description="If the surgeon overrode the AI recommendation, why"
    )
    status: str = Field(
        default="pending",
        description='One of: pending, in_progress, consensus, dissent, surgeon_decided',
    )
