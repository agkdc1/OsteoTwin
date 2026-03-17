"""OsteoTwin Planning Server — Port 8200.

Handles user auth, project CRUD, HTMX/Alpine.js web UI,
and the Multi-LLM Orchestrator (Claude primary, Gemini secondary).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .database import init_db
from .graph_db.connection import graph_db

# Routers
from .auth.router import router as auth_router
from .auth.admin_router import router as admin_router
from .pipeline.router import router as pipeline_router
from .graph_db.router import router as knowledge_router
from .web_ui.router import router as web_router
from .voice.router import router as voice_router
from .knowledge_cache.router import router as knowledge_cache_router
from .printer.router import router as printer_router
from .pipeline.sync_router import router as sync_router
from .services.firestore_logger import clinical_logger
from .services.clinical_log_router import router as clinical_log_router

logger = logging.getLogger("osteotwin.planning")

# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown hooks
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(
        "Planning Server starting on %s:%s", config.PLAN_HOST, config.PLAN_PORT
    )
    await init_db()
    await graph_db.connect()
    await clinical_logger.connect()
    yield
    # Shutdown
    from .knowledge_cache.heartbeat import stop_all_heartbeats
    stop_all_heartbeats()
    await clinical_logger.close()
    await graph_db.close()
    logger.info("Planning Server shut down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="OsteoTwin Planning Server",
    version="0.1.0",
    description="AI-driven orthopedic reduction planning with multi-agent debate.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
STATIC_DIR = Path(__file__).parent.parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(pipeline_router)
app.include_router(knowledge_router)
app.include_router(web_router)
app.include_router(voice_router)
app.include_router(knowledge_cache_router)
app.include_router(printer_router)
app.include_router(sync_router)
app.include_router(clinical_log_router)


# ---------------------------------------------------------------------------
# Health & info
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "service": "planning_server", "port": config.PLAN_PORT}


@app.get("/api/info")
async def info():
    return {
        "service": "OsteoTwin Planning Server",
        "version": "0.1.0",
        "docs": "/docs",
        "neo4j": graph_db.available,
        "firestore": clinical_logger.available,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "planning_server.app.main:app",
        host=config.PLAN_HOST,
        port=config.PLAN_PORT,
        reload=True,
    )
