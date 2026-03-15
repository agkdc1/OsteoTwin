"""Auth endpoints: register, login, me."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from ..database import User, async_session
from .dependencies import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    async with async_session() as session:
        existing = await session.execute(
            select(User).where(User.username == req.username)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already taken")

        user = User(
            username=req.username,
            hashed_password=hash_password(req.password),
            role="user",
            status="pending",
        )
        session.add(user)
        await session.commit()
    return {"message": "Registration successful. Awaiting admin approval."}


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.username == req.username)
        )
        user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.status != "approved":
        raise HTTPException(status_code=403, detail="Account not yet approved")

    return TokenResponse(
        access_token=create_access_token(user.id, user.username),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "status": user.status,
    }
