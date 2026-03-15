"""API routes for the orthopedic implant library."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import verify_api_key
from .. import config
from .implant_library import (
    IMPLANT_CATALOG,
    ImplantType,
    generate_implant_mesh,
    suggest_implants,
)

router = APIRouter(prefix="/api/v1/implants", tags=["implants"])


class ImplantInfo(BaseModel):
    implant_id: str
    name: str
    implant_type: str
    diameter_mm: float
    length_mm: float
    hole_count: Optional[int] = None


@router.get("/catalog")
async def list_implants(
    implant_type: Optional[str] = Query(None, description="Filter by type"),
    _: str = Depends(verify_api_key),
):
    """List all implants in the catalog."""
    items = []
    for impl_id, spec in IMPLANT_CATALOG.items():
        if implant_type and spec.implant_type.value != implant_type:
            continue
        items.append(ImplantInfo(
            implant_id=impl_id,
            name=spec.name,
            implant_type=spec.implant_type.value,
            diameter_mm=spec.diameter_mm,
            length_mm=spec.length_mm,
            hole_count=spec.hole_count,
        ))
    return {"implants": items, "count": len(items)}


@router.post("/generate")
async def generate_implant(
    implant_id: str,
    branch: str = "main",
    label: Optional[str] = None,
    _: str = Depends(verify_api_key),
):
    """Generate an implant mesh and load it into the collision engine."""
    try:
        mesh, spec = generate_implant_mesh(implant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Save STL
    output_dir = config.MESH_CACHE_DIR / "implants"
    output_dir.mkdir(parents=True, exist_ok=True)
    stl_path = output_dir / f"{implant_id}.stl"
    mesh.export(str(stl_path))

    # Load into collision engine for the branch
    from ..main import _get_collision_engine
    engine = _get_collision_engine(branch)
    mesh_label = label or spec.name
    engine.load_mesh_from_trimesh(
        mesh_id=implant_id,
        mesh=mesh,
        label=mesh_label,
        mesh_type="hardware",
    )

    return {
        "generated": True,
        "implant_id": implant_id,
        "name": spec.name,
        "type": spec.implant_type.value,
        "stl_path": str(stl_path),
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.faces),
        "loaded_in_branch": branch,
    }


@router.get("/suggest")
async def suggest(
    bone_region: str = Query(..., description="e.g. distal_radius"),
    fragment_count: int = Query(2, ge=1),
    max_bone_width_mm: float = Query(20.0, gt=0),
    _: str = Depends(verify_api_key),
):
    """Suggest appropriate implants based on bone geometry."""
    suggestions = suggest_implants(bone_region, fragment_count, max_bone_width_mm)
    details = []
    for impl_id in suggestions:
        spec = IMPLANT_CATALOG[impl_id]
        details.append(ImplantInfo(
            implant_id=impl_id,
            name=spec.name,
            implant_type=spec.implant_type.value,
            diameter_mm=spec.diameter_mm,
            length_mm=spec.length_mm,
            hole_count=spec.hole_count,
        ))
    return {
        "bone_region": bone_region,
        "fragment_count": fragment_count,
        "max_bone_width_mm": max_bone_width_mm,
        "suggestions": details,
    }
