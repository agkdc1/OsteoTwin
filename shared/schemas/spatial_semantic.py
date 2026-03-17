"""Common Spatial-Semantic Schema for OsteoTwin.

Single source of truth for spatial and anatomical data shared across:
- Lead Surgeon AI (Claude)
- Vision Critic / Librarian (Gemini)
- Simulation Server (deterministic physics)
- React Dashboard (3D viewer)

All vectors use the **LPS (Left-Posterior-Superior)** coordinate system
matching DICOM convention:
    X+  = Left        X-  = Right
    Y+  = Posterior    Y-  = Anterior
    Z+  = Superior     Z-  = Inferior
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LPS Coordinate System
# ---------------------------------------------------------------------------

class CoordinateSystem(str, Enum):
    """Supported coordinate systems.  LPS is the project standard."""

    LPS = "LPS"       # Left-Posterior-Superior (DICOM native)
    RAS = "RAS"       # Right-Anterior-Superior (some neuro tools)
    THREEJS = "XYZ"   # Three.js scene coords (frontend only)


class LPSVector(BaseModel):
    """A 3-component vector in the LPS coordinate frame (mm or unitless)."""

    x: float = Field(0.0, description="Left(+) / Right(-)")
    y: float = Field(0.0, description="Posterior(+) / Anterior(-)")
    z: float = Field(0.0, description="Superior(+) / Inferior(-)")


class LPSRotation(BaseModel):
    """Euler angles in degrees around the LPS axes.

    Convention: extrinsic rotations applied in X → Y → Z order.
    """

    x_deg: float = Field(0.0, description="Rotation around L-R axis (flexion/extension)")
    y_deg: float = Field(0.0, description="Rotation around A-P axis (varus/valgus)")
    z_deg: float = Field(0.0, description="Rotation around S-I axis (internal/external rotation)")


# ---------------------------------------------------------------------------
# Fragment Identity
# ---------------------------------------------------------------------------

class FragmentIdentity(BaseModel):
    """Uniquely identifies and describes a bone fragment in the scene.

    The naming convention encodes anatomy:
        {bone}_{side}_{fragment_number}_{qualifier}
    e.g.  "tibia_R_frag1_proximal", "humerus_L_frag3_articular"
    """

    fragment_id: str = Field(
        ...,
        description='Unique ID, e.g. "tibia_R_frag1_proximal"',
        examples=["tibia_R_frag1_proximal", "humerus_L_frag2_shaft"],
    )
    color_code: str = Field(
        ...,
        description="Display color for frontend rendering and cross-agent reference",
        examples=["Blue", "Green", "Red", "Yellow", "Orange"],
    )
    volume_mm3: float = Field(
        ..., ge=0, description="Fragment volume in cubic millimeters"
    )
    bone: Optional[str] = Field(
        None, description='Bone name, e.g. "tibia", "humerus"'
    )
    side: Optional[str] = Field(
        None, description='"L" or "R"'
    )
    qualifier: Optional[str] = Field(
        None,
        description='Anatomical qualifier, e.g. "proximal", "shaft", "articular"',
    )


# ---------------------------------------------------------------------------
# Semantic Translation Layer — surgical terms ↔ LPS math
# ---------------------------------------------------------------------------

class AnatomicalDirection(str, Enum):
    """Surgical movement directions mapped to LPS axes."""

    # Translations
    PROXIMAL = "proximal"          # +Z
    DISTAL = "distal"              # -Z
    MEDIAL = "medial"              # +X (for right-side bones; flipped for left)
    LATERAL = "lateral"            # -X (for right-side bones; flipped for left)
    ANTERIOR = "anterior"          # -Y
    POSTERIOR = "posterior"         # +Y

    # Rotations (around specific LPS axes)
    VARUS = "varus"                # rotation around A-P axis (Y)
    VALGUS = "valgus"              # rotation around A-P axis (Y), opposite sign
    FLEXION = "flexion"            # rotation around L-R axis (X)
    EXTENSION = "extension"        # rotation around L-R axis (X), opposite sign
    INTERNAL_ROTATION = "internal_rotation"   # rotation around S-I axis (Z)
    EXTERNAL_ROTATION = "external_rotation"   # rotation around S-I axis (Z), opposite sign

    # Compound
    COMPRESSION = "compression"    # reduce gap between fragments along fracture line
    DISTRACTION = "distraction"    # increase gap


# Mapping: direction → (axis, sign_multiplier, is_rotation)
# Sign conventions assume RIGHT-side lower limb; kinematics.py flips for left side.
DIRECTION_LPS_MAP: dict[AnatomicalDirection, tuple[str, float, bool]] = {
    # Translations
    AnatomicalDirection.PROXIMAL:    ("z", +1.0, False),
    AnatomicalDirection.DISTAL:      ("z", -1.0, False),
    AnatomicalDirection.MEDIAL:      ("x", +1.0, False),
    AnatomicalDirection.LATERAL:     ("x", -1.0, False),
    AnatomicalDirection.ANTERIOR:    ("y", -1.0, False),
    AnatomicalDirection.POSTERIOR:   ("y", +1.0, False),
    # Rotations
    AnatomicalDirection.VARUS:              ("y", +1.0, True),
    AnatomicalDirection.VALGUS:             ("y", -1.0, True),
    AnatomicalDirection.FLEXION:            ("x", +1.0, True),
    AnatomicalDirection.EXTENSION:          ("x", -1.0, True),
    AnatomicalDirection.INTERNAL_ROTATION:  ("z", +1.0, True),
    AnatomicalDirection.EXTERNAL_ROTATION:  ("z", -1.0, True),
}


class SemanticMovement(BaseModel):
    """A single anatomical movement expressed in clinical terms.

    Resolved to an LPS vector/rotation by kinematics.resolve_movement().
    """

    direction: AnatomicalDirection = Field(
        ..., description="Clinical movement direction"
    )
    magnitude: float = Field(
        ..., gt=0, description="Magnitude in mm (translation) or degrees (rotation)"
    )
    side: str = Field(
        "R",
        description='"L" or "R" — needed to resolve medial/lateral sign flip',
    )


# ---------------------------------------------------------------------------
# Surgical Action — the universal inter-agent message
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    """Types of surgical actions the pipeline can execute."""

    TRANSLATE = "translate"
    ROTATE = "rotate"
    TRANSLATE_AND_ROTATE = "translate_and_rotate"
    INSERT_K_WIRE = "insert_k_wire"
    PLACE_PLATE = "place_plate"
    PLACE_SCREW = "place_screw"
    REMOVE_HARDWARE = "remove_hardware"


class SurgicalAction(BaseModel):
    """The canonical message exchanged between all agents for any surgical move.

    Flow:
        Surgeon (voice/text) → Claude parses → SurgicalAction
        Claude → Gemini (validation) passes SurgicalAction + rendered image
        Gemini → Claude (feedback) returns corrections as SurgicalAction
        Claude → SimulationServer dispatches via SimActionRequest
    """

    action_type: ActionType = Field(
        ..., description="Category of surgical action"
    )
    target: FragmentIdentity = Field(
        ..., description="The fragment being acted upon"
    )
    clinical_intent: str = Field(
        ...,
        description="Surgeon's original natural-language instruction",
        examples=["Move the green fragment 2mm distally and add 3 degrees of valgus"],
    )

    # Semantic movements (clinical terms — what the surgeon said)
    movements: list[SemanticMovement] = Field(
        default_factory=list,
        description="Parsed clinical movements before LPS resolution",
    )

    # Resolved LPS math (computed by kinematics.resolve_movements)
    translation_mm: LPSVector = Field(
        default_factory=LPSVector,
        description="Net translation in mm (LPS frame)",
    )
    rotation_deg: LPSRotation = Field(
        default_factory=LPSRotation,
        description="Net rotation in degrees (LPS Euler angles)",
    )

    # Hardware (for INSERT_K_WIRE, PLACE_PLATE, PLACE_SCREW)
    hardware_id: Optional[str] = Field(
        None, description='e.g. "k_wire_1.6mm", "lcp_plate_6hole"'
    )
    hardware_position: Optional[LPSVector] = None
    hardware_orientation: Optional[LPSRotation] = None

    # Traceability
    case_id: Optional[str] = Field(None, description="FractureCase ID")
    branch: str = Field(
        default="LLM_Hypothesis",
        description="Simulation branch (never 'main' unless surgeon-approved)",
    )
    source_agent: Optional[str] = Field(
        None,
        description='"claude", "gemini", or "surgeon"',
    )


# ---------------------------------------------------------------------------
# Gemini Validation Feedback
# ---------------------------------------------------------------------------

class CorrectionSuggestion(BaseModel):
    """A correction proposed by Gemini after visual validation.

    Uses the exact same fragment IDs and LPS vectors so Claude
    can apply it without ambiguity.
    """

    fragment_id: str = Field(
        ..., description="Must match a FragmentIdentity.fragment_id in the scene"
    )
    reason: str = Field(
        ..., description="Clinical rationale for the correction"
    )
    correction_translation_mm: Optional[LPSVector] = Field(
        None, description="Additional translation needed (LPS mm)"
    )
    correction_rotation_deg: Optional[LPSRotation] = Field(
        None, description="Additional rotation needed (LPS degrees)"
    )
    confidence: float = Field(
        ..., ge=0, le=1, description="Gemini's confidence in this correction"
    )


class ValidationFeedback(BaseModel):
    """Gemini's structured response after visual validation of a SurgicalAction."""

    original_action: SurgicalAction = Field(
        ..., description="The action that was validated"
    )
    is_acceptable: bool = Field(
        ..., description="True if Gemini considers the result acceptable"
    )
    corrections: list[CorrectionSuggestion] = Field(
        default_factory=list,
        description="Suggested corrections (empty if acceptable)",
    )
    visual_assessment: str = Field(
        ..., description="Free-text assessment of the rendered result"
    )


# ---------------------------------------------------------------------------
# 3D Printer Configuration & Filament Mapping
# ---------------------------------------------------------------------------

class MaterialType(str, Enum):
    """Common 3D printing materials for medical models."""

    PLA = "PLA"
    PETG = "PETG"
    ABS = "ABS"
    PC = "PC"                        # Polycarbonate — bone-simulating
    TPU = "TPU"                      # Flexible — soft tissue simulation
    NYLON = "Nylon"
    ASA = "ASA"
    PVA = "PVA"                      # Water-soluble support
    HIPS = "HIPS"                    # Soluble support
    RESIN_STANDARD = "Resin_Standard"
    RESIN_TOUGH = "Resin_Tough"


class FilamentMapping(BaseModel):
    """Maps a semantic color to a physical printer extruder and material.

    Example: the "Green" fragment in the 3D viewer → Extruder 2 → PETG
    """

    color_code: str = Field(
        ...,
        description="Semantic color matching FragmentIdentity.color_code",
        examples=["Blue", "Green", "Red", "White", "Yellow"],
    )
    extruder_id: int = Field(
        ..., ge=0, description="0-indexed extruder/toolhead number"
    )
    material_type: MaterialType = Field(
        ..., description="Filament material for this extruder"
    )
    material_label: Optional[str] = Field(
        None,
        description='User-friendly material name, e.g. "Bone-Simulating PC"',
    )
    color_hex: Optional[str] = Field(
        None,
        description='Physical filament hex color, e.g. "#F5F0E1"',
        pattern=r"^#[0-9a-fA-F]{6}$",
    )
    notes: Optional[str] = Field(
        None, description="Usage notes, e.g. 'Use for main bone body'"
    )


class PrinterConfig(BaseModel):
    """Defines the target 3D printer hardware for export.

    Stored per-user or per-project; the export engine reads this to
    inject correct extruder metadata into 3MF / named STL output.
    """

    printer_id: str = Field(
        ...,
        description="Unique ID for this printer profile",
        examples=["prusa-xl-5t", "bambu-x1c-ams"],
    )
    printer_name: str = Field(
        ...,
        description="Human-readable printer name",
        examples=["Prusa XL 5-Toolhead", "Bambu Lab X1C + AMS"],
    )
    num_extruders: int = Field(
        ..., ge=1, le=16, description="Number of toolheads / extruders"
    )
    build_volume_mm: LPSVector = Field(
        default_factory=lambda: LPSVector(x=360, y=360, z=360),
        description="Build volume in mm (x=width, y=depth, z=height)",
    )
    filament_mappings: list[FilamentMapping] = Field(
        default_factory=list,
        description="Color-to-extruder mapping for multi-material prints",
    )
    is_default: bool = Field(
        default=False, description="If True, used when no printer is explicitly selected"
    )
    notes: Optional[str] = Field(
        None, description="Printer-specific notes (e.g. calibration tips)"
    )
