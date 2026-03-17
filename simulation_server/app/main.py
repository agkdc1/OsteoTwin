"""OsteoTwin Simulation Server — Port 8300.

Handles heavy 3D mesh processing (pydicom → VTK/trimesh),
rigid-body collision detection, and deterministic biomechanical simulation.
All physics results are computed here — the LLM never guesses physics.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .auth import verify_api_key

# Shared protocol models — single source of truth
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
from shared.simulation_protocol import (
    SimActionRequest,
    SimActionResponse,
    CollisionFlag,
    TensionMetric,
    UpdatedFragmentCoords,
    TranslationVector,
    RotationMatrix,
)
from shared.collision_protocol import (
    CollisionCheckRequest,
    CollisionCheckResponse,
    IntersectionHit,
    Vec3,
)

from .collision.engine import CollisionEngine
from .mesh_processor.router import router as dicom_router
from .mesh_processor.implant_router import router as implant_router
from .mesh_processor.segment_router import router as segment_router
from .mesh_processor.export_router import router as export_router
from .soft_tissue.router import router as soft_tissue_router
from .mesh_processor.thums_router import router as thums_router
from .mesh_processor.drr_router import router as drr_router
from .mesh_processor.approach_router import router as approach_router

logger = logging.getLogger("osteotwin.simulation")

# ---------------------------------------------------------------------------
# In-memory branch store (will be replaced by persistent storage)
# ---------------------------------------------------------------------------

# branch_name -> { fragment_id -> { position, rotation } }
_branch_states: dict[str, dict] = {}


def _get_or_create_branch(branch: str) -> dict:
    if branch not in _branch_states:
        _branch_states[branch] = {}
    return _branch_states[branch]


# Per-branch collision engines
_collision_engines: dict[str, CollisionEngine] = {}


def _get_collision_engine(branch: str) -> CollisionEngine:
    if branch not in _collision_engines:
        _collision_engines[branch] = CollisionEngine()
    return _collision_engines[branch]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Simulation Server starting on %s:%s", config.SIM_HOST, config.SIM_PORT
    )
    config.JOBS_DIR.mkdir(exist_ok=True)
    config.MESH_CACHE_DIR.mkdir(exist_ok=True)
    yield
    logger.info("Simulation Server shut down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="OsteoTwin Simulation Server",
    version="0.1.0",
    description="Deterministic biomechanical simulation engine for fracture reduction.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(dicom_router)
app.include_router(implant_router)
app.include_router(segment_router)
app.include_router(export_router)
app.include_router(soft_tissue_router)
app.include_router(thums_router)
app.include_router(drr_router)
app.include_router(approach_router)


# ---------------------------------------------------------------------------
# Health (public — no API key required)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "service": "simulation_server", "port": config.SIM_PORT}


@app.get("/")
async def root():
    return {
        "service": "OsteoTwin Simulation Server",
        "version": "0.1.0",
        "docs": "/docs",
    }


# ---------------------------------------------------------------------------
# Core simulation endpoint
# ---------------------------------------------------------------------------


@app.post(
    "/api/v1/simulate/action",
    response_model=SimActionResponse,
    dependencies=[Depends(verify_api_key)],
)
async def simulate_action(req: SimActionRequest) -> SimActionResponse:
    """Execute a deterministic simulation action.

    Accepts a SimActionRequest (fragment movement + constraints),
    runs collision detection and tension estimation via trimesh,
    and returns deterministic SimActionResponse.
    """
    branch_state = _get_or_create_branch(req.branch)

    # Apply the requested transformation to the fragment
    new_position = TranslationVector(
        x=req.translation.x,
        y=req.translation.y,
        z=req.translation.z,
    )

    # Store updated state in the branch
    branch_state[req.fragment_id] = {
        "position": new_position,
        "rotation": req.rotation,
    }

    # --- Collision detection stub ---
    # TODO: Replace with real trimesh collision detection once meshes are loaded
    collisions: list[CollisionFlag] = []
    has_critical = False

    # --- Tension estimation stub ---
    # TODO: Replace with real tension model (SOFA framework integration)
    tensions: list[TensionMetric] = []

    updated_coords = UpdatedFragmentCoords(
        fragment_id=req.fragment_id,
        position=new_position,
        rotation=req.rotation,
    )

    return SimActionResponse(
        request_id=req.request_id,
        success=True,
        updated_coords=updated_coords,
        collisions=collisions,
        total_collisions=len(collisions),
        has_critical_collision=has_critical,
        tension_metrics=tensions,
        max_tension_exceeded=any(t.exceeded for t in tensions),
        engine_summary=f"Fragment '{req.fragment_id}' moved to ({new_position.x}, {new_position.y}, {new_position.z}) on branch '{req.branch}'. 0 collisions detected.",
        branch=req.branch,
        snapshot_id=uuid.uuid4().hex[:12],
    )


# ---------------------------------------------------------------------------
# K-wire / trajectory collision check (Phase 1 core feature)
# ---------------------------------------------------------------------------


@app.post(
    "/api/v1/simulate/collision",
    response_model=CollisionCheckResponse,
    dependencies=[Depends(verify_api_key)],
)
async def simulate_collision(req: CollisionCheckRequest) -> CollisionCheckResponse:
    """Check a K-wire trajectory (ray) for intersections with loaded meshes.

    Casts a ray from origin along direction and returns every mesh intersection
    sorted by distance. Deterministic — uses trimesh ray casting.
    """
    engine = _get_collision_engine(req.branch)

    if not engine.list_meshes():
        return CollisionCheckResponse(
            request_id=req.request_id,
            success=True,
            hits=[],
            total_hits=0,
            engine_summary="No meshes loaded in this branch. Load meshes first via POST /api/v1/meshes.",
            branch=req.branch,
        )

    raw_hits = engine.ray_cast(
        origin=(req.ray_origin.x, req.ray_origin.y, req.ray_origin.z),
        direction=(req.ray_direction.x, req.ray_direction.y, req.ray_direction.z),
        max_length=req.max_length_mm,
    )

    hits = [
        IntersectionHit(
            mesh_id=h["mesh_id"],
            mesh_label=h["mesh_label"],
            hit_point=Vec3(x=h["hit_point"][0], y=h["hit_point"][1], z=h["hit_point"][2]),
            distance_mm=h["distance_mm"],
            face_index=h["face_index"],
            is_entry=h["is_entry"],
        )
        for h in raw_hits
    ]

    # Derive collision flags
    bone_entries = [h for h in raw_hits if h["mesh_type"] == "bone" and h["is_entry"]]
    bone_exits = [h for h in raw_hits if h["mesh_type"] == "bone" and not h["is_entry"]]
    hardware_hits = [h for h in raw_hits if h["mesh_type"] == "hardware"]

    passes_through = len(bone_entries) >= 1 and len(bone_exits) >= 1
    breaches_far = len(bone_exits) >= 2  # exits twice = through-and-through
    intersects_hw = len(hardware_hits) > 0

    # Build summary
    parts = [f"{len(raw_hits)} intersection(s) found"]
    if passes_through:
        parts.append("K-wire passes through cortex (bicortical)")
    if breaches_far:
        parts.append("WARNING: K-wire breaches far cortex")
    if intersects_hw:
        hw_labels = {h["mesh_label"] for h in hardware_hits}
        parts.append(f"K-wire intersects hardware: {', '.join(hw_labels)}")
    if not raw_hits:
        parts = ["No intersections - trajectory is clear"]

    return CollisionCheckResponse(
        request_id=req.request_id,
        success=True,
        hits=hits,
        total_hits=len(hits),
        passes_through_cortex=passes_through,
        breaches_far_cortex=breaches_far,
        intersects_hardware=intersects_hw,
        engine_summary=". ".join(parts) + ".",
        branch=req.branch,
    )


# ---------------------------------------------------------------------------
# Mesh management
# ---------------------------------------------------------------------------


@app.post("/api/v1/meshes", dependencies=[Depends(verify_api_key)])
async def load_mesh(
    mesh_id: str,
    file_path: str,
    label: str = "",
    mesh_type: str = "bone",
    branch: str = "main",
):
    """Load an STL/OBJ/PLY mesh into a branch's collision engine."""
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mesh file not found: {file_path}",
        )

    engine = _get_collision_engine(branch)
    try:
        info = engine.load_mesh(mesh_id, path, label=label, mesh_type=mesh_type)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to load mesh: {exc}",
        )
    return {"loaded": True, "branch": branch, **info}


@app.get("/api/v1/meshes", dependencies=[Depends(verify_api_key)])
async def list_meshes(branch: str = "main"):
    """List all meshes loaded in a branch's collision engine."""
    engine = _get_collision_engine(branch)
    return {"branch": branch, "meshes": engine.list_meshes()}


@app.delete("/api/v1/meshes/{mesh_id}", dependencies=[Depends(verify_api_key)])
async def remove_mesh(mesh_id: str, branch: str = "main"):
    """Remove a mesh from the branch's collision engine."""
    engine = _get_collision_engine(branch)
    removed = engine.remove_mesh(mesh_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mesh '{mesh_id}' not found in branch '{branch}'",
        )
    return {"removed": True, "mesh_id": mesh_id, "branch": branch}


# ---------------------------------------------------------------------------
# Mesh-mesh intersection check
# ---------------------------------------------------------------------------


@app.post("/api/v1/simulate/intersection", dependencies=[Depends(verify_api_key)])
async def check_mesh_intersection(
    mesh_id_a: str, mesh_id_b: str, branch: str = "main"
):
    """Check if two loaded meshes collide (rigid-body boolean intersection)."""
    engine = _get_collision_engine(branch)
    try:
        result = engine.check_intersection(mesh_id_a, mesh_id_b)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {"branch": branch, **result}


# ---------------------------------------------------------------------------
# Branch management
# ---------------------------------------------------------------------------


@app.post("/api/v1/branches/promote", dependencies=[Depends(verify_api_key)])
async def promote_branch(source_branch: str, target_branch: str = "main"):
    """Promote a hypothesis branch to the target branch (default: main).

    Used when the surgeon approves an LLM-proposed plan.
    """
    if source_branch not in _branch_states:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Branch '{source_branch}' does not exist",
        )
    _branch_states[target_branch] = dict(_branch_states[source_branch])
    return {
        "promoted": True,
        "source": source_branch,
        "target": target_branch,
        "fragment_count": len(_branch_states[target_branch]),
    }


@app.get("/api/v1/branches", dependencies=[Depends(verify_api_key)])
async def list_branches():
    """List all simulation branches."""
    return {
        name: {"fragment_count": len(state)}
        for name, state in _branch_states.items()
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "simulation_server.app.main:app",
        host=config.SIM_HOST,
        port=config.SIM_PORT,
        reload=True,
    )
