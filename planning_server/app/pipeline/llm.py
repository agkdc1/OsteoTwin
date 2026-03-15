"""Unified LLM provider abstraction for Claude (primary) and Gemini (secondary).

Supports both free-form text generation and structured tool/function calling.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

from .. import config

logger = logging.getLogger("osteotwin.llm")


class Provider(str, Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"


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
        return await _gemini_text(prompt, system=system, max_tokens=max_tokens)


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


async def _gemini_text(prompt: str, *, system: str, max_tokens: int) -> str:
    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=full_prompt,
        config=genai.types.GenerateContentConfig(max_output_tokens=max_tokens),
    )
    return resp.text or ""


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

    Args:
        prompt: User prompt.
        tool: Tool definition dict with 'name', 'description', 'input_schema'.
        tool_name: Name of the tool to force.
        system: System prompt.
        provider: LLM provider.
        max_tokens: Maximum output tokens.

    Returns:
        Parsed tool input dict.
    """
    if provider == Provider.CLAUDE:
        return await _claude_tool_call(
            prompt, tool=tool, tool_name=tool_name, system=system, max_tokens=max_tokens
        )
    else:
        return await _gemini_tool_call(
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


async def _gemini_tool_call(
    prompt: str, *, tool: dict, tool_name: str, system: str, max_tokens: int
) -> dict:
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

    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=full_prompt,
        config=genai.types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        ),
    )
    text = resp.text or "{}"
    return json.loads(text)
