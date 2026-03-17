"""Implant schemas for the Autonomous Catalog-to-CAD Pipeline (Phase 9).

Defines:
- ManufacturerAlias: 3-letter anonymized manufacturer codes
- ParametricImplantSpec: full parametric dimensions from catalog extraction
- ImplantQAState: tracks the 6-strike autonomous QA loop
- ImplantCADResult: final output of the pipeline
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Manufacturer Alias System
# ---------------------------------------------------------------------------

class ManufacturerAlias(str, Enum):
    """3-letter anonymized manufacturer aliases.

    Raw database and 3D file names use these aliases.
    Frontend can map back to full names for authenticated users only.
    """

    SYN = "SYN"  # DePuy Synthes
    STK = "STK"  # Stryker
    ZIM = "ZIM"  # Zimmer Biomet
    ACM = "ACM"  # Acumed
    ARX = "ARX"  # Arthrex
    SMN = "SMN"  # Smith & Nephew
    MED = "MED"  # Medartis
    ACP = "ACP"  # Acuplus
    GEN = "GEN"  # Generic / Unknown


# Frontend-only display mapping (NOT stored in DB/files)
ALIAS_DISPLAY_MAP: dict[ManufacturerAlias, str] = {
    ManufacturerAlias.SYN: "Synthes",
    ManufacturerAlias.STK: "Stryker",
    ManufacturerAlias.ZIM: "Zimmer Biomet",
    ManufacturerAlias.ACM: "Acumed",
    ManufacturerAlias.ARX: "Arthrex",
    ManufacturerAlias.SMN: "Smith & Nephew",
    ManufacturerAlias.MED: "Medartis",
    ManufacturerAlias.ACP: "Acuplus",
    ManufacturerAlias.GEN: "Generic",
}


# ---------------------------------------------------------------------------
# Parametric Implant Specification (Gemini extraction target)
# ---------------------------------------------------------------------------

class HoleType(str, Enum):
    """Types of screw holes on plates."""

    LOCKING = "locking"
    COMPRESSION = "compression"
    COMBINATION = "combination"  # accepts both locking and cortical
    OBLONG = "oblong"           # elongated for compression
    K_WIRE = "k_wire"           # small hole for temporary K-wire


class HoleSpec(BaseModel):
    """Specification for a single hole in a plate."""

    index: int = Field(..., ge=0, description="0-indexed hole number from proximal end")
    hole_type: HoleType = Field(..., description="Hole type")
    diameter_mm: float = Field(..., gt=0, description="Hole diameter in mm")
    offset_x_mm: float = Field(0.0, description="Lateral offset from plate centerline (mm)")
    offset_y_mm: float = Field(0.0, description="Longitudinal offset from previous hole (mm)")
    angle_deg: Optional[float] = Field(
        None, description="Fixed-angle direction for locking holes (degrees from perpendicular)"
    )


class PlateContour(str, Enum):
    """Plate contour/profile types."""

    STRAIGHT = "straight"
    CURVED = "curved"
    ANATOMIC = "anatomic"   # pre-contoured to bone surface
    T_SHAPED = "t_shaped"
    L_SHAPED = "l_shaped"
    Y_SHAPED = "y_shaped"


class ParametricImplantSpec(BaseModel):
    """Full parametric specification of an orthopedic implant.

    Extracted by Gemini from manufacturer catalogs.
    Used by Claude to generate OpenSCAD code.
    """

    # Identity
    manufacturer_alias: ManufacturerAlias = Field(
        ..., description="3-letter manufacturer alias (e.g., SYN, STK)"
    )
    implant_name: str = Field(
        ...,
        description="Clinical implant name without manufacturer (e.g., 'LCP Volar Distal Radius Plate')",
    )
    catalog_number: Optional[str] = Field(
        None, description="Manufacturer catalog/part number"
    )
    implant_type: str = Field(
        ..., description="Category: locking_plate, recon_plate, cortical_screw, etc."
    )

    # Global dimensions
    length_mm: float = Field(..., gt=0, description="Total length in mm")
    width_mm: float = Field(..., gt=0, description="Maximum width in mm")
    thickness_mm: float = Field(..., gt=0, description="Plate/body thickness in mm")

    # Plate-specific
    contour: Optional[PlateContour] = Field(None, description="Plate profile shape")
    hole_count: Optional[int] = Field(None, ge=0, description="Total number of screw holes")
    holes: list[HoleSpec] = Field(
        default_factory=list, description="Detailed per-hole specifications"
    )

    # Screw-specific
    thread_pitch_mm: Optional[float] = Field(None, gt=0)
    head_diameter_mm: Optional[float] = Field(None, gt=0)
    head_height_mm: Optional[float] = Field(None, gt=0)
    shaft_diameter_mm: Optional[float] = Field(None, gt=0)

    # Material
    material: str = Field(
        default="Titanium", description="Material (Titanium, Stainless Steel, etc.)"
    )

    # Anatomical context
    body_region: Optional[str] = Field(
        None, description="Target body region (e.g., 'distal_radius', 'proximal_humerus')"
    )
    side_specific: bool = Field(
        default=False, description="True if left/right-specific design"
    )

    @property
    def file_prefix(self) -> str:
        """Generate the standardized filename prefix.

        Example: SYN_LCP_Volar_Distal_Radius_5Hole
        """
        name_part = self.implant_name.replace(" ", "_").replace("-", "_")
        holes = f"_{self.hole_count}Hole" if self.hole_count else ""
        return f"{self.manufacturer_alias.value}_{name_part}{holes}"


# ---------------------------------------------------------------------------
# QA Loop State (6-Strike Rule)
# ---------------------------------------------------------------------------

class QAStatus(str, Enum):
    """Status of a single QA iteration."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class QAIteration(BaseModel):
    """Record of a single QA validation pass."""

    iteration: int = Field(..., ge=1, description="1-indexed iteration number")
    status: QAStatus
    feedback: Optional[str] = Field(
        None, description="Gemini's rejection rationale (None if approved)"
    )
    constraint_checklist: list[str] = Field(
        default_factory=list,
        description="Specific items Gemini flagged for correction",
    )
    scad_code_hash: Optional[str] = Field(
        None, description="SHA-256 of the SCAD code at this iteration"
    )
    render_path: Optional[str] = Field(
        None, description="Path to the 6-way stitched render image"
    )


class ImplantQAState(BaseModel):
    """Tracks the autonomous QA loop for a single implant.

    The 6-strike rule: if rejected 6 consecutive times, halt and
    escalate to human review.
    """

    MAX_REJECTIONS: int = 6

    implant_spec: ParametricImplantSpec
    iterations: list[QAIteration] = Field(default_factory=list)

    @property
    def rejection_count(self) -> int:
        return sum(1 for it in self.iterations if it.status == QAStatus.REJECTED)

    @property
    def is_approved(self) -> bool:
        return bool(self.iterations) and self.iterations[-1].status == QAStatus.APPROVED

    @property
    def is_halted(self) -> bool:
        return self.rejection_count >= self.MAX_REJECTIONS

    @property
    def current_iteration(self) -> int:
        return len(self.iterations)


# ---------------------------------------------------------------------------
# Final CAD Result
# ---------------------------------------------------------------------------

class ImplantCADResult(BaseModel):
    """Output of the autonomous Catalog-to-CAD pipeline."""

    spec: ParametricImplantSpec
    scad_code: str = Field(..., description="Final OpenSCAD source code")
    stl_path: Optional[str] = Field(None, description="Path to exported STL")
    threemf_path: Optional[str] = Field(None, description="Path to exported 3MF")
    render_6way_path: Optional[str] = Field(
        None, description="Path to final 6-way orthographic render"
    )
    qa_iterations: int = Field(..., ge=1, description="Total QA iterations needed")
    approved: bool = Field(..., description="True if Gemini approved, False if halted")
    failure_report: Optional[str] = Field(
        None, description="Human-readable failure report (only if halted)"
    )
