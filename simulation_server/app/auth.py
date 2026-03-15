"""API-key authentication for the Simulation Server."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from . import config


async def verify_api_key(x_api_key: str = Header(...)) -> str:
    """Dependency that validates the X-API-Key header."""
    if not config.SIM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SIM_API_KEY not configured on server",
        )
    if x_api_key != config.SIM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return x_api_key
