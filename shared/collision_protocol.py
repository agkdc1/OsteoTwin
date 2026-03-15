"""Protocol for K-wire / implant trajectory collision checking.

Lightweight rigid-body collision detection for Phase 1.
Uses ray casting and mesh-mesh intersection via trimesh.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request: K-wire / ray trajectory collision check
# ---------------------------------------------------------------------------


class Vec3(BaseModel):
    """A 3D vector (position or direction)."""

    x: float
    y: float
    z: float


class CollisionCheckRequest(BaseModel):
    """Request to check a K-wire (ray) trajectory against loaded meshes.

    The ray is defined by an origin point and a direction vector.
    The server casts this ray against all loaded meshes in the scene
    and returns every intersection.
    """

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    case_id: str = Field(..., description="Parent FractureCase ID")
    branch: str = Field(default="main")

    # Ray definition
    ray_origin: Vec3 = Field(..., description="Starting point of the K-wire (mm)")
    ray_direction: Vec3 = Field(
        ..., description="Direction vector of the K-wire (will be normalized)"
    )

    # Optional: limit ray length (default: infinite)
    max_length_mm: Optional[float] = Field(
        None, description="Maximum ray length in mm (None = infinite)"
    )

    # Label for the trajectory
    label: str = Field(
        default="k_wire", description='e.g. "k_wire_1.6mm", "screw_3.5mm"'
    )


class IntersectionHit(BaseModel):
    """A single intersection between the ray and a mesh."""

    mesh_id: str = Field(..., description="Identifier of the intersected mesh")
    mesh_label: str = Field(
        ..., description='Human-readable label, e.g. "distal_fragment", "lcp_plate"'
    )
    hit_point: Vec3 = Field(..., description="World-space intersection point (mm)")
    distance_mm: float = Field(
        ..., description="Distance from ray origin to hit point"
    )
    face_index: int = Field(
        ..., description="Index of the triangle face that was hit"
    )
    is_entry: bool = Field(
        True, description="True if entering the mesh, False if exiting"
    )


class CollisionCheckResponse(BaseModel):
    """Result of a K-wire trajectory collision check."""

    request_id: str
    success: bool = True
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # All intersections along the ray, sorted by distance
    hits: list[IntersectionHit] = Field(default_factory=list)
    total_hits: int = 0

    # Derived metrics
    passes_through_cortex: bool = Field(
        default=False,
        description="True if the ray enters AND exits a bone (bicortical penetration)",
    )
    breaches_far_cortex: bool = Field(
        default=False,
        description="True if the ray exits the opposite cortex (over-penetration warning)",
    )
    intersects_hardware: bool = Field(
        default=False,
        description="True if the ray intersects any placed hardware (plate, screw)",
    )

    # Summary
    engine_summary: str = Field(default="")
    branch: str = Field(default="main")
