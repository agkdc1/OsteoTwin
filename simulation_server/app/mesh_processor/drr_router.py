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


# ---------------------------------------------------------------------------
# Physical C-arm simulation with collision detection
# ---------------------------------------------------------------------------

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.carm_schemas import (
    CARM_SPECS, CarmModel, CarmPose, CarmSpec, ORBedSpec, PatientModel, PatientPosition,
)
from .carm_simulator import (
    check_feasibility, compute_feasibility_map, generate_or_scene,
    render_or_scene_6view,
)


class PhysicalCarmRequest(BaseModel):
    """Request for physically-constrained C-arm simulation."""
    carm_model: str = Field(default="generic_full", description="C-arm model key")
    orbital_deg: float = Field(default=0.0, description="Orbital rotation (0=AP, 90=lateral)")
    angular_deg: float = Field(default=0.0, description="Cranial/caudal tilt")
    isocenter_lps: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    # Bed
    bed_height_mm: float = Field(default=850.0)
    bed_width_mm: float = Field(default=520.0)
    rail_height_mm: float = Field(default=120.0)
    # Patient
    patient_position: str = Field(default="supine")
    body_width_mm: float = Field(default=400.0)
    body_depth_mm: float = Field(default=220.0)


@router.post("/feasibility")
async def check_carm_feasibility(req: PhysicalCarmRequest):
    """Check if a C-arm pose is physically achievable.

    Accounts for C-arm arc radius, bed dimensions, rail height,
    and patient body volume. Returns collision details and clearance.
    """
    carm = CARM_SPECS.get(CarmModel(req.carm_model), CARM_SPECS[CarmModel.GENERIC_FULL])
    bed = ORBedSpec(
        height_mm=req.bed_height_mm, width_mm=req.bed_width_mm,
        rail_height_mm=req.rail_height_mm,
        bed_center_lps=(0, -(req.bed_height_mm), 0),
    )
    patient = PatientModel(
        position=PatientPosition(req.patient_position),
        body_width_mm=req.body_width_mm,
        body_depth_mm=req.body_depth_mm,
    )
    pose = CarmPose(
        orbital_deg=req.orbital_deg,
        angular_deg=req.angular_deg,
        isocenter_lps=tuple(req.isocenter_lps),
    )
    result = check_feasibility(carm, pose, bed, patient)
    return result.model_dump()


@router.post("/feasibility-map")
async def compute_carm_feasibility_map(req: PhysicalCarmRequest):
    """Compute full feasibility map across all orbital/angular combinations.

    Returns percentage of achievable poses and a heatmap of collisions.
    """
    carm = CARM_SPECS.get(CarmModel(req.carm_model), CARM_SPECS[CarmModel.GENERIC_FULL])
    bed = ORBedSpec(
        height_mm=req.bed_height_mm, width_mm=req.bed_width_mm,
        rail_height_mm=req.rail_height_mm,
        bed_center_lps=(0, -(req.bed_height_mm), 0),
    )
    patient = PatientModel(
        position=PatientPosition(req.patient_position),
        body_width_mm=req.body_width_mm,
        body_depth_mm=req.body_depth_mm,
    )
    fmap = compute_feasibility_map(
        carm, bed, patient,
        isocenter_lps=tuple(req.isocenter_lps),
        orbital_step=5.0,
        angular_step=5.0,
    )
    # Return summary without full results array (can be large)
    return {
        "carm_model": fmap.carm_model,
        "bed_type": fmap.bed_type,
        "patient_position": fmap.patient_position,
        "total_poses_tested": fmap.total_poses_tested,
        "feasible_poses": fmap.feasible_poses,
        "blocked_poses": fmap.blocked_poses,
        "feasibility_pct": fmap.feasibility_pct,
        "blocked_samples": [
            r.model_dump() for r in fmap.results if not r.feasible
        ][:20],  # first 20 blocked poses
    }


@router.post("/scene-6view")
async def render_or_scene(req: PhysicalCarmRequest):
    """Generate 3D OR scene (bed + patient + C-arm) and render 6 views.

    Returns the stitched 6-view image path for Gemini validation.
    """
    carm = CARM_SPECS.get(CarmModel(req.carm_model), CARM_SPECS[CarmModel.GENERIC_FULL])
    bed = ORBedSpec(
        height_mm=req.bed_height_mm, width_mm=req.bed_width_mm,
        rail_height_mm=req.rail_height_mm,
        bed_center_lps=(0, -(req.bed_height_mm), 0),
    )
    patient = PatientModel(
        position=PatientPosition(req.patient_position),
        body_width_mm=req.body_width_mm,
        body_depth_mm=req.body_depth_mm,
    )
    pose = CarmPose(
        orbital_deg=req.orbital_deg,
        angular_deg=req.angular_deg,
        isocenter_lps=tuple(req.isocenter_lps),
    )

    # Check feasibility first
    feasibility = check_feasibility(carm, pose, bed, patient)

    # Generate 3D scene
    scene = generate_or_scene(carm, pose, bed, patient)

    # Render 6-view
    from .. import config
    out_dir = config.MESH_CACHE_DIR / "carm_scenes"
    stitched = render_or_scene_6view(scene, out_dir)

    # Export scene as GLB for Three.js viewing
    glb_path = out_dir / "or_scene.glb"
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.export(str(glb_path))

    return {
        "feasibility": feasibility.model_dump(),
        "scene_glb": str(glb_path),
        "six_view_image": str(stitched) if stitched else None,
        "carm": {
            "model": carm.name,
            "arc_radius_mm": carm.arc_radius_mm,
            "throat_depth_mm": carm.throat_depth_mm,
            "sid_mm": carm.sid_mm,
        },
    }


@router.post("/validate-with-gemini")
async def validate_carm_with_gemini(req: PhysicalCarmRequest):
    """Full pipeline: check feasibility, render 6-view, send to Gemini for validation.

    Gemini receives:
    - The 6-view stitched image of the OR scene
    - The feasibility constraints and collision data
    - The C-arm specs and patient positioning

    Gemini confirms whether the C-arm movement is physically possible
    and flags any risks the collision model might have missed.
    """
    # Run feasibility check
    carm = CARM_SPECS.get(CarmModel(req.carm_model), CARM_SPECS[CarmModel.GENERIC_FULL])
    bed = ORBedSpec(
        height_mm=req.bed_height_mm, width_mm=req.bed_width_mm,
        rail_height_mm=req.rail_height_mm,
        bed_center_lps=(0, -(req.bed_height_mm), 0),
    )
    patient = PatientModel(
        position=PatientPosition(req.patient_position),
        body_width_mm=req.body_width_mm,
        body_depth_mm=req.body_depth_mm,
    )
    pose = CarmPose(
        orbital_deg=req.orbital_deg,
        angular_deg=req.angular_deg,
        isocenter_lps=tuple(req.isocenter_lps),
    )

    feasibility = check_feasibility(carm, pose, bed, patient)

    # Build Gemini prompt with context
    context = (
        f"## C-arm Feasibility Check\n"
        f"**C-arm:** {carm.name} (arc radius: {carm.arc_radius_mm}mm, throat: {carm.throat_depth_mm}mm)\n"
        f"**Pose:** Orbital {pose.orbital_deg} deg, Angular {pose.angular_deg} deg\n"
        f"**Bed:** {bed.width_mm}mm wide, rails {bed.rail_height_mm}mm high\n"
        f"**Patient:** {patient.position.value}, {patient.body_width_mm}mm wide, {patient.body_depth_mm}mm deep\n\n"
        f"**Collision model result:** {'FEASIBLE' if feasibility.feasible else 'BLOCKED'}\n"
    )
    if feasibility.collisions:
        context += f"**Collisions:** {[c.value for c in feasibility.collisions]}\n"
    if feasibility.min_clearance_mm is not None:
        context += f"**Min clearance:** {feasibility.min_clearance_mm}mm\n"
    if feasibility.notes:
        context += f"**Notes:** {'; '.join(feasibility.notes)}\n"

    context += (
        "\n## Task\n"
        "Review the OR scene rendering and the collision model output. "
        "Confirm whether the C-arm can physically achieve this position. "
        "Consider: sterile drape clearance, cable routing, "
        "anesthesia equipment on the head-side, and surgeon access. "
        "Output <status>CONFIRMED</status> or <status>BLOCKED</status> "
        "with a brief explanation."
    )

    # Call Gemini
    try:
        # Import from planning server's LLM module
        _sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent.parent.parent / "planning_server"))
        from planning_server.app.pipeline.llm import generate_text, Provider
        import re

        gemini_response = await generate_text(
            context,
            system="You are an OR setup specialist validating C-arm positioning feasibility.",
            provider=Provider.GEMINI,
            max_tokens=1024,
        )

        status_match = re.search(r"<status>(CONFIRMED|BLOCKED)</status>", gemini_response)
        gemini_status = status_match.group(1) if status_match else "UNKNOWN"

    except Exception as exc:
        logger.warning("Gemini validation failed: %s", exc)
        gemini_response = f"Gemini unavailable: {exc}"
        gemini_status = "UNAVAILABLE"

    return {
        "collision_model": feasibility.model_dump(),
        "gemini_validation": {
            "status": gemini_status,
            "response": gemini_response,
        },
        "combined_verdict": (
            "FEASIBLE" if feasibility.feasible and gemini_status == "CONFIRMED"
            else "BLOCKED" if not feasibility.feasible
            else "REVIEW" if gemini_status == "BLOCKED"
            else "FEASIBLE_UNCONFIRMED"
        ),
    }
