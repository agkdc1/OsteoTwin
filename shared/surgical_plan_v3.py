"""SurgicalPlan v3 — Unified schema bridging 3D engine with AI reasoning.

Covers: reduction sequencing, clamping physics, interference detection,
stability metrics, and multi-modal Gemini collaboration.

This schema is the single payload exchanged between:
- Simulation Server (physics engine)
- Planning Server (LLM orchestrator)
- Gemini (visual reasoning / multi-modal validation)
- React Dashboard (3D viewer)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Camera / Rendering Metadata
# ---------------------------------------------------------------------------

class CameraView(BaseModel):
    """Standardized camera position for 6-axis orthogonal rendering."""

    view_name: str = Field(..., description="e.g., 'AP', 'Lateral', 'Oblique_45'")
    position: list[float] = Field(
        ..., min_length=3, max_length=3, description="Camera position [x, y, z] in LPS mm"
    )
    rotation: list[float] = Field(
        ..., min_length=3, max_length=3, description="Camera rotation [theta_x, theta_y, theta_z] in degrees"
    )
    projection: str = Field(default="orthographic", description="'orthographic' or 'perspective'")
    fov_mm: Optional[float] = Field(None, description="Field of view width in mm (ortho)")


STANDARD_VIEWS = [
    CameraView(view_name="AP", position=[0, 500, 0], rotation=[90, 0, 0]),
    CameraView(view_name="Lateral_L", position=[500, 0, 0], rotation=[90, 0, 90]),
    CameraView(view_name="Lateral_R", position=[-500, 0, 0], rotation=[90, 0, -90]),
    CameraView(view_name="Oblique_45_L", position=[354, 354, 0], rotation=[90, 0, 45]),
    CameraView(view_name="Oblique_45_R", position=[-354, 354, 0], rotation=[90, 0, -45]),
    CameraView(view_name="Axial_Sup", position=[0, 0, 500], rotation=[0, 0, 0]),
]


# ---------------------------------------------------------------------------
# Reduction Priority Tree
# ---------------------------------------------------------------------------

class ReductionPriority(str, Enum):
    """Reduction sequence priority levels (highest first)."""
    ARTICULAR_SURFACE = "articular_surface"       # Priority 1: restore joint congruity
    METAPHYSEAL_ALIGNMENT = "metaphyseal_alignment"  # Priority 2: realign metaphysis
    SHAFT_ALIGNMENT = "shaft_alignment"            # Priority 3: restore shaft axis
    ROTATIONAL_ALIGNMENT = "rotational_alignment"  # Priority 4: correct rotation
    LENGTH_RESTORATION = "length_restoration"       # Priority 5: restore limb length


class ReductionStep(BaseModel):
    """A single step in the fracture reduction sequence."""

    step_number: int = Field(..., ge=1)
    priority: ReductionPriority
    description: str = Field(..., description="Clinical description of this reduction maneuver")
    target_fragment_ids: list[str] = Field(..., description="Fragment IDs involved")
    reference_fragment_id: Optional[str] = Field(
        None, description="Fixed reference fragment (the one that doesn't move)"
    )
    translation_mm: list[float] = Field(
        default=[0, 0, 0], min_length=3, max_length=3, description="Required translation [x,y,z] LPS"
    )
    rotation_deg: list[float] = Field(
        default=[0, 0, 0], min_length=3, max_length=3, description="Required rotation [rx,ry,rz] LPS"
    )
    estimated_resistance_n: Optional[float] = Field(
        None, description="Estimated soft-tissue resistance force (N) from spring-mass/SOFA"
    )
    requires_clamp: bool = Field(default=False)
    clamp_id: Optional[str] = Field(None, description="Clamp used for this step")
    verification_view: Optional[str] = Field(
        None, description="Best C-arm view to verify this step (e.g., 'AP', 'Lateral')"
    )


# ---------------------------------------------------------------------------
# Clamp Library
# ---------------------------------------------------------------------------

class ClampType(str, Enum):
    POINTED = "pointed"            # Weber pointed reduction clamp
    SERRATED = "serrated"          # Serrated jaw reduction clamp
    PELVIC = "pelvic"              # Jungbluth/Matta pelvic clamp
    LOBSTER_CLAW = "lobster_claw"  # Lobster claw (Verbrugge)
    SPEED_LOCK = "speed_lock"      # Speed lock clamp
    BONE_HOLDING = "bone_holding"  # Standard bone-holding forceps
    TOWEL_CLIP = "towel_clip"      # Backhaus towel clip (temporary)


class ClampSpec(BaseModel):
    """Physical specification of a reduction clamp."""

    clamp_id: str = Field(..., description="Unique clamp identifier")
    clamp_type: ClampType
    name: str = Field(..., description="e.g., 'Weber Pointed Reduction Clamp 180mm'")

    # Physical dimensions
    jaw_span_mm: tuple[float, float] = Field(
        ..., description="Min and max jaw opening (mm)"
    )
    jaw_depth_mm: float = Field(..., description="How deep the jaw reaches (mm)")
    handle_length_mm: float = Field(default=180.0)

    # Force characteristics
    max_clamping_force_n: float = Field(
        ..., description="Maximum clamping force (N)"
    )
    force_at_typical_use_n: float = Field(
        ..., description="Typical operating force (N)"
    )

    # Geometry for collision detection
    bounding_radius_mm: float = Field(
        ..., description="Bounding sphere radius for quick collision pre-check"
    )

    # Usage context
    suitable_for: list[str] = Field(
        default_factory=list,
        description="Fracture types this clamp is suitable for",
    )
    notes: str = Field(default="")


# Pre-defined clamp library
CLAMP_LIBRARY: dict[str, ClampSpec] = {
    "weber_pointed_180": ClampSpec(
        clamp_id="weber_pointed_180",
        clamp_type=ClampType.POINTED,
        name="Weber Pointed Reduction Clamp 180mm",
        jaw_span_mm=(0, 100), jaw_depth_mm=35,
        max_clamping_force_n=300, force_at_typical_use_n=150,
        bounding_radius_mm=95,
        suitable_for=["simple_fracture", "oblique_fracture", "spiral_fracture"],
        notes="Most common. Points engage cortex directly.",
    ),
    "weber_pointed_240": ClampSpec(
        clamp_id="weber_pointed_240",
        clamp_type=ClampType.POINTED,
        name="Weber Pointed Reduction Clamp 240mm",
        jaw_span_mm=(0, 140), jaw_depth_mm=45,
        max_clamping_force_n=400, force_at_typical_use_n=200,
        bounding_radius_mm=125,
        suitable_for=["femur_shaft", "tibia_shaft", "larger_bones"],
    ),
    "serrated_190": ClampSpec(
        clamp_id="serrated_190",
        clamp_type=ClampType.SERRATED,
        name="Serrated Jaw Reduction Clamp 190mm",
        jaw_span_mm=(0, 90), jaw_depth_mm=30,
        max_clamping_force_n=250, force_at_typical_use_n=120,
        bounding_radius_mm=90,
        suitable_for=["metaphyseal_fracture", "periarticular"],
        notes="Serrated jaws prevent slipping on cancellous bone.",
    ),
    "pelvic_jungbluth": ClampSpec(
        clamp_id="pelvic_jungbluth",
        clamp_type=ClampType.PELVIC,
        name="Jungbluth Pelvic Reduction Clamp",
        jaw_span_mm=(0, 250), jaw_depth_mm=80,
        max_clamping_force_n=800, force_at_typical_use_n=400,
        bounding_radius_mm=200,
        suitable_for=["pelvic_ring", "acetabulum", "sacroiliac"],
        notes="Large clamp for pelvic reduction. Percutaneous application possible.",
    ),
    "verbrugge_lobster": ClampSpec(
        clamp_id="verbrugge_lobster",
        clamp_type=ClampType.LOBSTER_CLAW,
        name="Verbrugge Lobster Claw Bone Holder",
        jaw_span_mm=(0, 70), jaw_depth_mm=25,
        max_clamping_force_n=200, force_at_typical_use_n=100,
        bounding_radius_mm=70,
        suitable_for=["plate_holding", "temporary_fixation"],
        notes="Holds bone against plate during screw insertion.",
    ),
    "speed_lock_self": ClampSpec(
        clamp_id="speed_lock_self",
        clamp_type=ClampType.SPEED_LOCK,
        name="Speed Lock Self-Centering Clamp",
        jaw_span_mm=(10, 80), jaw_depth_mm=28,
        max_clamping_force_n=280, force_at_typical_use_n=140,
        bounding_radius_mm=85,
        suitable_for=["simple_fracture", "transverse_fracture"],
        notes="Self-centering jaws. Maintains axial alignment during reduction.",
    ),
}


# ---------------------------------------------------------------------------
# Clamping State & Stability
# ---------------------------------------------------------------------------

class ClampPlacement(BaseModel):
    """A clamp placed in the scene."""

    clamp_id: str = Field(..., description="Clamp spec ID from CLAMP_LIBRARY")
    placement_id: str = Field(..., description="Unique ID for this placement instance")
    fragment_a_id: str = Field(..., description="First fragment the clamp grips")
    fragment_b_id: str = Field(..., description="Second fragment the clamp grips")
    position_lps: list[float] = Field(
        ..., min_length=3, max_length=3, description="Clamp center position in LPS"
    )
    orientation_deg: list[float] = Field(
        default=[0, 0, 0], min_length=3, max_length=3, description="Clamp orientation"
    )
    applied_force_n: float = Field(
        default=0.0, description="Currently applied clamping force (N)"
    )
    is_active: bool = Field(default=True)


class StabilityMetric(BaseModel):
    """Stability evaluation for a fragment-fragment junction."""

    fragment_a_id: str
    fragment_b_id: str
    stability_n_per_mm: float = Field(
        ..., description="Stiffness at the junction (N/mm) — higher = more stable"
    )
    max_displacement_under_load_mm: float = Field(
        ..., description="Max fragment displacement under physiological load"
    )
    fixation_method: str = Field(
        ..., description="What's holding it: 'clamp_only', 'kwire', 'plate_screws', 'clamp+kwire'"
    )
    risk_level: str = Field(
        default="safe", description="'safe', 'marginal', 'unstable'"
    )


class DeltaStability(BaseModel):
    """Change in stability when a clamp is removed.

    Critical for deciding when it's safe to remove temporary fixation
    after permanent hardware is placed.
    """

    removed_clamp_id: str
    before_stability_n_per_mm: float
    after_stability_n_per_mm: float
    delta_pct: float = Field(..., description="Percentage change in stability")
    is_safe_to_remove: bool = Field(
        ..., description="True if remaining fixation provides adequate stability"
    )
    minimum_required_n_per_mm: float = Field(
        default=50.0, description="Minimum acceptable stability after removal"
    )
    notes: str = Field(default="")


# ---------------------------------------------------------------------------
# Interference Detection
# ---------------------------------------------------------------------------

class InterferenceType(str, Enum):
    KWIRE_CLAMP = "kwire_clamp"          # K-wire hits existing clamp
    KWIRE_PLATE = "kwire_plate"          # K-wire blocks plate placement
    CLAMP_PLATE = "clamp_plate"          # Clamp blocks plate trajectory
    KWIRE_NERVE = "kwire_nerve"          # K-wire enters neurovascular danger zone
    KWIRE_VESSEL = "kwire_vessel"        # K-wire near major vessel
    KWIRE_TENDON = "kwire_tendon"        # K-wire through tendon
    SCREW_JOINT = "screw_joint"          # Screw penetrates joint surface
    APPROACH_CONFLICT = "approach_conflict"  # Tool access blocked by approach constraints


class InterferenceResult(BaseModel):
    """A single interference/collision detected."""

    interference_type: InterferenceType
    severity: str = Field(..., description="'critical', 'warning', 'info'")
    object_a: str = Field(..., description="First object (e.g., 'kwire_1')")
    object_b: str = Field(..., description="Second object (e.g., 'clamp_weber_1')")
    distance_mm: Optional[float] = Field(
        None, description="Distance between objects (negative = penetration)"
    )
    location_lps: Optional[list[float]] = Field(
        None, description="Location of interference in LPS"
    )
    suggestion: str = Field(
        default="", description="Suggested resolution (e.g., 'Relocate clamp 15mm distally')"
    )
    view_for_verification: Optional[str] = Field(
        None, description="Best C-arm view to visually verify this interference"
    )


# ---------------------------------------------------------------------------
# Gemini Inference Query
# ---------------------------------------------------------------------------

class GeminiInferenceQuery(BaseModel):
    """A structured query for Gemini's visual reasoning.

    Sent alongside the 6-view rendered image for multi-modal validation.
    """

    query_id: str
    view_name: str = Field(..., description="Which rendered view to analyze")
    question: str = Field(
        ..., description="Specific question for Gemini, e.g., 'Assess clearance between K-wire and pointed clamp'"
    )
    context: dict = Field(
        default_factory=dict,
        description="Mechanical vectors, stability metrics, etc. for grounding",
    )
    expected_output: str = Field(
        default="<status>SAFE</status> or <status>COLLISION</status> with explanation",
    )


# ---------------------------------------------------------------------------
# SurgicalPlan v3 — Top-level schema
# ---------------------------------------------------------------------------

class SurgicalPlanV3(BaseModel):
    """Unified surgical plan bridging 3D engine, AI reasoning, and multi-modal validation.

    This is the master payload for a complete fracture reduction plan.
    """

    # --- Metadata ---
    plan_id: str
    case_id: str
    ao_code: Optional[str] = None
    target_anatomy: str
    created_by: str = Field(default="claude", description="'claude', 'gemini', or 'surgeon'")

    # --- Reduction Sequence ---
    reduction_steps: list[ReductionStep] = Field(
        default_factory=list,
        description="Ordered sequence of reduction maneuvers",
    )

    # --- Clamping ---
    clamp_placements: list[ClampPlacement] = Field(
        default_factory=list,
    )
    stability_metrics: list[StabilityMetric] = Field(
        default_factory=list,
    )
    delta_stability_checks: list[DeltaStability] = Field(
        default_factory=list,
        description="What happens when each clamp is removed",
    )

    # --- Interference Audit ---
    interferences: list[InterferenceResult] = Field(
        default_factory=list,
    )
    interference_clear: bool = Field(
        default=True, description="True if no critical interferences detected"
    )

    # --- Rendering ---
    camera_views: list[CameraView] = Field(
        default_factory=lambda: list(STANDARD_VIEWS),
    )
    rendered_image_paths: list[str] = Field(
        default_factory=list,
        description="Paths to rendered 6-view images",
    )

    # --- Gemini Queries ---
    gemini_queries: list[GeminiInferenceQuery] = Field(
        default_factory=list,
    )
    gemini_responses: list[dict] = Field(
        default_factory=list,
    )

    # --- Final Hardware ---
    permanent_hardware: list[str] = Field(
        default_factory=list,
        description="Final implant IDs (plates, screws) after reduction",
    )
    temporary_hardware: list[str] = Field(
        default_factory=list,
        description="Temporary K-wires, clamps to be removed",
    )
