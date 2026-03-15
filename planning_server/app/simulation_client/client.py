"""HTTP client for Planning Server → Simulation Server communication."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from .. import config

# Shared protocol — single source of truth
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.simulation_protocol import SimActionRequest, SimActionResponse

logger = logging.getLogger("osteotwin.sim_client")


class SimulationClient:
    """Async HTTP client to the Simulation Server."""

    def __init__(self) -> None:
        self._base_url = config.SIMULATION_SERVER_URL.rstrip("/")
        self._headers = {"X-API-Key": config.SIM_API_KEY}

    async def health(self) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base_url}/health", timeout=5.0)
            resp.raise_for_status()
            return resp.json()

    async def simulate_action(self, request: SimActionRequest) -> SimActionResponse:
        """Send a SimActionRequest and return the deterministic response."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/simulate/action",
                json=request.model_dump(mode="json"),
                headers=self._headers,
                timeout=30.0,
            )
            resp.raise_for_status()
            return SimActionResponse.model_validate(resp.json())

    async def promote_branch(
        self, source: str, target: str = "main"
    ) -> dict:
        """Promote a hypothesis branch to the user-visible main branch."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/branches/promote",
                params={"source_branch": source, "target_branch": target},
                headers=self._headers,
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_branches(self) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/branches",
                headers=self._headers,
                timeout=5.0,
            )
            resp.raise_for_status()
            return resp.json()


# Module-level singleton
sim_client = SimulationClient()
