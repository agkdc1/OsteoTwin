"""Voice Agent Orchestrator — Audio → Text → Tool Use → Response → Audio pipeline.

Handles the full lifecycle of a voice interaction:
1. STT: Speech-to-text (Whisper or Google STT)
2. Parse: Extract intent and parameters from transcribed text
3. Tool Use: Call simulation tools if needed
4. Response: Generate clinical response via Claude
5. TTS: Text-to-speech for auditory feedback

Currently supports text-in/text-out for prototyping.
STT/TTS integration is pluggable via the AudioPipeline interface.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import anthropic

from .. import config
from ..simulation_client.client import sim_client
from ..graph_db.connection import graph_db
from ..pipeline.tools import SIMULATE_ACTION_TOOL, CHECK_COLLISION_TOOL
from .prompts import build_voice_system_prompt

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.simulation_protocol import SimActionRequest
from shared.collision_protocol import CollisionCheckRequest

logger = logging.getLogger("osteotwin.voice")

# Additional tool for soft-tissue queries
SOFT_TISSUE_TOOL = {
    "name": "check_soft_tissue",
    "description": (
        "Run a soft-tissue biomechanical simulation to check tissue tensions, "
        "vascular proximity, and periosteal stripping for the current fragment configuration. "
        "Use this when the surgeon asks about tissue tension, nerve proximity, or "
        "whether a reduction will cause excessive soft-tissue strain."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fragment_positions": {
                "type": "object",
                "description": "fragment_id -> [x, y, z] position",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "number"},
                },
            },
            "case_id": {"type": "string"},
            "branch": {"type": "string", "default": "LLM_Hypothesis"},
        },
        "required": ["fragment_positions", "case_id"],
    },
}


class VoiceAgentOrchestrator:
    """Stateful voice agent that maintains conversation context within a case."""

    def __init__(
        self,
        case_id: str,
        surgical_plan: str | None = None,
        ao_code: str | None = None,
    ):
        self.case_id = case_id
        self.surgical_plan = surgical_plan
        self.ao_code = ao_code
        self.system_prompt = build_voice_system_prompt(surgical_plan)
        self.conversation_history: list[dict] = []
        self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

        # 2-Track: Gemini Librarian extracts brief on session start,
        # Claude uses the compact brief for all subsequent queries
        self._brief_xml: str | None = None
        self._system_blocks: list[dict] = []

        # Heartbeat placeholder — started after first query extracts the brief
        from ..knowledge_cache.heartbeat import start_heartbeat
        self._heartbeat_started = False

    async def process_text_query(
        self,
        text: str,
        *,
        max_tool_rounds: int = 3,
    ) -> dict[str, Any]:
        """Process a text query (simulated STT output) and return a clinical response.

        Returns:
            Dict with 'response' (clinical text for TTS), 'tool_calls' (list),
            'simulation_results' (list), and 'processing_time_ms'.
        """
        t0 = time.time()

        # On first query, extract surgical brief via Gemini Librarian
        if not self._brief_xml:
            from ..knowledge_cache.librarian import extract_surgical_brief, build_surgeon_system_with_brief
            from ..knowledge_cache.heartbeat import start_heartbeat

            librarian_result = await extract_surgical_brief(
                query=text, ao_code=self.ao_code,
                surgical_plan=self.surgical_plan,
            )
            self._brief_xml = librarian_result["brief_xml"]
            self._system_blocks = build_surgeon_system_with_brief(self._brief_xml)
            self._system_blocks.append({"type": "text", "text": self.system_prompt})

            # Start heartbeat with the compact brief
            start_heartbeat(f"voice-{self.case_id}", self._system_blocks[:1])
            self._heartbeat_started = True

        # Touch heartbeat — a real query resets the timer
        from ..knowledge_cache.heartbeat import touch_heartbeat
        touch_heartbeat(f"voice-{self.case_id}")

        # Add user message to conversation
        self.conversation_history.append({"role": "user", "content": text})

        tools = [SIMULATE_ACTION_TOOL, CHECK_COLLISION_TOOL, SOFT_TISSUE_TOOL]
        tool_calls_log: list[dict] = []
        sim_results_log: list[dict] = []

        messages = list(self.conversation_history)

        for round_num in range(max_tool_rounds):
            resp = await self._client.messages.create(
                model=config.CLAUDE_MODEL_FAST,
                max_tokens=512,  # Short responses for voice
                system=self._system_blocks,
                messages=messages,
                tools=tools,
            )

            tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
            text_blocks = [b for b in resp.content if b.type == "text"]

            if not tool_use_blocks:
                final_text = " ".join(b.text for b in text_blocks)
                self.conversation_history.append(
                    {"role": "assistant", "content": final_text}
                )
                elapsed = (time.time() - t0) * 1000
                return {
                    "response": final_text,
                    "tool_calls": tool_calls_log,
                    "simulation_results": sim_results_log,
                    "processing_time_ms": round(elapsed, 1),
                }

            # Process tool calls
            tool_results: list[dict] = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                tool_calls_log.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "round": round_num,
                })

                logger.info("Voice tool call [round %d]: %s", round_num, tool_name)

                try:
                    result_dict = await self._execute_tool(
                        tool_name, tool_input
                    )
                except Exception as exc:
                    logger.error("Voice tool call failed: %s", exc)
                    result_dict = {"error": str(exc)}

                sim_results_log.append({
                    "tool": tool_name,
                    "result": result_dict,
                })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result_dict),
                })

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": tool_results})

        # Max rounds hit
        fallback = "I wasn't able to complete the simulation check. Could you rephrase your question?"
        self.conversation_history.append({"role": "assistant", "content": fallback})
        elapsed = (time.time() - t0) * 1000
        return {
            "response": fallback,
            "tool_calls": tool_calls_log,
            "simulation_results": sim_results_log,
            "processing_time_ms": round(elapsed, 1),
        }

    async def _execute_tool(
        self, tool_name: str, tool_input: dict
    ) -> dict:
        """Execute a simulation tool and return the result."""
        import httpx

        if tool_name == "simulate_action":
            tool_input.setdefault("branch", "LLM_Hypothesis")
            tool_input.setdefault("case_id", self.case_id)
            req = SimActionRequest.model_validate(tool_input)
            result = await sim_client.simulate_action(req)
            return result.model_dump(mode="json")

        elif tool_name == "check_collision":
            tool_input.setdefault("branch", "LLM_Hypothesis")
            tool_input.setdefault("case_id", self.case_id)
            req = CollisionCheckRequest.model_validate(tool_input)
            async with httpx.AsyncClient() as http:
                r = await http.post(
                    f"{config.SIMULATION_SERVER_URL}/api/v1/simulate/collision",
                    json=req.model_dump(mode="json"),
                    headers={"X-API-Key": config.SIM_API_KEY},
                    timeout=30.0,
                )
                r.raise_for_status()
                return r.json()

        elif tool_name == "check_soft_tissue":
            tool_input.setdefault("branch", "LLM_Hypothesis")
            tool_input.setdefault("case_id", self.case_id)
            async with httpx.AsyncClient() as http:
                r = await http.post(
                    f"{config.SIMULATION_SERVER_URL}/api/v1/soft-tissue/simulate",
                    json={
                        "request_id": f"voice-{int(time.time())}",
                        "case_id": tool_input["case_id"],
                        "branch": tool_input["branch"],
                        "fragment_positions": tool_input["fragment_positions"],
                    },
                    headers={"X-API-Key": config.SIM_API_KEY},
                    timeout=60.0,
                )
                r.raise_for_status()
                return r.json()

        return {"error": f"Unknown tool: {tool_name}"}

    def reset_conversation(self):
        """Clear conversation history (e.g., between surgical phases)."""
        self.conversation_history.clear()
        from ..knowledge_cache.heartbeat import stop_heartbeat
        stop_heartbeat(f"voice-{self.case_id}")
