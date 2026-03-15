"""Cache heartbeat — keeps Anthropic prompt cache alive during idle periods.

Anthropic's prompt cache has a 5-minute TTL. If no request uses the cached
content within that window, it expires and the next request pays the full
cache write cost again (~$0.38 for 100K tokens).

During a surgical planning session, the surgeon may go 5-15 minutes between
queries (thinking, operating, discussing with staff). The heartbeat sends a
minimal "ping" request every ~4 minutes to keep the cache warm.

Cost of heartbeat: ~$0.0003 per ping (tiny input + 1-token output).
Cost of cache miss: ~$0.38 per re-write. Breakeven after 1 miss avoided.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import anthropic

from .. import config
from .cache_manager import cache_manager

logger = logging.getLogger("osteotwin.knowledge_cache.heartbeat")

# Heartbeat interval (seconds) — must be < 5min TTL
HEARTBEAT_INTERVAL = 240  # 4 minutes

# Minimal prompt that triggers a cache read without meaningful computation
HEARTBEAT_PROMPT = "ping"
HEARTBEAT_MAX_TOKENS = 1


class CacheHeartbeat:
    """Keeps prompt cache alive by sending periodic minimal requests.

    One heartbeat instance per active session (case_id).
    Starts automatically when a session begins, stops when the session
    ends or the server shuts down.
    """

    def __init__(
        self,
        session_id: str,
        cached_blocks: list[dict],
        interval: int = HEARTBEAT_INTERVAL,
    ):
        self.session_id = session_id
        self._cached_blocks = cached_blocks
        self._interval = interval
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_ping: float = 0
        self._ping_count: int = 0
        self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    def start(self) -> None:
        """Start the heartbeat background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Cache heartbeat started for session '%s' (every %ds)", self.session_id, self._interval)

    def stop(self) -> None:
        """Stop the heartbeat."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info(
            "Cache heartbeat stopped for session '%s' (%d pings sent)",
            self.session_id, self._ping_count,
        )

    def touch(self) -> None:
        """Record that a real query just used the cache (resets the timer).

        Call this from the orchestrator/voice agent after every real query
        so we don't send a heartbeat immediately after a real request.
        """
        self._last_ping = time.time()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            "session_id": self.session_id,
            "running": self._running,
            "ping_count": self._ping_count,
            "interval_seconds": self._interval,
            "last_ping_ago": round(time.time() - self._last_ping, 1) if self._last_ping else None,
        }

    async def _heartbeat_loop(self) -> None:
        """Background loop that pings the API to keep the cache alive."""
        self._last_ping = time.time()

        while self._running:
            try:
                # Sleep until next heartbeat
                await asyncio.sleep(self._interval)

                if not self._running:
                    break

                # Check if a real query was sent recently (within interval)
                elapsed = time.time() - self._last_ping
                if elapsed < self._interval:
                    # A real query already refreshed the cache — skip this ping
                    continue

                # Send minimal request to keep cache alive
                await self._ping()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Heartbeat error for '%s': %s", self.session_id, exc)
                # Don't crash the loop on transient errors
                await asyncio.sleep(10)

    async def _ping(self) -> None:
        """Send a minimal API request using the cached blocks."""
        try:
            await self._client.messages.create(
                model=config.CLAUDE_MODEL_FAST,
                max_tokens=HEARTBEAT_MAX_TOKENS,
                system=self._cached_blocks,
                messages=[{"role": "user", "content": HEARTBEAT_PROMPT}],
            )
            self._last_ping = time.time()
            self._ping_count += 1
            logger.debug(
                "Cache heartbeat ping #%d for session '%s'",
                self._ping_count, self.session_id,
            )
        except Exception as exc:
            logger.warning("Heartbeat ping failed for '%s': %s", self.session_id, exc)


# ---------------------------------------------------------------------------
# Session-level heartbeat manager
# ---------------------------------------------------------------------------

_heartbeats: dict[str, CacheHeartbeat] = {}


def start_heartbeat(
    session_id: str,
    cached_blocks: list[dict],
    interval: int = HEARTBEAT_INTERVAL,
) -> CacheHeartbeat:
    """Start or restart a heartbeat for a session."""
    # Stop existing heartbeat if any
    if session_id in _heartbeats:
        _heartbeats[session_id].stop()

    hb = CacheHeartbeat(session_id, cached_blocks, interval)
    _heartbeats[session_id] = hb
    hb.start()
    return hb


def stop_heartbeat(session_id: str) -> None:
    """Stop the heartbeat for a session."""
    if session_id in _heartbeats:
        _heartbeats[session_id].stop()
        del _heartbeats[session_id]


def touch_heartbeat(session_id: str) -> None:
    """Record a real query for a session (resets heartbeat timer)."""
    if session_id in _heartbeats:
        _heartbeats[session_id].touch()


def get_all_heartbeats() -> list[dict]:
    """Get stats for all active heartbeats."""
    return [hb.stats for hb in _heartbeats.values()]


def stop_all_heartbeats() -> None:
    """Stop all heartbeats (called on server shutdown)."""
    for hb in _heartbeats.values():
        hb.stop()
    _heartbeats.clear()
