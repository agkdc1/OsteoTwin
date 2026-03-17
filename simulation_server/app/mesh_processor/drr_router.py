"""C-arm fluoroscopy simulation (DRR) API endpoints."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..auth import verify_api_key
from .drr_engine import DRREngine

logger = logging.getLogger("osteotwin.drr_router")

router = APIRouter(
    prefix="/api/v1/carm",
    tags=["c-arm"],
    dependencies=[Depends(verify_api_key)],
)

# Shared engine instance
_engine = DRREngine()


class DRRRequest(BaseModel):
    """Request to render a simulated C-arm image."""
    mesh_ids: list[str] = Field(
        ..., description="List of mesh IDs loaded in the collision engine to include"
    )
    projection: str = Field(
        default="ap",
        description="Projection type: ap, lateral, or oblique",
    )
    angle_deg: float = Field(
        default=0.0,
        description="Oblique angle in degrees (rotation around Z/superior axis)",
    )
    image_width: int = Field(default=512, ge=64, le=2048)
    image_height: int = Field(default=512, ge=64, le=2048)
    branch: str = Field(default="main")


@router.post("/render")
async def render_drr(req: DRRRequest):
    """Render a simulated C-arm fluoroscopy image (DRR).

    Takes mesh IDs from the collision engine, generates a simulated
    X-ray from the specified projection angle.

    Returns a PNG image (bone=white on black background).
    """
    from ..main import _get_collision_engine
    import trimesh

    engine = _get_collision_engine(req.branch)
    loaded = engine.list_meshes()
    mesh_map = {m["mesh_id"]: m for m in loaded}

    meshes = []
    for mid in req.mesh_ids:
        if mid not in mesh_map:
            raise HTTPException(404, f"Mesh '{mid}' not loaded in branch '{req.branch}'")
        # Access the actual trimesh object from the engine internals
        mesh_entry = engine._meshes.get(mid)
        if mesh_entry and isinstance(mesh_entry["mesh"], trimesh.Trimesh):
            meshes.append(mesh_entry["mesh"])

    if not meshes:
        raise HTTPException(422, "No valid meshes to render")

    _engine.load_bone_meshes(meshes)
    image = _engine.render(
        projection=req.projection,
        image_size=(req.image_width, req.image_height),
        angle_deg=req.angle_deg,
    )

    # Convert to PNG
    try:
        from PIL import Image
        img = Image.fromarray(image, mode="L")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(
            content=buf.getvalue(),
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="drr_{req.projection}.png"'},
        )
    except ImportError:
        # Return raw bytes if Pillow not available
        return Response(content=image.tobytes(), media_type="application/octet-stream")


@router.post("/multiview")
async def render_multiview(req: DRRRequest):
    """Render standard C-arm views: AP, Lateral, 30/45/60 deg obliques.

    Returns metadata with file paths (saved to disk).
    """
    from ..main import _get_collision_engine
    from .. import config
    import trimesh

    engine = _get_collision_engine(req.branch)
    meshes = []
    for mid in req.mesh_ids:
        mesh_entry = engine._meshes.get(mid)
        if mesh_entry and isinstance(mesh_entry["mesh"], trimesh.Trimesh):
            meshes.append(mesh_entry["mesh"])

    if not meshes:
        raise HTTPException(422, "No valid meshes to render")

    _engine.load_bone_meshes(meshes)

    out_dir = config.MESH_CACHE_DIR / "drr"
    paths = _engine.render_multiview(
        str(out_dir),
        image_size=(req.image_width, req.image_height),
    )

    return {
        "views_rendered": len(paths),
        "files": paths,
        "projections": ["ap", "lateral", "oblique_30", "oblique_45", "oblique_60"],
    }


@router.get("/projections")
async def list_projections():
    """List available C-arm projection types."""
    return {
        "projections": [
            {"name": "ap", "description": "Anteroposterior (front view)", "angle": 0},
            {"name": "lateral", "description": "Lateral (side view)", "angle": 0},
            {"name": "oblique", "description": "Oblique (custom angle around Z-axis)", "angle": "variable"},
        ],
        "standard_angles": [0, 15, 30, 45, 60, 90],
    }
