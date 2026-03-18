"""Grand Surgical Audit API endpoints.

Phase 1: POST /api/v1/audit/condense — Flash condenses discussion into audit package
Phase 2: POST /api/v1/audit/run — Pro/Ultra runs Grand Audit
Phase 3: POST /api/v1/audit/resolve — Surgeon submits resolutions, triggers re-audit
Full:    POST /api/v1/audit/full — Run complete Phase 1+2 pipeline
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.dependencies import get_current_user
from ..database import User
from .audit_manager import (
    AuditPackage,
    AuditReport,
    phase1_condense,
    phase2_audit,
    run_grand_audit,
)

logger = logging.getLogger("osteotwin.audit_router")

router = APIRouter(prefix="/api/v1/audit", tags=["grand-audit"])

# In-memory store for active audit sessions
_active_audits: dict[str, dict] = {}  # case_id -> {package, reports, resolutions}


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class CondenseRequest(BaseModel):
    case_id: str
    discussion_log: str = Field(..., description="Full pre-operative chat history")
    draft_plans: list[dict] = Field(..., description="Plan A, B, C as dicts")
    textbook_content: str = Field(default="", description="Cached anatomy textbook content")


class AuditRunRequest(BaseModel):
    case_id: str
    rendering_data: Optional[dict] = Field(None, description="6-axis rendering JSON from sim engine")


class ResolutionRequest(BaseModel):
    case_id: str
    resolutions: list[dict] = Field(
        ...,
        description="List of {finding_id: str, resolution: str} from the surgeon",
    )


class FullAuditRequest(BaseModel):
    case_id: str
    discussion_log: str
    draft_plans: list[dict]
    textbook_content: str = ""
    rendering_data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/condense", response_model=dict)
async def condense_audit_package(
    req: CondenseRequest,
    user: User = Depends(get_current_user),
):
    """Phase 1: Flash condenses discussion + textbook into audit package."""
    package = await phase1_condense(
        req.case_id, req.discussion_log, req.draft_plans, req.textbook_content,
    )

    # Store for subsequent phases
    _active_audits[req.case_id] = {
        "package": package,
        "reports": [],
        "resolutions": [],
    }

    return {
        "phase": 1,
        "package": package.model_dump(mode="json"),
        "status": "condensed",
        "token_reduction_pct": round(
            (1 - package.condensed_token_count / max(package.source_token_count, 1)) * 100, 1
        ),
    }


@router.post("/run", response_model=dict)
async def run_audit(
    req: AuditRunRequest,
    user: User = Depends(get_current_user),
):
    """Phase 2: Run Grand Surgical Audit on the condensed package."""
    session = _active_audits.get(req.case_id)
    if not session:
        raise HTTPException(404, "No audit package found. Run /condense first.")

    package = session["package"]
    round_num = len(session["reports"]) + 1
    previous_resolutions = session["resolutions"] if session["resolutions"] else None

    report = await phase2_audit(
        package,
        rendering_data=req.rendering_data,
        audit_round=round_num,
        previous_resolutions=previous_resolutions,
    )
    session["reports"].append(report)

    return {
        "phase": 2,
        "round": round_num,
        "report": report.model_dump(mode="json"),
        "status": "approved" if report.is_approved else "pending_resolution",
        "critical_count": sum(1 for f in report.findings if f.severity.value == "critical"),
        "warning_count": sum(1 for f in report.findings if f.severity.value == "warning"),
    }


@router.post("/resolve", response_model=dict)
async def submit_resolutions(
    req: ResolutionRequest,
    user: User = Depends(get_current_user),
):
    """Phase 3: Surgeon submits resolutions, triggers re-audit.

    After submitting resolutions, call /run again for the next audit round.
    """
    session = _active_audits.get(req.case_id)
    if not session:
        raise HTTPException(404, "No audit session found.")

    if not session["reports"]:
        raise HTTPException(400, "No audit report to resolve. Run /run first.")

    # Store resolutions
    session["resolutions"].extend(req.resolutions)

    # Mark findings as resolved in the latest report
    latest_report: AuditReport = session["reports"][-1]
    resolution_map = {r["finding_id"]: r["resolution"] for r in req.resolutions}
    resolved_count = 0
    for finding in latest_report.findings:
        if finding.finding_id in resolution_map:
            finding.resolved = True
            finding.surgeon_resolution = resolution_map[finding.finding_id]
            resolved_count += 1

    remaining_critical = len(latest_report.unresolved_critical)

    return {
        "phase": 3,
        "resolutions_submitted": len(req.resolutions),
        "findings_resolved": resolved_count,
        "remaining_critical": remaining_critical,
        "next_action": "Call POST /api/v1/audit/run for re-audit" if remaining_critical > 0 else "All critical resolved",
    }


@router.post("/full", response_model=dict)
async def full_audit_pipeline(
    req: FullAuditRequest,
    user: User = Depends(get_current_user),
):
    """Run complete Phase 1 + Phase 2 pipeline in one call.

    Returns the condensed package and initial audit report.
    Surgeon must then use /resolve + /run for the resolution loop.
    """
    result = await run_grand_audit(
        req.case_id,
        req.discussion_log,
        req.draft_plans,
        req.textbook_content,
        req.rendering_data,
    )

    # Store session
    package = AuditPackage.model_validate(result["package"])
    reports = [AuditReport.model_validate(r) for r in result["all_rounds"]]
    _active_audits[req.case_id] = {
        "package": package,
        "reports": reports,
        "resolutions": [],
    }

    return result


@router.get("/status/{case_id}")
async def audit_status(case_id: str):
    """Get current audit session status."""
    session = _active_audits.get(case_id)
    if not session:
        return {"case_id": case_id, "status": "no_session"}

    latest = session["reports"][-1] if session["reports"] else None
    return {
        "case_id": case_id,
        "status": "approved" if (latest and latest.is_approved) else "pending",
        "total_rounds": len(session["reports"]),
        "total_resolutions": len(session["resolutions"]),
        "latest_critical": len(latest.unresolved_critical) if latest else 0,
        "latest_verdict": latest.verdict_summary if latest else "",
    }
