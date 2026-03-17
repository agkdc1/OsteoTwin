"""Soft-tissue simulation endpoints for the Simulation Server."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Depends

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.soft_tissue_protocol import (
    SoftTissueSimRequest,
    SoftTissueSimResponse,
    TissueTensionResult,
    VascularProximityResult,
)

from ..auth import verify_api_key
from .engine import SoftTissueEngine, sofa_available
from .thums_loader import get_thums_db

logger = logging.getLogger("osteotwin.soft_tissue.router")

router = APIRouter(
    prefix="/api/v1/soft-tissue",
    tags=["soft-tissue"],
    dependencies=[Depends(verify_api_key)],
)

# Shared engine instance
_engine = SoftTissueEngine()


@router.get("/status")
async def soft_tissue_status():
    """Check soft-tissue engine availability and THUMS data status."""
    thums = get_thums_db()
    return {
        "sofa_available": sofa_available(),
        "fallback_mode": "spring-mass" if not sofa_available() else "sofa-fea",
        "thums_loaded": thums.available,
        "thums_summary": thums.summary() if thums.available else None,
        "description": (
            "SOFA FEA engine active" if sofa_available()
            else "Using spring-mass approximation (install SOFA for full FEA)"
        ),
    }


@router.post("/simulate", response_model=SoftTissueSimResponse)
async def simulate_soft_tissue(req: SoftTissueSimRequest) -> SoftTissueSimResponse:
    """Run soft-tissue biomechanical simulation.

    Computes tissue tensions, vascular proximity, and periosteal stripping
    estimates for the given fragment configuration.

    Uses SOFA FEA when available, otherwise falls back to spring-mass model.
    """
    t0 = time.time()

    # Convert tissue definitions to engine format
    if req.tissues:
        tissues = [t.model_dump(mode="json") for t in req.tissues]
    else:
        tissues = _get_default_tissues(req.case_id)

    # Compute tensions
    tension_results_raw = _engine.compute_tensions(
        tissues=tissues,
        fragment_positions=req.fragment_positions,
        fragment_rotations=req.fragment_rotations,
    )

    tension_results = [TissueTensionResult(**r) for r in tension_results_raw]

    max_exceeded = any(t.exceeded for t in tension_results)
    critical = [t.label for t in tension_results if t.risk_level == "critical"]

    # Compute vascular/nerve proximity (using default structures)
    proximity_structs = _get_default_vascular_structures(req.case_id)
    proximity_raw = _engine.compute_proximity(proximity_structs, req.fragment_positions)
    proximity_warnings = [VascularProximityResult(**p) for p in proximity_raw]

    # Periosteal stripping estimate (simplified: proportional to total displacement)
    import numpy as np

    total_displacement = sum(
        np.linalg.norm(pos) for pos in req.fragment_positions.values()
    )
    periosteal_strip = total_displacement * 8.0  # rough: 8mm² per mm displacement

    # Build summary
    summary_parts = []
    mode = "SOFA FEA" if sofa_available() else "spring-mass model"
    summary_parts.append(f"Soft-tissue simulation ({mode})")

    safe_count = sum(1 for t in tension_results if t.risk_level == "safe")
    warn_count = sum(1 for t in tension_results if t.risk_level == "warning")
    crit_count = sum(1 for t in tension_results if t.risk_level == "critical")
    summary_parts.append(
        f"{len(tension_results)} tissues analyzed: "
        f"{safe_count} safe, {warn_count} warning, {crit_count} critical"
    )

    if critical:
        summary_parts.append(
            f"CRITICAL: {', '.join(critical)} — tension exceeds safe threshold"
        )

    prox_warns = [p for p in proximity_warnings if p.warning]
    if prox_warns:
        for pw in prox_warns:
            summary_parts.append(pw.warning)

    elapsed = (time.time() - t0) * 1000

    return SoftTissueSimResponse(
        request_id=req.request_id,
        success=True,
        branch=req.branch,
        tension_results=tension_results,
        max_tension_exceeded=max_exceeded,
        critical_tissues=critical,
        proximity_warnings=proximity_warnings,
        estimated_periosteal_strip_mm2=round(periosteal_strip, 1),
        engine_summary=". ".join(summary_parts) + ".",
        simulation_time_ms=round(elapsed, 1),
    )


@router.get("/thums/{subject}")
async def thums_material_data(subject: str, region: str = ""):
    """Query THUMS material database for a specific subject and region."""
    thums = get_thums_db(subject)
    if not thums.available:
        return {"error": f"THUMS data not available for {subject}", "available_subjects": ["AF05", "AF50", "AM50", "AM95"]}

    if region:
        bone_parts = thums.get_bone_parts(region)
        soft_parts = thums.get_soft_tissue_parts(region)
        return {
            "subject": subject,
            "region": region,
            "bone_parts": len(bone_parts),
            "soft_tissue_parts": len(soft_parts),
            "bone_samples": bone_parts[:10],
            "soft_tissue_samples": soft_parts[:10],
        }

    return thums.summary()


def _get_default_tissues(case_id: str) -> list[dict]:
    """Return tissue definitions - THUMS-sourced when available, hardcoded fallback.

    When THUMS data is loaded, returns anatomically accurate tissue properties
    from the parsed THUMS v7.1 model. Falls back to simplified defaults otherwise.
    """
    thums = get_thums_db()
    if thums.available:
        # Try to infer region from case_id naming convention
        region = None
        cid = case_id.lower()
        if "wrist" in cid or "radius" in cid or "humerus" in cid:
            region = "upper_extremity_right"
        elif "femur" in cid or "tibia" in cid or "ankle" in cid or "knee" in cid:
            region = "lower_extremity_right"
        elif "pelvis" in cid or "hip" in cid:
            region = "abdomen_pelvis"

        if region:
            thums_tissues = thums.build_tissue_definitions(region)
            if thums_tissues:
                logger.info("Using THUMS %s tissues for %s (%d definitions)",
                            thums.subject, case_id, len(thums_tissues))
                return thums_tissues

    # Fallback to hardcoded defaults
    return [
        {
            "tissue_id": "t_supraspinatus",
            "tissue_type": "tendon",
            "label": "supraspinatus",
            "origin": {
                "label": "supraspinatus_origin",
                "fragment_id": "proximal",
                "position": [10.0, 5.0, 30.0],
            },
            "insertion": {
                "label": "supraspinatus_insertion",
                "fragment_id": "distal",
                "position": [15.0, 8.0, 5.0],
            },
            "rest_length_mm": 28.0,
            "max_tension_n": 30.0,
            "stiffness": 50.0,
        },
        {
            "tissue_id": "t_brachioradialis",
            "tissue_type": "muscle",
            "label": "brachioradialis",
            "origin": {
                "label": "brachioradialis_origin",
                "fragment_id": "proximal",
                "position": [-5.0, 10.0, 25.0],
            },
            "insertion": {
                "label": "brachioradialis_insertion",
                "fragment_id": "distal",
                "position": [0.0, 12.0, -10.0],
            },
            "rest_length_mm": 40.0,
            "max_tension_n": 50.0,
            "stiffness": 30.0,
        },
        {
            "tissue_id": "t_periosteum",
            "tissue_type": "periosteum",
            "label": "periosteum",
            "origin": {
                "label": "periosteum_proximal",
                "fragment_id": "proximal",
                "position": [0.0, 0.0, 10.0],
            },
            "insertion": {
                "label": "periosteum_distal",
                "fragment_id": "distal",
                "position": [0.0, 0.0, -5.0],
            },
            "rest_length_mm": 15.0,
            "max_tension_n": 15.0,
            "stiffness": 80.0,
        },
    ]


def _get_default_vascular_structures(case_id: str) -> list[dict]:
    """Return default vascular/nerve structures for proximity checking."""
    return [
        {
            "label": "radial_artery",
            "tissue_type": "vessel",
            "position": [8.0, -3.0, 0.0],
            "compression_threshold_mm": 2.0,
            "warning_threshold_mm": 5.0,
        },
        {
            "label": "median_nerve",
            "tissue_type": "nerve",
            "position": [0.0, -5.0, 2.0],
            "compression_threshold_mm": 1.5,
            "warning_threshold_mm": 4.0,
        },
        {
            "label": "radial_nerve",
            "tissue_type": "nerve",
            "position": [12.0, 2.0, 15.0],
            "compression_threshold_mm": 1.5,
            "warning_threshold_mm": 4.0,
        },
    ]
