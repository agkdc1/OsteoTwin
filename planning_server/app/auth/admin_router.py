"""Admin endpoints: user approval/rejection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..database import User, async_session
from .dependencies import get_admin_user

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users/pending")
async def pending_users(_: User = Depends(get_admin_user)):
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.status == "pending")
        )
        users = result.scalars().all()
    return [
        {"id": u.id, "username": u.username, "created_at": str(u.created_at)}
        for u in users
    ]


@router.post("/users/{user_id}/approve")
async def approve_user(user_id: int, _: User = Depends(get_admin_user)):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.status = "approved"
        session.add(user)
        await session.commit()
    return {"approved": True, "user_id": user_id}


@router.post("/users/{user_id}/reject")
async def reject_user(user_id: int, _: User = Depends(get_admin_user)):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.status = "rejected"
        session.add(user)
        await session.commit()
    return {"rejected": True, "user_id": user_id}
