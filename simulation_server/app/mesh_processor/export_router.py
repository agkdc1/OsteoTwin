"""API routes for 3D print STL export."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..auth import verify_api_key
from .. import config

router = APIRouter(prefix="/api/v1/export", tags=["3d-print"])


class ExportRequest(BaseModel):
    case_id: str = Field(..., description="FractureCase ID")
    fragment_stl_paths: list[str] = Field(
        ..., description="Paths to fragment STL files"
    )
    fragment_labels: list[str] = Field(
        ..., description="Labels for each fragment"
    )
    hardware_ids: list[str] = Field(
        default_factory=list,
        description="Implant IDs from the catalog to include",
    )
    scale_factor: float = Field(
        default=1.0, ge=0.1, le=5.0,
        description="Scale factor (1.0 = original size)",
    )
    merged: bool = Field(default=True, description="Export a single merged STL")
    per_component: bool = Field(default=True, description="Export separate STLs per component")


@router.post("/stl", dependencies=[Depends(verify_api_key)])
async def export_stl(req: ExportRequest):
    """Export a fracture case as 3D-printable STL files.

    Generates color-coded bone fragments, placed hardware, alignment markers,
    and a scale bar. Returns file paths and print estimates.
    """
    import trimesh
    from .stl_export import export_case_stl
    from .implant_library import generate_implant_mesh

    # Load fragment meshes
    fragments = []
    for stl_path in req.fragment_stl_paths:
        p = Path(stl_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"Fragment not found: {stl_path}")
        mesh = trimesh.load(str(p), force="mesh")
        fragments.append(mesh)

    if len(req.fragment_labels) != len(fragments):
        raise HTTPException(
            status_code=422,
            detail="fragment_labels length must match fragment_stl_paths length",
        )

    # Generate hardware meshes
    hardware = []
    for hw_id in req.hardware_ids:
        try:
            mesh, spec = generate_implant_mesh(hw_id)
            hardware.append((mesh, spec.name))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    output_dir = config.MESH_CACHE_DIR / req.case_id / "3d_print"

    result = export_case_stl(
        fragments=fragments,
        fragment_labels=req.fragment_labels,
        hardware=hardware if hardware else None,
        output_dir=output_dir,
        case_id=req.case_id,
        merged=req.merged,
        per_component=req.per_component,
        scale_factor=req.scale_factor,
    )

    return result


@router.get("/stl/{case_id}/{filename}", dependencies=[Depends(verify_api_key)])
async def download_stl(case_id: str, filename: str):
    """Download a specific exported STL file."""
    filepath = config.MESH_CACHE_DIR / case_id / "3d_print" / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return FileResponse(
        path=str(filepath),
        media_type="application/sla",
        filename=filename,
    )


@router.get("/stl/{case_id}", dependencies=[Depends(verify_api_key)])
async def list_exports(case_id: str):
    """List all exported STL files for a case."""
    export_dir = config.MESH_CACHE_DIR / case_id / "3d_print"
    if not export_dir.exists():
        return {"case_id": case_id, "files": []}

    files = []
    for f in sorted(export_dir.glob("*.stl")):
        files.append({
            "filename": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "download_url": f"/api/v1/export/stl/{case_id}/{f.name}",
        })
    return {"case_id": case_id, "files": files}
