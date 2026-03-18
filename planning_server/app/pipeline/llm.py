"""Unified LLM provider abstraction for Claude (primary) and Gemini (secondary).

Supports both free-form text generation and structured tool/function calling.

Gemini fallback chain on 429 rate limit:
    gemini-2.5-flash -> gemini-2.5-pro -> wait 60s -> retry
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any

from .. import config

logger = logging.getLogger("osteotwin.llm")


class Provider(str, Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"


# Gemini model fallback chain (try in order on 429)
GEMINI_FALLBACK_CHAIN = [
    None,                          # use config.GEMINI_MODEL (default: gemini-3-flash-preview)
    "gemini-3.1-pro-preview",     # fallback 1: latest pro
    "gemini-2.5-pro",             # fallback 2: stable pro
    "gemini-2.5-flash",           # fallback 3: stable flash
]
GEMINI_RATE_LIMIT_WAIT_SEC = 60


# ---------------------------------------------------------------------------
# Text generation
# ---------------------------------------------------------------------------


async def generate_text(
    prompt: str,
    *,
    system: str = "",
    provider: Provider = Provider.CLAUDE,
    max_tokens: int = 4096,
) -> str:
    """Generate free-form text from a prompt."""
    if provider == Provider.CLAUDE:
        return await _claude_text(prompt, system=system, max_tokens=max_tokens)
    else:
        return await _gemini_text_with_fallback(prompt, system=system, max_tokens=max_tokens)


async def _claude_text(prompt: str, *, system: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict[str, Any] = {
        "model": config.CLAUDE_MODEL_FAST,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    for attempt in range(config.CLAUDE_MAX_RETRIES):
        try:
            resp = await client.messages.create(**kwargs)
            return resp.content[0].text
        except Exception as exc:
            logger.warning("Claude text attempt %d failed: %s", attempt + 1, exc)
            if attempt == config.CLAUDE_MAX_RETRIES - 1:
                raise
    return ""


async def _gemini_text_with_fallback(
    prompt: str, *, system: str, max_tokens: int
) -> str:
    """Gemini text generation with model fallback on 429 rate limit.

    Chain: config.GEMINI_MODEL -> gemini-2.5-pro -> gemini-2.0-flash -> wait 60s -> retry all
    """
    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    gen_config = genai.types.GenerateContentConfig(max_output_tokens=max_tokens)

    # Build model list: default first, then fallbacks
    models = [config.GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_CHAIN if m and m != config.GEMINI_MODEL]

    for retry_round in range(2):  # try full chain twice (with wait between)
        for model_id in models:
            try:
                logger.debug("Gemini text: trying %s (round %d)", model_id, retry_round)
                resp = client.models.generate_content(
                    model=model_id,
                    contents=full_prompt,
                    config=gen_config,
                )
                return resp.text or ""
            except Exception as exc:
                exc_str = str(exc)
                if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "rate" in exc_str.lower():
                    logger.warning("Gemini 429 on %s, trying next model...", model_id)
                    continue
                else:
                    raise

        # All models hit rate limit — wait and retry
        if retry_round == 0:
            logger.warning(
                "All Gemini models rate-limited. Waiting %ds before retry...",
                GEMINI_RATE_LIMIT_WAIT_SEC,
            )
            await asyncio.sleep(GEMINI_RATE_LIMIT_WAIT_SEC)

    raise RuntimeError("All Gemini models exhausted after rate-limit retries")


# ---------------------------------------------------------------------------
# Structured tool/function calling
# ---------------------------------------------------------------------------


async def generate_with_tool(
    prompt: str,
    *,
    tool: dict,
    tool_name: str,
    system: str = "",
    provider: Provider = Provider.CLAUDE,
    max_tokens: int = 8192,
) -> dict:
    """Generate structured output using tool/function calling.

    For Gemini, uses model fallback chain on 429.
    """
    if provider == Provider.CLAUDE:
        return await _claude_tool_call(
            prompt, tool=tool, tool_name=tool_name, system=system, max_tokens=max_tokens
        )
    else:
        return await _gemini_tool_call_with_fallback(
            prompt, tool=tool, tool_name=tool_name, system=system, max_tokens=max_tokens
        )


async def _claude_tool_call(
    prompt: str, *, tool: dict, tool_name: str, system: str, max_tokens: int
) -> dict:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": prompt}]

    kwargs: dict[str, Any] = {
        "model": config.CLAUDE_MODEL_FAST,
        "max_tokens": max_tokens,
        "messages": messages,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool_name},
    }
    if system:
        kwargs["system"] = system

    for attempt in range(config.CLAUDE_MAX_RETRIES):
        try:
            resp = await client.messages.create(**kwargs)
            for block in resp.content:
                if block.type == "tool_use" and block.name == tool_name:
                    return block.input
            raise ValueError(f"No tool_use block found for '{tool_name}'")
        except Exception as exc:
            logger.warning("Claude tool attempt %d failed: %s", attempt + 1, exc)
            if attempt == config.CLAUDE_MAX_RETRIES - 1:
                raise
    return {}


async def _gemini_tool_call_with_fallback(
    prompt: str, *, tool: dict, tool_name: str, system: str, max_tokens: int
) -> dict:
    """Gemini structured output with model fallback on 429."""
    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    schema = tool.get("input_schema", {})
    schema_str = json.dumps(schema, indent=2)

    full_prompt = (
        f"{system}\n\n" if system else ""
    ) + (
        f"You must respond with a valid JSON object matching this schema:\n"
        f"```json\n{schema_str}\n```\n\n"
        f"User request:\n{prompt}"
    )

    gen_config = genai.types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
    )

    models = [config.GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_CHAIN if m and m != config.GEMINI_MODEL]

    for retry_round in range(2):
        for model_id in models:
            try:
                logger.debug("Gemini tool: trying %s (round %d)", model_id, retry_round)
                resp = client.models.generate_content(
                    model=model_id,
                    contents=full_prompt,
                    config=gen_config,
                )
                text = resp.text or "{}"
                return json.loads(text)
            except Exception as exc:
                exc_str = str(exc)
                if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "rate" in exc_str.lower():
                    logger.warning("Gemini 429 on %s (tool call), trying next...", model_id)
                    continue
                elif isinstance(exc, json.JSONDecodeError):
                    logger.warning("Gemini returned invalid JSON from %s, trying next...", model_id)
                    continue
                else:
                    raise

        if retry_round == 0:
            logger.warning(
                "All Gemini models rate-limited (tool call). Waiting %ds...",
                GEMINI_RATE_LIMIT_WAIT_SEC,
            )
            await asyncio.sleep(GEMINI_RATE_LIMIT_WAIT_SEC)

    raise RuntimeError("All Gemini models exhausted after rate-limit retries")
