"""Strict JSON protocol for LLM ↔ Simulation Server communication.

The LLM MUST use SimActionRequest to interact with the deterministic engine.
The LLM MUST NEVER predict, imagine, or guess physical outcomes.
All physics results come exclusively from SimActionResponse.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request: LLM → Simulation Server
# ---------------------------------------------------------------------------


class AnatomicalConstraint(str, Enum):
    """Named anatomical boundaries the simulation must respect."""

    RADIAL_NERVE = "radial_nerve"
    ULNAR_NERVE = "ulnar_nerve"
    MEDIAN_NERVE = "median_nerve"
    BRACHIAL_ARTERY = "brachial_artery"
    SUPRASPINATUS_TENDON = "supraspinatus_tendon"
    ARTICULAR_SURFACE = "articular_surface"
    GROWTH_PLATE = "growth_plate"
    PERIOSTEUM = "periosteum"


class RotationMatrix(BaseModel):
    """3×3 rotation matrix (row-major)."""

    r00: float = 1.0
    r01: float = 0.0
    r02: float = 0.0
    r10: float = 0.0
    r11: float = 1.0
    r12: float = 0.0
    r20: float = 0.0
    r21: float = 0.0
    r22: float = 1.0


class TranslationVector(BaseModel):
    """Translation in mm along each axis."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class SimActionRequest(BaseModel):
    """Request from the LLM to the Simulation Server.

    The LLM constructs this from the user's natural-language instruction.
    The Simulation Server executes the action deterministically and returns
    a SimActionResponse.
    """

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    case_id: str = Field(..., description="Parent FractureCase ID")
    branch: str = Field(
        default="LLM_Hypothesis",
        description="Simulation branch to operate on (never 'main' unless user-approved)",
    )

    # Target fragment
    fragment_id: str = Field(
        ..., description="ID of the bone fragment to manipulate"
    )

    # Requested transformation
    translation: TranslationVector = Field(default_factory=TranslationVector)
    rotation: RotationMatrix = Field(default_factory=RotationMatrix)

    # Anatomical constraints the engine must check
    anatomical_constraints: list[AnatomicalConstraint] = Field(
        default_factory=list,
        description="Anatomical boundaries to enforce during this action",
    )

    # Optional hardware placement
    place_hardware: Optional[str] = Field(
        None,
        description='Hardware to place, e.g. "k_wire_1.6mm" or "lcp_plate_6hole"',
    )
    hardware_position: Optional[TranslationVector] = None
    hardware_orientation: Optional[RotationMatrix] = None


# ---------------------------------------------------------------------------
# Response: Simulation Server → LLM
# ---------------------------------------------------------------------------


class CollisionFlag(BaseModel):
    """A single collision detected by the deterministic engine."""

    object_a: str
    object_b: str
    penetration_mm: float = Field(
        ..., description="Penetration depth in millimeters"
    )
    description: str = Field(
        ..., description='e.g. "K-wire intersects Plate hole 3"'
    )
    is_critical: bool = Field(
        default=False,
        description="True if this collision makes the action unsafe",
    )


class TensionMetric(BaseModel):
    """Soft-tissue tension estimate at a named attachment point."""

    structure_name: str = Field(
        ..., description='e.g. "supraspinatus tendon"'
    )
    tension_n: float = Field(
        ..., description="Estimated tension in Newtons"
    )
    threshold_n: float = Field(
        ..., description="Safe threshold in Newtons"
    )
    exceeded: bool = Field(
        default=False, description="True if tension > threshold"
    )


class UpdatedFragmentCoords(BaseModel):
    """Post-action coordinates for the moved fragment."""

    fragment_id: str
    position: TranslationVector
    rotation: RotationMatrix


class SimActionResponse(BaseModel):
    """Deterministic response from the Simulation Server.

    The LLM must read these results and translate them into clinical advice.
    The LLM must NEVER override or reinterpret the collision/tension data.
    """

    request_id: str = Field(..., description="Echo of the originating request ID")
    success: bool = Field(
        ..., description="Whether the action was executed without critical failures"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Updated state
    updated_coords: Optional[UpdatedFragmentCoords] = None

    # Collision results
    collisions: list[CollisionFlag] = Field(default_factory=list)
    total_collisions: int = 0
    has_critical_collision: bool = False

    # Tension results
    tension_metrics: list[TensionMetric] = Field(default_factory=list)
    max_tension_exceeded: bool = False

    # Summary for LLM consumption
    engine_summary: str = Field(
        default="",
        description="Human-readable summary of what the engine computed",
    )

    # Branch snapshot
    branch: str = Field(default="LLM_Hypothesis")
    snapshot_id: Optional[str] = Field(
        None, description="Opaque ID to restore this exact state"
    )
