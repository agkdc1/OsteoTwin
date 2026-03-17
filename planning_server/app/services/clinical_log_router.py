"""Clinical Case Logging REST endpoints.

Provides API access to the Firestore clinical case log system.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import sys, pathlib

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)
)
from shared.clinical_log_schemas import SurgicalCaseLog

from .firestore_logger import clinical_logger

router = APIRouter(prefix="/api/v1/clinical-logs", tags=["clinical-logs"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def log_status():
    """Check Firestore logger availability."""
    return {
        "available": clinical_logger.available,
        "collection": "clinical_case_logs",
    }


@router.post("", status_code=201)
async def create_log(case_log: SurgicalCaseLog):
    """Create a new clinical case log entry.

    Writes asynchronously to Firestore. Returns immediately.
    """
    if not clinical_logger.available:
        raise HTTPException(
            status_code=503,
            detail="Firestore logger not available. Check GCP credentials.",
        )

    doc_id = await clinical_logger.log_case(case_log)
    if not doc_id:
        raise HTTPException(status_code=500, detail="Failed to write log to Firestore")

    return {"log_id": doc_id, "case_id": case_log.case_id}


@router.get("/case/{case_id}")
async def get_case_logs(case_id: str, limit: int = 50):
    """Retrieve all logs for a specific case."""
    logs = await clinical_logger.get_case_logs(case_id, limit=limit)
    return {"case_id": case_id, "count": len(logs), "logs": logs}


@router.get("/surgeon/{surgeon_id}")
async def get_surgeon_logs(surgeon_id: str, limit: int = 100):
    """Retrieve all logs for a specific surgeon."""
    logs = await clinical_logger.get_surgeon_logs(surgeon_id, limit=limit)
    return {"surgeon_id": surgeon_id, "count": len(logs), "logs": logs}


class PostOpFeedback(BaseModel):
    deviation_log: str = Field(
        ..., description="Description of real-world deviations from the plan"
    )
    satisfaction: Optional[int] = Field(None, ge=1, le=5)
    additional_notes: Optional[str] = None


@router.patch("/{log_id}/post-op")
async def update_post_op(log_id: str, feedback: PostOpFeedback):
    """Update a log with post-operative feedback.

    Called after surgery to capture real-world deviations.
    """
    if not clinical_logger.available:
        raise HTTPException(status_code=503, detail="Firestore logger not available")

    ok = await clinical_logger.update_post_op(
        log_id=log_id,
        deviation_log=feedback.deviation_log,
        satisfaction=feedback.satisfaction,
        additional_notes=feedback.additional_notes,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update post-op feedback")

    return {"updated": True, "log_id": log_id}
