"""Simulation Server configuration — loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ENV_PATH)

# --- Auth ---
SIM_API_KEY: str = os.getenv("SIM_API_KEY", "")

# --- Server ---
SIM_HOST: str = os.getenv("SIM_HOST", "0.0.0.0")
SIM_PORT: int = int(os.getenv("SIM_PORT", "8300"))

# --- Paths ---
JOBS_DIR: Path = Path(__file__).resolve().parent.parent / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

MESH_CACHE_DIR: Path = Path(__file__).resolve().parent.parent / "mesh_cache"
MESH_CACHE_DIR.mkdir(exist_ok=True)
