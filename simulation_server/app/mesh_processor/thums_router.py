"""THUMS v7.1 mesh serving endpoints.

Serves parsed THUMS VTK meshes to the frontend. Converts VTK to STL
on-the-fly for Three.js compatibility. Provides listing and metadata.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field

from ..auth import verify_api_key

logger = logging.getLogger("osteotwin.thums_router")

router = APIRouter(
    prefix="/api/v1/thums",
    tags=["thums"],
    dependencies=[Depends(verify_api_key)],
)

THUMS_OUTPUT = Path(__file__).resolve().parent.parent.parent.parent / "fea" / "thums_output"

SUBJECTS = ["AF05", "AF50", "AM50", "AM95"]

REGION_FILTER = {
    "upper_extremity": ["upper_extremity_right", "upper_extremity_left"],
    "lower_extremity": ["lower_extremity_right", "lower_extremity_left"],
    "head": ["head"],
    "thorax": ["thorax"],
    "abdomen": ["abdomen_pelvis"],
    "neck": ["neck"],
    "muscle": ["muscle"],
    "organs": ["internal_organs"],
}


# ---------------------------------------------------------------------------
# List / metadata endpoints
# ---------------------------------------------------------------------------


@router.get("/subjects")
async def list_subjects():
    """List available THUMS subjects and their parse status."""
    result = []
    for s in SUBJECTS:
        d = THUMS_OUTPUT / s
        has_anat = (d / "thums_anatomical_map.json").exists()
        vtk_count = len(list((d / "vtk").glob("*.vtk"))) if (d / "vtk").exists() else 0
        result.append({
            "subject": s,
            "parsed": has_anat,
            "vtk_meshes": vtk_count,
        })
    return {"subjects": result}


@router.get("/{subject}/parts")
async def list_parts(
    subject: str,
    region: Optional[str] = Query(None, description="Filter: upper_extremity, lower_extremity, head, thorax, etc."),
    mat_type: Optional[str] = Query(None, description="Filter by material type, e.g. *MAT_ELASTIC"),
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """List THUMS parts with optional region/material filter."""
    anat_path = THUMS_OUTPUT / subject / "thums_anatomical_map.json"
    if not anat_path.exists():
        raise HTTPException(404, f"Subject '{subject}' not parsed. Run thums_parser.py {subject}")

    with open(anat_path) as f:
        parts = json.load(f)

    # Apply filters
    if region:
        regions = REGION_FILTER.get(region, [region])
        parts = [p for p in parts if p["region"] in regions]
    if mat_type:
        parts = [p for p in parts if p["mat_type"] == mat_type]

    total = len(parts)
    parts = parts[offset:offset + limit]

    # Check which have VTK meshes
    vtk_dir = THUMS_OUTPUT / subject / "vtk"
    for p in parts:
        p["has_vtk"] = (vtk_dir / f"part_{p['part_id']}.vtk").exists()

    return {"subject": subject, "total": total, "offset": offset, "limit": limit, "parts": parts}


@router.get("/{subject}/parts/{part_id}")
async def get_part_detail(subject: str, part_id: int):
    """Get detailed info for a specific part, including SOFA config."""
    anat_path = THUMS_OUTPUT / subject / "thums_anatomical_map.json"
    if not anat_path.exists():
        raise HTTPException(404, f"Subject '{subject}' not parsed")

    with open(anat_path) as f:
        parts = json.load(f)

    part = next((p for p in parts if p["part_id"] == part_id), None)
    if not part:
        raise HTTPException(404, f"Part {part_id} not found in {subject}")

    # Add SOFA config if available
    sofa_path = THUMS_OUTPUT / subject / "material_configs.json"
    sofa_config = None
    if sofa_path.exists():
        with open(sofa_path) as f:
            configs = json.load(f)
        sofa_config = next((c for c in configs if c["part_id"] == part_id), None)

    vtk_path = THUMS_OUTPUT / subject / "vtk" / f"part_{part_id}.vtk"

    return {
        **part,
        "has_vtk": vtk_path.exists(),
        "vtk_size_kb": round(vtk_path.stat().st_size / 1024, 1) if vtk_path.exists() else None,
        "sofa_config": sofa_config,
    }


# ---------------------------------------------------------------------------
# Mesh serving (VTK -> STL conversion for Three.js)
# ---------------------------------------------------------------------------


@router.get("/{subject}/mesh/{part_id}.stl")
async def get_mesh_stl(subject: str, part_id: int):
    """Serve a THUMS part mesh as STL (converted from VTK on-the-fly).

    Three.js STLLoader can consume this directly.
    """
    vtk_path = THUMS_OUTPUT / subject / "vtk" / f"part_{part_id}.vtk"
    if not vtk_path.exists():
        raise HTTPException(404, f"VTK mesh not found for part {part_id}")

    try:
        import trimesh
        mesh = trimesh.load(str(vtk_path))
        if not isinstance(mesh, trimesh.Trimesh):
            raise HTTPException(422, "Could not load as single mesh")

        buf = io.BytesIO()
        mesh.export(buf, file_type="stl")
        return Response(
            content=buf.getvalue(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="thums_{subject}_{part_id}.stl"',
            },
        )
    except ImportError:
        raise HTTPException(500, "trimesh not installed")
    except Exception as exc:
        raise HTTPException(500, f"Mesh conversion failed: {exc}")


@router.get("/{subject}/mesh/{part_id}.vtk")
async def get_mesh_vtk(subject: str, part_id: int):
    """Serve raw VTK mesh file."""
    vtk_path = THUMS_OUTPUT / subject / "vtk" / f"part_{part_id}.vtk"
    if not vtk_path.exists():
        raise HTTPException(404, f"VTK mesh not found for part {part_id}")
    return FileResponse(vtk_path, media_type="application/octet-stream",
                        filename=f"thums_{subject}_{part_id}.vtk")


# ---------------------------------------------------------------------------
# Batch: load multiple parts into scene
# ---------------------------------------------------------------------------


class SceneLoadRequest(BaseModel):
    part_ids: list[int] = Field(..., description="List of THUMS part IDs to load")
    branch: str = Field(default="main")


@router.post("/{subject}/load-scene")
async def load_thums_scene(subject: str, req: SceneLoadRequest):
    """Load multiple THUMS parts into the simulation collision engine.

    Converts VTK to trimesh and registers in the branch's collision engine.
    """
    from ..main import _get_collision_engine

    engine = _get_collision_engine(req.branch)
    vtk_dir = THUMS_OUTPUT / subject / "vtk"

    loaded = []
    failed = []
    for pid in req.part_ids:
        vtk_path = vtk_dir / f"part_{pid}.vtk"
        if not vtk_path.exists():
            failed.append({"part_id": pid, "error": "VTK not found"})
            continue
        try:
            info = engine.load_mesh(
                mesh_id=f"thums_{pid}",
                file_path=vtk_path,
                label=f"THUMS_{subject}_{pid}",
                mesh_type="bone",
            )
            loaded.append(info)
        except Exception as exc:
            failed.append({"part_id": pid, "error": str(exc)})

    return {
        "subject": subject,
        "branch": req.branch,
        "loaded": len(loaded),
        "failed": len(failed),
        "loaded_parts": loaded,
        "failed_parts": failed,
    }
