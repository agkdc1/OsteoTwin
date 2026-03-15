"""Knowledge Cache API endpoints — manage reference text downloads and caching."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel, Field

from ..auth.dependencies import get_current_user
from .sources import SOURCES, BodyRegion, get_sources_by_priority
from .downloader import (
    download_all_sources,
    download_source,
    backup_to_gcs,
    restore_from_gcs,
    is_cached,
)
from .cache_manager import cache_manager

logger = logging.getLogger("osteotwin.knowledge_cache.router")

router = APIRouter(
    prefix="/api/v1/knowledge-cache",
    tags=["knowledge-cache"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/status")
async def cache_status():
    """Get knowledge cache statistics and source availability."""
    stats = cache_manager.get_cache_stats()
    sources = cache_manager.get_available_sources()
    return {"stats": stats, "sources": sources}


@router.post("/download")
async def download_sources(
    background_tasks: BackgroundTasks,
    source_ids: Optional[list[str]] = None,
    max_priority: int = 3,
    force: bool = False,
):
    """Download reference sources (runs in background).

    If source_ids is provided, downloads those specific sources.
    Otherwise downloads all sources up to max_priority level.
    """
    if source_ids:
        sources = [s for s in SOURCES if s.id in source_ids]
    else:
        sources = get_sources_by_priority(max_priority)

    not_cached = [s for s in sources if force or not is_cached(s.id)]

    if not not_cached:
        return {
            "status": "all_cached",
            "message": f"All {len(sources)} sources already cached",
        }

    # Run downloads in background
    background_tasks.add_task(_run_downloads, not_cached, force)

    return {
        "status": "downloading",
        "queued": len(not_cached),
        "already_cached": len(sources) - len(not_cached),
        "source_ids": [s.id for s in not_cached],
    }


async def _run_downloads(sources: list, force: bool):
    """Background task to download sources."""
    results = await download_all_sources(sources, force=force)
    logger.info("Download complete: %s", results)

    # Auto-backup to GCS after download
    backup_count = backup_to_gcs()
    logger.info("Backed up %d files to GCS", backup_count)


@router.post("/backup")
async def backup_cache():
    """Backup knowledge cache to GCS."""
    count = backup_to_gcs()
    return {"backed_up": count, "status": "ok" if count > 0 else "failed"}


@router.post("/restore")
async def restore_cache():
    """Restore knowledge cache from GCS."""
    count = restore_from_gcs()
    return {"restored": count, "status": "ok" if count > 0 else "failed"}


class AssembleCacheRequest(BaseModel):
    ao_code: Optional[str] = Field(None, description="AO classification code")
    body_region: Optional[str] = Field(None, description="Body region override")
    max_tokens: int = Field(120000, description="Maximum cache tokens")


@router.post("/assemble")
async def assemble_cache(req: AssembleCacheRequest):
    """Preview the assembled cache block for a given case."""
    region = None
    if req.body_region:
        try:
            region = BodyRegion(req.body_region)
        except ValueError:
            pass

    blocks = cache_manager.assemble_cached_block(
        ao_code=req.ao_code,
        body_region=region,
        max_tokens=req.max_tokens,
    )

    total_tokens = sum(len(b["text"]) // 4 for b in blocks)

    return {
        "block_count": len(blocks),
        "total_tokens": total_tokens,
        "has_cache_control": any("cache_control" in b for b in blocks),
        "blocks_preview": [
            {
                "index": i,
                "tokens": len(b["text"]) // 4,
                "preview": b["text"][:200] + "...",
                "cached": "cache_control" in b,
            }
            for i, b in enumerate(blocks)
        ],
    }
