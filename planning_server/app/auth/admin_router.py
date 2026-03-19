"""Admin endpoints: user approval/rejection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import User, user_store
from .dependencies import get_admin_user

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users/pending")
async def pending_users(_: User = Depends(get_admin_user)):
    users = await user_store.get_by_status("pending")
    return [
        {"id": u.id, "username": u.username, "created_at": str(u.created_at)}
        for u in users
    ]


@router.post("/users/{user_id}/approve")
async def approve_user(user_id: str, _: User = Depends(get_admin_user)):
    user = await user_store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await user_store.update_status(user_id, "approved")
    return {"approved": True, "user_id": user_id}


@router.post("/users/{user_id}/reject")
async def reject_user(user_id: str, _: User = Depends(get_admin_user)):
    user = await user_store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await user_store.update_status(user_id, "rejected")
    return {"rejected": True, "user_id": user_id}
