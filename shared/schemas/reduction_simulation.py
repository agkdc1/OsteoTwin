"""Schemas for fracture-reduction simulation state and results."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class CollisionWarning(BaseModel):
    """A single collision or constraint violation detected by the simulation."""

    warning_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    severity: SeverityLevel
    description: str = Field(
        ..., description='e.g. "K-wire intersects Plate hole 3"'
    )
    fragment_a: str = Field(..., description="First colliding object identifier")
    fragment_b: str = Field(..., description="Second colliding object identifier")
    penetration_depth_mm: Optional[float] = Field(
        None, description="Penetration depth in mm (if applicable)"
    )


class AppliedVector(BaseModel):
    """A translation or force vector applied to a bone fragment."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    magnitude_mm: Optional[float] = Field(
        None, description="Magnitude in mm (computed)"
    )


class FragmentState(BaseModel):
    """Current spatial state of a single bone fragment in the simulation."""

    fragment_id: str
    label: str = Field(
        ..., description='Human-readable label, e.g. "Distal fragment"'
    )
    position: AppliedVector = Field(
        default_factory=AppliedVector, description="World-space position (mm)"
    )
    rotation_euler_deg: AppliedVector = Field(
        default_factory=AppliedVector,
        description="Euler rotation in degrees (x=roll, y=pitch, z=yaw)",
    )
    mesh_path: Optional[str] = Field(
        None, description="Path to the STL/PLY mesh file for this fragment"
    )


class ReductionSimulation(BaseModel):
    """Full state of a fracture-reduction simulation."""

    simulation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    case_id: str = Field(..., description="Reference to the parent FractureCase")
    branch: str = Field(
        default="main",
        description="State branch name (main = user view, LLM_Hypothesis = AI sandbox)",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Fragment states
    fragments: list[FragmentState] = Field(default_factory=list)

    # Applied vectors history
    applied_vectors: list[AppliedVector] = Field(default_factory=list)

    # Collision analysis
    collision_warnings: list[CollisionWarning] = Field(default_factory=list)
    has_critical_collision: bool = Field(default=False)

    # Hardware placement
    hardware: list[str] = Field(
        default_factory=list,
        description='Placed hardware identifiers, e.g. ["k_wire_1", "plate_lcp_3hole"]',
    )

    # Overall metrics
    reduction_quality_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="0.0 = no reduction, 1.0 = anatomic reduction",
    )
