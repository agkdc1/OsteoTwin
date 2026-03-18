"""Planning Server configuration — loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ENV_PATH)

# --- LLM ---
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
CLAUDE_MODEL_FAST: str = os.getenv("CLAUDE_MODEL_FAST", "claude-sonnet-4-20250514")
CLAUDE_MODEL_SMART: str = os.getenv("CLAUDE_MODEL_SMART", "claude-sonnet-4-20250514")
CLAUDE_MAX_RETRIES: int = int(os.getenv("CLAUDE_MAX_RETRIES", "3"))
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3-flash")

# --- JWT / Auth ---
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin")

# --- Inter-Service ---
SIM_API_KEY: str = os.getenv("SIM_API_KEY", "")
SIMULATION_SERVER_URL: str = os.getenv("SIMULATION_SERVER_URL", "http://localhost:8300")

# --- Server ---
PLAN_HOST: str = os.getenv("PLAN_HOST", "0.0.0.0")
PLAN_PORT: int = int(os.getenv("PLAN_PORT", "8200"))

# --- Neo4j Graph DB ---
NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")

# --- GCP ---
GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")

# --- Database ---
_DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent / "data"
_DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "osteotwin.db"
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH}"
)
