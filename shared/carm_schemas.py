"""C-arm, OR Bed, and Patient positioning schemas.

Precise physical models for simulating real C-arm fluoroscopy.
All dimensions based on common clinical equipment specs.

The C-arm is modeled as a circular arc (C-shape) that rotates around
two axes: orbital (around the patient's long axis) and angular
(tilt toward/away from the table). The X-ray source is at one end
of the arc, the image intensifier at the other.

Physical constraints:
- The C-arm arc has a finite throat depth (clearance from center to arc)
- The bed has a fixed height and width
- The patient body has a bounding volume
- Some projection angles are physically impossible because the arc
  collides with the bed rails, mattress, or patient body

Coordinate system: LPS (Left-Posterior-Superior) consistent with DICOM.
- Patient lies supine: head toward +Z, feet toward -Z
- Bed surface is at approximately Y = -200mm (posterior)
- C-arm rotates around the patient's long axis (Z)
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# C-arm Model
# ---------------------------------------------------------------------------

class CarmModel(str, Enum):
    """Common C-arm models with known dimensions."""
    SIEMENS_CIOS_ALPHA = "siemens_cios_alpha"
    GE_OEC_ONE = "ge_oec_one"
    ZIEHM_VISION_RFD = "ziehm_vision_rfd"
    PHILIPS_ZENITION = "philips_zenition"
    GENERIC_MINI = "generic_mini"
    GENERIC_FULL = "generic_full"


class CarmSpec(BaseModel):
    """Physical dimensions of a C-arm unit.

    The C-arm is a semicircular arc. The X-ray tube is at one end,
    the image intensifier (II) / flat panel detector at the other.
    """

    model: CarmModel = Field(default=CarmModel.GENERIC_FULL)
    name: str = Field(default="Generic Full-Size C-arm")

    # Arc geometry
    arc_radius_mm: float = Field(
        default=800.0,
        description="Radius of the C-shaped arc (center to inner edge of arc)",
    )
    arc_thickness_mm: float = Field(
        default=80.0,
        description="Thickness of the arc arm itself",
    )
    throat_depth_mm: float = Field(
        default=660.0,
        description="Free space from isocenter to the nearest point of the C-arm body",
    )

    # Source and detector
    source_to_isocenter_mm: float = Field(
        default=620.0,
        description="Distance from X-ray source to isocenter",
    )
    detector_to_isocenter_mm: float = Field(
        default=380.0,
        description="Distance from detector to isocenter",
    )
    sid_mm: float = Field(
        default=1000.0,
        description="Source-to-Image Distance (SID) = source_to_iso + detector_to_iso",
    )
    detector_size_mm: tuple[float, float] = Field(
        default=(310.0, 310.0),
        description="Detector active area (width, height) in mm",
    )

    # Movement ranges
    orbital_range_deg: tuple[float, float] = Field(
        default=(-120.0, 120.0),
        description="Orbital rotation range (around patient long axis Z)",
    )
    angular_range_deg: tuple[float, float] = Field(
        default=(-40.0, 40.0),
        description="Angular tilt range (cranial/caudal)",
    )
    vertical_travel_mm: float = Field(
        default=430.0,
        description="Vertical travel of the C-arm column",
    )
    horizontal_travel_mm: float = Field(
        default=200.0,
        description="Horizontal travel along bed length",
    )


# Pre-defined C-arm specs
CARM_SPECS: dict[CarmModel, CarmSpec] = {
    CarmModel.SIEMENS_CIOS_ALPHA: CarmSpec(
        model=CarmModel.SIEMENS_CIOS_ALPHA,
        name="Siemens Cios Alpha",
        arc_radius_mm=780, throat_depth_mm=660,
        source_to_isocenter_mm=620, detector_to_isocenter_mm=380, sid_mm=1000,
        detector_size_mm=(310, 310),
        orbital_range_deg=(-135, 135), angular_range_deg=(-40, 40),
    ),
    CarmModel.GE_OEC_ONE: CarmSpec(
        model=CarmModel.GE_OEC_ONE,
        name="GE OEC One",
        arc_radius_mm=810, throat_depth_mm=680,
        source_to_isocenter_mm=640, detector_to_isocenter_mm=390, sid_mm=1030,
        detector_size_mm=(310, 310),
        orbital_range_deg=(-130, 130), angular_range_deg=(-40, 40),
    ),
    CarmModel.ZIEHM_VISION_RFD: CarmSpec(
        model=CarmModel.ZIEHM_VISION_RFD,
        name="Ziehm Vision RFD",
        arc_radius_mm=790, throat_depth_mm=670,
        source_to_isocenter_mm=630, detector_to_isocenter_mm=370, sid_mm=1000,
        detector_size_mm=(300, 300),
        orbital_range_deg=(-125, 125), angular_range_deg=(-35, 35),
    ),
    CarmModel.GENERIC_MINI: CarmSpec(
        model=CarmModel.GENERIC_MINI,
        name="Generic Mini C-arm",
        arc_radius_mm=500, throat_depth_mm=400,
        source_to_isocenter_mm=400, detector_to_isocenter_mm=250, sid_mm=650,
        detector_size_mm=(230, 230),
        orbital_range_deg=(-90, 90), angular_range_deg=(-20, 20),
    ),
    CarmModel.GENERIC_FULL: CarmSpec(
        model=CarmModel.GENERIC_FULL,
        name="Generic Full-Size C-arm",
        arc_radius_mm=800, throat_depth_mm=660,
        source_to_isocenter_mm=620, detector_to_isocenter_mm=380, sid_mm=1000,
        detector_size_mm=(310, 310),
        orbital_range_deg=(-120, 120), angular_range_deg=(-40, 40),
    ),
}


# ---------------------------------------------------------------------------
# OR Bed Model
# ---------------------------------------------------------------------------

class BedType(str, Enum):
    STANDARD_OR = "standard_or"
    CARBON_FIBER = "carbon_fiber"      # radiolucent
    FRACTURE_TABLE = "fracture_table"  # with traction
    BEACH_CHAIR = "beach_chair"        # shoulder surgery


class ORBedSpec(BaseModel):
    """Physical dimensions of the operating room bed/table."""

    bed_type: BedType = Field(default=BedType.CARBON_FIBER)
    name: str = Field(default="Standard Carbon Fiber OR Table")

    # Bed surface dimensions
    length_mm: float = Field(default=2100.0, description="Bed length (head to foot)")
    width_mm: float = Field(default=520.0, description="Bed width")
    mattress_thickness_mm: float = Field(default=80.0, description="Mattress + pad thickness")

    # Bed height (floor to top of mattress)
    height_min_mm: float = Field(default=650.0, description="Minimum bed height")
    height_max_mm: float = Field(default=1050.0, description="Maximum bed height")
    height_mm: float = Field(default=850.0, description="Current bed height")

    # Rails and accessories
    rail_height_mm: float = Field(default=120.0, description="Side rail height above mattress")
    rail_width_mm: float = Field(default=30.0, description="Side rail thickness")
    has_arm_boards: bool = Field(default=True)
    arm_board_width_mm: float = Field(default=200.0)

    # Bed surface position in LPS (center of bed)
    # Y = posterior surface of mattress (patient lies ON this)
    bed_center_lps: tuple[float, float, float] = Field(
        default=(0.0, 0.0, 0.0),
        description="Center of bed surface in LPS coordinates",
    )

    @property
    def half_width(self) -> float:
        return self.width_mm / 2

    @property
    def half_length(self) -> float:
        return self.length_mm / 2


# ---------------------------------------------------------------------------
# Patient Positioning
# ---------------------------------------------------------------------------

class PatientPosition(str, Enum):
    SUPINE = "supine"          # face up (most common)
    PRONE = "prone"            # face down
    LATERAL_LEFT = "lateral_left"    # left side down
    LATERAL_RIGHT = "lateral_right"  # right side down
    BEACH_CHAIR = "beach_chair"      # semi-reclined (shoulder)


class PatientModel(BaseModel):
    """Simplified patient bounding volume for collision detection."""

    position: PatientPosition = Field(default=PatientPosition.SUPINE)

    # Body dimensions (approximate bounding ellipsoid)
    body_width_mm: float = Field(default=400.0, description="Shoulder width")
    body_depth_mm: float = Field(default=220.0, description="AP thickness (chest)")
    body_length_mm: float = Field(default=1750.0, description="Head to toe")

    # Position on bed (LPS, relative to bed center)
    offset_x_mm: float = Field(default=0.0, description="Lateral offset on bed")
    offset_y_mm: float = Field(default=0.0, description="AP offset")
    offset_z_mm: float = Field(default=0.0, description="Cranial-caudal offset on bed")

    # Target anatomy position (where the C-arm isocenter should be)
    target_lps: tuple[float, float, float] = Field(
        default=(0.0, 0.0, 0.0),
        description="Target anatomy position in LPS (C-arm isocenter)",
    )


# ---------------------------------------------------------------------------
# C-arm Pose (current position and angles)
# ---------------------------------------------------------------------------

class CarmPose(BaseModel):
    """Current C-arm position and orientation.

    The C-arm has two rotation axes:
    - orbital_deg: rotation around patient's Z-axis (0=AP, 90=lateral)
    - angular_deg: cranial/caudal tilt (0=perpendicular to bed)

    And translation:
    - isocenter: the 3D point the C-arm is centered on
    """

    orbital_deg: float = Field(
        default=0.0,
        description="Orbital rotation: 0=AP, +90=left lateral, -90=right lateral",
    )
    angular_deg: float = Field(
        default=0.0,
        description="Angular tilt: +=cranial, -=caudal",
    )
    isocenter_lps: tuple[float, float, float] = Field(
        default=(0.0, 0.0, 0.0),
        description="Isocenter position in LPS",
    )

    @property
    def source_direction(self) -> tuple[float, float, float]:
        """Unit vector from source toward detector (beam direction)."""
        orb = math.radians(self.orbital_deg)
        ang = math.radians(self.angular_deg)
        # At orbital=0, beam goes Y+ to Y- (posterior to anterior = AP view)
        dx = -math.sin(orb) * math.cos(ang)
        dy = -math.cos(orb) * math.cos(ang)
        dz = -math.sin(ang)
        return (dx, dy, dz)


# ---------------------------------------------------------------------------
# Feasibility Result
# ---------------------------------------------------------------------------

class CollisionType(str, Enum):
    NONE = "none"
    ARC_BED = "arc_bed"
    ARC_PATIENT = "arc_patient"
    ARC_RAIL = "arc_rail"
    SOURCE_BED = "source_bed"
    DETECTOR_BED = "detector_bed"
    OUT_OF_RANGE = "out_of_range"


class FeasibilityResult(BaseModel):
    """Result of C-arm feasibility check for a given pose."""

    feasible: bool = Field(..., description="True if this pose is physically achievable")
    orbital_deg: float
    angular_deg: float
    collisions: list[CollisionType] = Field(default_factory=list)
    min_clearance_mm: Optional[float] = Field(
        None, description="Minimum clearance between C-arm and obstacles",
    )
    notes: list[str] = Field(default_factory=list)
    beam_direction: tuple[float, float, float] = Field(
        default=(0, -1, 0), description="X-ray beam direction vector (LPS)",
    )


class CarmFeasibilityMap(BaseModel):
    """Full feasibility map: which angles are achievable for this setup."""

    carm_model: str
    bed_type: str
    patient_position: str
    orbital_range_tested: tuple[float, float]
    angular_range_tested: tuple[float, float]
    step_deg: float
    total_poses_tested: int
    feasible_poses: int
    blocked_poses: int
    feasibility_pct: float
    results: list[FeasibilityResult] = Field(default_factory=list)
