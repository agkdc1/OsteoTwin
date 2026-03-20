"""Auth endpoints: register, login, Cloudflare Access SSO, me."""

from __future__ import annotations

import json
import base64
import logging

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..database import User, user_store
from .dependencies import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)

logger = logging.getLogger("osteotwin.auth")

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
    existing = await user_store.get_by_username(req.username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        id="",
        username=req.username,
        hashed_password=hash_password(req.password),
        role="user",
        status="pending",
    )
    await user_store.create_user(user)
    return {"message": "Registration successful. Awaiting admin approval."}


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = await user_store.get_by_username(req.username)

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.status != "approved":
        raise HTTPException(status_code=403, detail="Account not yet approved")

    return TokenResponse(
        access_token=create_access_token(user.id, user.username),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/cf-login", response_model=TokenResponse)
async def cf_login(request: Request):
    """Auto-login via Cloudflare Access JWT.

    Cloudflare Access sets the Cf-Access-Jwt-Assertion header on every
    request that passes through the Access gate. We extract the email
    from the JWT payload (no signature verification needed — Cloudflare
    already validated it before forwarding to us).
    """
    cf_jwt = request.headers.get("Cf-Access-Jwt-Assertion", "")
    if not cf_jwt:
        raise HTTPException(status_code=401, detail="No Cloudflare Access token")

    # Decode JWT payload (base64, no verification — CF already validated)
    try:
        payload_b64 = cf_jwt.split(".")[1]
        # Fix padding
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        email = payload.get("email", "")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Cloudflare Access token")

    if not email:
        raise HTTPException(status_code=401, detail="No email in Cloudflare Access token")

    # Auto-create and approve user
    user = await user_store.get_by_username(email)
    if not user:
        user = User(
            id="",
            username=email,
            hashed_password=hash_password(email),  # placeholder, never used
            role="admin",
            status="approved",
        )
        await user_store.create_user(user)
        logger.info("Auto-created user from Cloudflare Access: %s", email)

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
