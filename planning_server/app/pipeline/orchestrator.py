"""Surgical planning orchestrator — coordinates LLM + Simulation Server.

The orchestrator:
1. Receives natural-language surgical queries
2. Calls Claude with simulation tools bound
3. Executes tool calls against the Simulation Server
4. Returns deterministic results translated into clinical advice
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import anthropic

from .. import config
from ..simulation_client.client import sim_client
from ..graph_db.connection import graph_db
from .tools import (
    SIMULATE_ACTION_TOOL,
    CHECK_COLLISION_TOOL,
    SURGICAL_AGENT_SYSTEM_PROMPT,
)

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.simulation_protocol import SimActionRequest
from shared.collision_protocol import CollisionCheckRequest

logger = logging.getLogger("osteotwin.orchestrator")


async def run_surgical_query(
    query: str,
    case_id: str,
    *,
    ao_code: Optional[str] = None,
    max_tool_rounds: int = 5,
) -> dict[str, Any]:
    """Execute a surgical planning query with tool-use loop.

    The LLM can call simulation tools multiple times in a single query
    (e.g., try a K-wire, check collision, adjust, retry).

    Returns:
        Dict with 'response' (clinical text), 'tool_calls' (list of calls made),
        and 'simulation_results' (list of deterministic results).
    """
    # Pre-fetch anatomical rules from Knowledge Graph
    context_rules: list[dict] = []
    if ao_code and graph_db.available:
        # Extract body region from AO code (e.g., "23" → "distal_radius")
        context_rules = await graph_db.get_anatomical_rules(ao_code)

    rules_context = ""
    if context_rules:
        rules_text = "\n".join(
            f"- {r['description']} (source: {r.get('source', 'unknown')})"
            for r in context_rules
        )
        rules_context = (
            f"\n\n## Previously Established Anatomical Rules\n{rules_text}\n"
            "You MUST respect these rules — they are surgeon-validated corrections.\n"
        )

    # ---------------------------------------------------------------
    # 2-Track Pipeline: Gemini Librarian -> Claude Surgeon
    # Track 1: Gemini extracts a surgical brief from the full KB
    # Track 2: Claude reasons with the compact brief + simulation tools
    # ---------------------------------------------------------------
    from ..knowledge_cache.librarian import extract_surgical_brief, build_surgeon_system_with_brief
    from ..knowledge_cache.heartbeat import start_heartbeat, touch_heartbeat

    librarian_result = await extract_surgical_brief(
        query=query, ao_code=ao_code,
    )
    brief_xml = librarian_result["brief_xml"]

    # Build Claude's system prompt with the extracted brief (cached)
    system_blocks = build_surgeon_system_with_brief(brief_xml)

    # Append rules and surgical system prompt (not cached — changes per query)
    system_blocks.append({
        "type": "text",
        "text": SURGICAL_AGENT_SYSTEM_PROMPT + rules_context,
    })

    # Start/touch cache heartbeat to keep cache alive during idle periods
    start_heartbeat(f"plan-{case_id}", system_blocks[:1])
    touch_heartbeat(f"plan-{case_id}")

    # Build conversation
    messages: list[dict] = [{"role": "user", "content": query}]
    tools = [SIMULATE_ACTION_TOOL, CHECK_COLLISION_TOOL]
    tool_calls_log: list[dict] = []
    sim_results_log: list[dict] = []

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    for round_num in range(max_tool_rounds):
        resp = await client.messages.create(
            model=config.CLAUDE_MODEL_FAST,
            max_tokens=4096,
            system=system_blocks,
            messages=messages,
            tools=tools,
        )

        # Check if the model wants to use tools
        tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
        text_blocks = [b for b in resp.content if b.type == "text"]

        if not tool_use_blocks:
            # No more tool calls — return the final text
            final_text = " ".join(b.text for b in text_blocks)
            return {
                "response": final_text,
                "tool_calls": tool_calls_log,
                "simulation_results": sim_results_log,
            }

        # Process each tool call
        tool_results: list[dict] = []
        for block in resp.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            tool_calls_log.append({"tool": tool_name, "input": tool_input, "round": round_num})

            logger.info("Tool call [round %d]: %s", round_num, tool_name)

            try:
                if tool_name == "simulate_action":
                    # Ensure we're on the hypothesis branch
                    tool_input.setdefault("branch", "LLM_Hypothesis")
                    tool_input.setdefault("case_id", case_id)
                    req = SimActionRequest.model_validate(tool_input)
                    result = await sim_client.simulate_action(req)
                    result_dict = result.model_dump(mode="json")

                elif tool_name == "check_collision":
                    tool_input.setdefault("branch", "LLM_Hypothesis")
                    tool_input.setdefault("case_id", case_id)
                    req = CollisionCheckRequest.model_validate(tool_input)
                    # Call collision endpoint
                    import httpx

                    async with httpx.AsyncClient() as http:
                        r = await http.post(
                            f"{config.SIMULATION_SERVER_URL}/api/v1/simulate/collision",
                            json=req.model_dump(mode="json"),
                            headers={"X-API-Key": config.SIM_API_KEY},
                            timeout=30.0,
                        )
                        r.raise_for_status()
                        result_dict = r.json()
                else:
                    result_dict = {"error": f"Unknown tool: {tool_name}"}

                sim_results_log.append({"tool": tool_name, "result": result_dict})

            except Exception as exc:
                logger.error("Tool call failed: %s", exc)
                result_dict = {"error": str(exc)}

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result_dict),
            })

        # Add assistant message (with tool_use blocks) and tool results
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": tool_results})

    # Hit max rounds
    return {
        "response": "Maximum simulation rounds reached. Please refine your query.",
        "tool_calls": tool_calls_log,
        "simulation_results": sim_results_log,
    }
