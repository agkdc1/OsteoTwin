"""API routes for the Anatomical Rule Engine (Neo4j Knowledge Graph)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.dependencies import get_current_user
from ..database import User
from .connection import graph_db

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge-graph"])


class CorrectionRequest(BaseModel):
    region: str = Field(..., description='Body region, e.g. "distal_radius", "proximal_humerus"')
    correction: str = Field(
        ...,
        description='Surgeon correction, e.g. "The supraspinatus does not attach there"',
    )


class RuleQueryRequest(BaseModel):
    region: str = Field(..., description="Body region to query rules for")
    limit: int = Field(default=20, ge=1, le=100)


@router.post("/corrections")
async def store_correction(
    req: CorrectionRequest,
    user: User = Depends(get_current_user),
):
    """Store a surgeon's correction as a permanent anatomical rule.

    These corrections are pre-fetched before every LLM query to prevent
    the same mistake from being repeated.
    """
    if not graph_db.available:
        raise HTTPException(
            status_code=503,
            detail="Knowledge Graph (Neo4j) is not connected",
        )

    rule_id = await graph_db.store_surgeon_correction(
        region=req.region,
        correction=req.correction,
        surgeon_id=user.username,
    )
    return {"stored": True, "rule_id": rule_id, "region": req.region}


@router.get("/rules")
async def get_rules(
    region: str,
    limit: int = 20,
    _: User = Depends(get_current_user),
):
    """Retrieve anatomical rules for a body region."""
    if not graph_db.available:
        return {"rules": [], "note": "Knowledge Graph not connected"}

    rules = await graph_db.get_anatomical_rules(region, limit=limit)
    return {"region": region, "rules": rules, "count": len(rules)}


@router.get("/status")
async def knowledge_graph_status():
    """Check Neo4j connection status."""
    return {
        "connected": graph_db.available,
        "note": "Set NEO4J_PASSWORD in .env to enable" if not graph_db.available else "OK",
    }
