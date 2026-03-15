"""Cache Manager — assembles and serves cached prompt blocks.

Builds optimized prompt segments from downloaded reference texts,
organized by body region and topic. Uses Anthropic's prompt caching
API to minimize per-query costs.

Cache architecture:
    [CACHED BLOCK — written once per session, read on every query]
    ├── System prompt + tool definitions (~2K tokens)
    ├── OsteoTwin architecture description (~1K tokens)
    ├── AO Classification reference (~30K tokens)
    ├── Body-region anatomy reference (~20-40K tokens)
    ├── Surgical technique reference (~10-20K tokens)
    ├── Implant specifications (~5K tokens)
    └── Case-specific surgical plan (~2-5K tokens)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .sources import (
    BodyRegion,
    Topic,
    ReferenceSource,
    get_sources_for_region,
    get_sources_by_priority,
    region_from_ao_code,
    SOURCES,
)
from .downloader import get_cached_text, is_cached, CACHE_DIR

logger = logging.getLogger("osteotwin.knowledge_cache.manager")

# Maximum tokens for the cached block (leave room for conversation)
MAX_CACHE_TOKENS = 120000  # ~480K chars (well within Claude's 200K context)


class CacheManager:
    """Manages assembled prompt cache blocks."""

    def __init__(self):
        self._assembled_cache: dict[str, str] = {}  # region_key -> assembled text

    def get_available_sources(self) -> list[dict]:
        """List all sources and their cache status."""
        return [
            {
                "id": s.id,
                "name": s.name,
                "cached": is_cached(s.id),
                "priority": s.priority,
                "regions": [r.value for r in s.regions],
                "topics": [t.value for t in s.topics],
                "estimated_tokens": s.estimated_tokens,
                "actual_tokens": len(get_cached_text(s.id)) // 4
                if is_cached(s.id)
                else 0,
            }
            for s in SOURCES
        ]

    def get_cache_stats(self) -> dict:
        """Get overall cache statistics."""
        total_sources = len(SOURCES)
        cached_sources = sum(1 for s in SOURCES if is_cached(s.id))
        total_tokens = sum(
            len(get_cached_text(s.id)) // 4
            for s in SOURCES
            if is_cached(s.id)
        )
        return {
            "total_sources": total_sources,
            "cached_sources": cached_sources,
            "total_cached_tokens": total_tokens,
            "cache_dir": str(CACHE_DIR),
            "max_cache_tokens": MAX_CACHE_TOKENS,
        }

    def assemble_cached_block(
        self,
        ao_code: Optional[str] = None,
        body_region: Optional[BodyRegion] = None,
        topics: Optional[list[Topic]] = None,
        max_tokens: int = MAX_CACHE_TOKENS,
        include_system_context: bool = True,
    ) -> list[dict]:
        """Assemble a cached prompt block for the Anthropic API.

        Returns a list of content blocks with cache_control markers
        for use in the system prompt.

        Args:
            ao_code: AO classification code to auto-detect region
            body_region: Explicit body region override
            topics: Specific topics to include
            max_tokens: Maximum total tokens
            include_system_context: Include OsteoTwin system description

        Returns:
            List of content blocks for Anthropic messages API:
            [
                {"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}},
                ...
            ]
        """
        # Determine region
        region = body_region
        if not region and ao_code:
            region = region_from_ao_code(ao_code)
        if not region:
            region = BodyRegion.general

        blocks: list[dict] = []
        token_budget = max_tokens
        used_tokens = 0

        # 1. System context (always first — small, always cached)
        if include_system_context:
            system_ctx = self._get_system_context()
            ctx_tokens = len(system_ctx) // 4
            if ctx_tokens <= token_budget:
                blocks.append({
                    "type": "text",
                    "text": system_ctx,
                })
                used_tokens += ctx_tokens

        # 2. Gather relevant sources, sorted by priority
        relevant_sources = self._select_sources(region, topics)

        # 3. Add sources up to token budget
        for source in relevant_sources:
            if not is_cached(source.id):
                continue

            text = get_cached_text(source.id)
            if not text:
                continue

            text_tokens = len(text) // 4
            if used_tokens + text_tokens > token_budget:
                # Try to fit a truncated version
                remaining = token_budget - used_tokens
                if remaining > 2000:  # Worth including partial
                    truncated = text[: remaining * 4]
                    truncated += f"\n\n[... truncated, {text_tokens - remaining} tokens omitted ...]"
                    blocks.append({
                        "type": "text",
                        "text": truncated,
                    })
                    used_tokens = token_budget
                break

            blocks.append({
                "type": "text",
                "text": text,
            })
            used_tokens += text_tokens

        # Mark the last block with cache_control
        if blocks:
            blocks[-1]["cache_control"] = {"type": "ephemeral"}

        logger.info(
            "Assembled cache block: %d sources, ~%d tokens (region=%s)",
            len(blocks),
            used_tokens,
            region.value,
        )

        return blocks

    def _select_sources(
        self,
        region: BodyRegion,
        topics: Optional[list[Topic]] = None,
    ) -> list[ReferenceSource]:
        """Select and prioritize sources for a given region and topics."""
        # Always include priority 1 (core references)
        core = [s for s in SOURCES if s.priority == 1]

        # Add region-specific sources
        regional = get_sources_for_region(region)

        # Merge, deduplicate, sort by priority
        seen = set()
        merged = []
        for s in core + regional:
            if s.id not in seen:
                seen.add(s.id)
                merged.append(s)

        # Filter by topics if specified
        if topics:
            topic_set = set(topics)
            merged = [
                s for s in merged
                if s.priority == 1 or any(t in topic_set for t in s.topics)
            ]

        return sorted(merged, key=lambda s: s.priority)

    def _get_system_context(self) -> str:
        """OsteoTwin system context for the cached block."""
        return """## OsteoTwin System Context

OsteoTwin is an AI-driven orthopedic surgical planning simulator. You are the surgical planning AI.

### Architecture
- Planning Server (:8200): LLM orchestration, auth, voice assistant
- Simulation Server (:8300): Deterministic physics (Trimesh collision, SOFA soft-tissue)
- Neo4j: Anatomical rule engine with surgeon-validated corrections

### Strict Rules
1. NEVER predict, imagine, or guess physics outcomes — always call simulation tools
2. Operate on Branch "LLM_Hypothesis" — never modify "main" without surgeon approval
3. Respect all surgeon-validated anatomical rules from the Knowledge Graph
4. Use AO/OTA classification codes consistently

### Available Simulation Tools
- simulate_action: Move bone fragments, get collision + tension results
- check_collision: K-wire/implant trajectory ray casting
- check_soft_tissue: Tissue tension, vascular proximity, periosteal stripping

### Reference Material
The following sections contain open access orthopedic reference texts.
Use these as your primary knowledge source — they are authoritative and peer-reviewed.
When your training knowledge conflicts with these references, prefer the reference texts.
"""


# Singleton
cache_manager = CacheManager()
