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
    """Check soft-tissue engine availability."""
    return {
        "sofa_available": sofa_available(),
        "fallback_mode": "spring-mass" if not sofa_available() else "sofa-fea",
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


def _get_default_tissues(case_id: str) -> list[dict]:
    """Return default tissue definitions for common fracture patterns.

    In production, these would come from a database keyed by AO classification.
    """
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
