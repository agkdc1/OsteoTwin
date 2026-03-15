"""Soft-tissue simulation protocol — Pydantic models for SOFA integration.

These schemas define the JSON contract between the Planning Server
(LLM orchestrator) and the Simulation Server (SOFA engine) for
soft-tissue biomechanics.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TissueType(str, Enum):
    muscle = "muscle"
    tendon = "tendon"
    ligament = "ligament"
    periosteum = "periosteum"
    nerve = "nerve"
    vessel = "vessel"


class AttachmentPoint(BaseModel):
    """An anatomical attachment point (origin/insertion) on a bone mesh."""

    label: str = Field(..., description="Anatomical name, e.g. 'supraspinatus_origin'")
    fragment_id: str = Field(..., description="ID of the bone fragment this attaches to")
    position: list[float] = Field(
        ..., min_length=3, max_length=3, description="[x, y, z] in mm"
    )


class SoftTissueDefinition(BaseModel):
    """Defines a soft-tissue structure connecting two attachment points."""

    tissue_id: str = Field(..., description="Unique identifier")
    tissue_type: TissueType
    label: str = Field(..., description="Anatomical name, e.g. 'supraspinatus'")
    origin: AttachmentPoint
    insertion: AttachmentPoint
    rest_length_mm: float = Field(..., gt=0, description="Resting length in mm")
    max_tension_n: float = Field(
        ..., gt=0, description="Maximum safe tension in Newtons"
    )
    stiffness: float = Field(
        default=100.0, gt=0, description="Spring stiffness (N/mm)"
    )
    young_modulus_mpa: Optional[float] = Field(
        default=None, description="Young's modulus for FEA (MPa)"
    )
    poisson_ratio: Optional[float] = Field(
        default=None, ge=0, le=0.5, description="Poisson ratio for FEA"
    )


class SoftTissueSimRequest(BaseModel):
    """Request to run a soft-tissue biomechanical simulation."""

    request_id: str = Field(..., description="Unique request ID for tracking")
    case_id: str = Field(..., description="Fracture case ID")
    branch: str = Field(default="LLM_Hypothesis", description="Simulation branch")

    # Fragment state — positions after rigid-body reduction
    fragment_positions: dict[str, list[float]] = Field(
        ..., description="fragment_id -> [x, y, z] position after reduction"
    )
    fragment_rotations: Optional[dict[str, list[list[float]]]] = Field(
        default=None, description="fragment_id -> 3x3 rotation matrix (optional)"
    )

    # Tissue definitions (override defaults if provided)
    tissues: Optional[list[SoftTissueDefinition]] = Field(
        default=None, description="Custom tissue definitions (uses defaults if omitted)"
    )

    # Simulation parameters
    num_steps: int = Field(default=100, ge=1, le=10000, description="Simulation steps")
    time_step_ms: float = Field(default=10.0, gt=0, description="Time step in ms")
    gravity: list[float] = Field(
        default=[0, 0, -9810], min_length=3, max_length=3,
        description="Gravity vector in mm/s^2"
    )


class TissueTensionResult(BaseModel):
    """Tension result for a single tissue structure."""

    tissue_id: str
    label: str
    tissue_type: TissueType
    current_length_mm: float = Field(..., description="Current stretched length")
    rest_length_mm: float
    strain_pct: float = Field(..., description="Strain percentage")
    tension_n: float = Field(..., description="Computed tension in Newtons")
    max_tension_n: float
    exceeded: bool = Field(..., description="True if tension > max safe value")
    risk_level: str = Field(
        ..., description="'safe', 'warning', or 'critical'"
    )


class VascularProximityResult(BaseModel):
    """Proximity of a fragment to a major vessel or nerve."""

    structure_label: str = Field(..., description="e.g. 'radial_artery'")
    tissue_type: TissueType
    min_distance_mm: float
    is_compressed: bool = Field(default=False)
    warning: Optional[str] = None


class SoftTissueSimResponse(BaseModel):
    """Deterministic response from the SOFA soft-tissue simulation."""

    request_id: str
    success: bool
    branch: str

    # Tension results
    tension_results: list[TissueTensionResult] = Field(default_factory=list)
    max_tension_exceeded: bool = Field(default=False)
    critical_tissues: list[str] = Field(
        default_factory=list,
        description="Labels of tissues with critical tension"
    )

    # Vascular/nerve proximity
    proximity_warnings: list[VascularProximityResult] = Field(default_factory=list)

    # Periosteal stripping
    estimated_periosteal_strip_mm2: Optional[float] = Field(
        default=None, description="Estimated area of periosteal stripping"
    )

    # Deformation field (for visualization)
    deformation_field_url: Optional[str] = Field(
        default=None, description="URL to download the deformation VTK file"
    )

    # Summary
    engine_summary: str = Field(
        ..., description="Human-readable summary of soft-tissue state"
    )
    simulation_time_ms: float = Field(
        default=0.0, description="Wall-clock time for simulation"
    )
