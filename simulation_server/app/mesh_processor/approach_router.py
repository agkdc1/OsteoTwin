"""Surgical Approach Mapping API endpoints.

Serves approach data (danger zones, layers, landmarks) and generates
danger zone meshes that can be overlaid on the 3D viewer.
"""

from __future__ import annotations

import io
import logging

import numpy as np
import trimesh
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..auth import verify_api_key

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.approach_atlas import APPROACH_ATLAS, get_approaches_for_region, DangerLevel

logger = logging.getLogger("osteotwin.approach")

router = APIRouter(
    prefix="/api/v1/approaches",
    tags=["surgical-approaches"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("")
async def list_approaches(region: str = ""):
    """List available surgical approaches, optionally filtered by region."""
    if region:
        approaches = get_approaches_for_region(region)
    else:
        approaches = list(APPROACH_ATLAS.values())

    return {
        "count": len(approaches),
        "approaches": [
            {
                "key": k,
                "name": a.name,
                "target_region": a.target_region,
                "description": a.description,
                "interval": a.interval,
                "danger_zone_count": len(a.danger_zones),
                "source": a.source,
            }
            for k, a in APPROACH_ATLAS.items()
            if not region or region in a.target_region
        ],
    }


@router.get("/{approach_key}")
async def get_approach_detail(approach_key: str):
    """Get full approach data including danger zones and layer dissection."""
    approach = APPROACH_ATLAS.get(approach_key)
    if not approach:
        raise HTTPException(404, f"Approach '{approach_key}' not found. Available: {list(APPROACH_ATLAS.keys())}")

    return {
        "key": approach_key,
        "name": approach.name,
        "target_region": approach.target_region,
        "description": approach.description,
        "interval": approach.interval,
        "patient_position": approach.patient_position,
        "incision": approach.incision,
        "source": approach.source,
        "layers": approach.layers,
        "danger_zones": [
            {
                "name": dz.name,
                "structure_type": dz.structure_type,
                "danger_level": dz.danger_level.value,
                "position_lps": list(dz.position_lps),
                "safe_distance_mm": dz.safe_distance_mm,
                "note": dz.note,
            }
            for dz in approach.danger_zones
        ],
    }


DANGER_COLORS = {
    DangerLevel.CRITICAL: (220, 40, 40, 160),   # translucent red
    DangerLevel.WARNING: (220, 180, 40, 120),    # translucent yellow
    DangerLevel.MONITOR: (40, 120, 220, 80),     # translucent blue
}


@router.get("/{approach_key}/danger-zones.stl")
async def get_danger_zone_meshes(approach_key: str):
    """Generate danger zone spheres as a combined STL mesh.

    Each danger zone is rendered as a sphere at its LPS position
    with radius = safe_distance_mm. Color-coded by danger level.
    Load into the 3D viewer to visualize the danger corridor.
    """
    approach = APPROACH_ATLAS.get(approach_key)
    if not approach:
        raise HTTPException(404, f"Approach '{approach_key}' not found")

    meshes = []
    for dz in approach.danger_zones:
        sphere = trimesh.creation.icosphere(subdivisions=2, radius=dz.safe_distance_mm)
        sphere.apply_translation(list(dz.position_lps))

        # Color by danger level
        color = DANGER_COLORS.get(dz.danger_level, (200, 200, 200, 128))
        colors = np.full((len(sphere.faces), 4), color, dtype=np.uint8)
        sphere.visual.face_colors = colors

        meshes.append(sphere)

    if not meshes:
        raise HTTPException(422, "No danger zones defined for this approach")

    combined = trimesh.util.concatenate(meshes)

    buf = io.BytesIO()
    combined.export(buf, file_type="stl")
    return Response(
        content=buf.getvalue(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{approach_key}_danger_zones.stl"'},
    )
