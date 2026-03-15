"""Multi-Agent Debate: Claude vs Gemini surgical plan cross-validation.

The "Surgical Council" — two AI agents debate reduction strategies,
each plan is validated against the deterministic simulation engine.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .llm import Provider, generate_text, generate_with_tool
from ..simulation_client.client import sim_client
from ..graph_db.connection import graph_db

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.schemas import AgentDebate, AgentResponse, SurgicalPlan, DebateRound
from shared.schemas.agent_debate import AgentRole, RiskLevel

logger = logging.getLogger("osteotwin.debate")

# ---------------------------------------------------------------------------
# Tool definition for structured plan output
# ---------------------------------------------------------------------------

SURGICAL_PLAN_TOOL = {
    "name": "surgical_plan",
    "description": "Propose one or more surgical reduction plans for the given fracture case.",
    "input_schema": {
        "type": "object",
        "properties": {
            "plans": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "plan_label": {"type": "string"},
                        "approach": {"type": "string"},
                        "reduction_sequence": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "hardware_recommendation": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "estimated_risk": {
                            "type": "string",
                            "enum": ["low", "moderate", "high", "critical"],
                        },
                        "risk_justification": {"type": "string"},
                    },
                    "required": [
                        "plan_label",
                        "approach",
                        "reduction_sequence",
                        "estimated_risk",
                        "risk_justification",
                    ],
                },
            },
            "critique_of_other": {"type": "string"},
            "consensus_notes": {"type": "string"},
            "dissent_notes": {"type": "string"},
        },
        "required": ["plans"],
    },
}


# ---------------------------------------------------------------------------
# Debate prompts
# ---------------------------------------------------------------------------

PRIMARY_SYSTEM = """You are the PRIMARY surgical planning agent (Claude).
You are an expert orthopedic surgeon specializing in fracture reduction.
You must propose concrete, actionable surgical plans (Plan A, B, C) with specific:
- Surgical approach (e.g., volar, dorsal, lateral)
- Step-by-step reduction sequence
- Hardware recommendations (plate type, screw sizes, K-wire diameters)
- Risk assessment with justification

If this is Round 2+, you will also receive the SECONDARY agent's plans.
You must critique their plans and note areas of agreement and disagreement.
Be rigorous — patient safety is paramount."""

SECONDARY_SYSTEM = """You are the SECONDARY surgical planning agent (Gemini).
You are an expert orthopedic surgeon providing an independent second opinion.
You must propose your own surgical plans that may differ from the PRIMARY agent.
Your role is to:
- Challenge assumptions in the PRIMARY agent's plans
- Identify risks the PRIMARY agent may have missed
- Propose alternative approaches when you see merit
- Concur explicitly when you agree (consensus strengthens the recommendation)

Be constructively adversarial — your disagreements help find the safest plan."""


# ---------------------------------------------------------------------------
# Debate engine
# ---------------------------------------------------------------------------


async def run_debate(
    case_summary: str,
    case_id: str,
    *,
    ao_code: Optional[str] = None,
    max_rounds: int = 3,
) -> AgentDebate:
    """Run a multi-round Claude vs Gemini debate on a fracture case.

    Args:
        case_summary: Clinical description of the fracture case.
        case_id: FractureCase ID.
        ao_code: AO classification code for knowledge graph lookup.
        max_rounds: Maximum debate rounds (default 3).

    Returns:
        Complete AgentDebate with all rounds and selected plan.
    """
    # Pre-fetch knowledge graph context
    kg_context = ""
    if ao_code and graph_db.available:
        rules = await graph_db.get_anatomical_rules(ao_code)
        past_cases = await graph_db.get_past_case_context(ao_code)
        if rules:
            kg_context += "\n\nPreviously validated anatomical rules:\n"
            kg_context += "\n".join(f"- {r['description']}" for r in rules)
        if past_cases:
            kg_context += "\n\nPast case outcomes for similar fractures:\n"
            kg_context += "\n".join(
                f"- {c['ao_code']}: {c['outcome']} (success={c['success']})"
                for c in past_cases
            )

    debate = AgentDebate(case_id=case_id, max_rounds=max_rounds, status="in_progress")
    rounds: list[DebateRound] = []
    primary_history = ""
    secondary_history = ""

    for round_num in range(1, max_rounds + 1):
        logger.info("Debate round %d/%d for case %s", round_num, max_rounds, case_id)

        # Build round-specific prompts
        if round_num == 1:
            primary_prompt = (
                f"Fracture case:\n{case_summary}{kg_context}\n\n"
                "Propose 2-3 surgical reduction plans (Plan A, B, C)."
            )
            secondary_prompt = primary_prompt
        else:
            primary_prompt = (
                f"Fracture case:\n{case_summary}{kg_context}\n\n"
                f"Previous rounds:\n{secondary_history}\n\n"
                "Review the SECONDARY agent's plans. Critique them, note agreements, "
                "and refine your own plans if needed."
            )
            secondary_prompt = (
                f"Fracture case:\n{case_summary}{kg_context}\n\n"
                f"Previous rounds:\n{primary_history}\n\n"
                "Review the PRIMARY agent's plans. Critique them, note agreements, "
                "and refine your own plans if needed."
            )

        # Run both agents
        primary_result = await generate_with_tool(
            primary_prompt,
            tool=SURGICAL_PLAN_TOOL,
            tool_name="surgical_plan",
            system=PRIMARY_SYSTEM,
            provider=Provider.CLAUDE,
        )

        secondary_result = await generate_with_tool(
            secondary_prompt,
            tool=SURGICAL_PLAN_TOOL,
            tool_name="surgical_plan",
            system=SECONDARY_SYSTEM,
            provider=Provider.GEMINI,
        )

        # Parse responses into schema
        primary_plans = [
            SurgicalPlan(
                plan_label=p.get("plan_label", f"Plan {chr(65+i)}"),
                approach=p.get("approach", ""),
                reduction_sequence=p.get("reduction_sequence", []),
                hardware_recommendation=p.get("hardware_recommendation", []),
                estimated_risk=RiskLevel(p.get("estimated_risk", "moderate")),
                risk_justification=p.get("risk_justification", ""),
            )
            for i, p in enumerate(primary_result.get("plans", []))
        ]

        secondary_plans = [
            SurgicalPlan(
                plan_label=p.get("plan_label", f"Plan {chr(65+i)}"),
                approach=p.get("approach", ""),
                reduction_sequence=p.get("reduction_sequence", []),
                hardware_recommendation=p.get("hardware_recommendation", []),
                estimated_risk=RiskLevel(p.get("estimated_risk", "moderate")),
                risk_justification=p.get("risk_justification", ""),
            )
            for i, p in enumerate(secondary_result.get("plans", []))
        ]

        primary_response = AgentResponse(
            agent=AgentRole.PRIMARY,
            model_id=config.CLAUDE_MODEL_SMART,
            proposed_plans=primary_plans,
            critique_of_other=primary_result.get("critique_of_other"),
            consensus_notes=primary_result.get("consensus_notes"),
            dissent_notes=primary_result.get("dissent_notes"),
        )

        secondary_response = AgentResponse(
            agent=AgentRole.SECONDARY,
            model_id=config.GEMINI_MODEL,
            proposed_plans=secondary_plans,
            critique_of_other=secondary_result.get("critique_of_other"),
            consensus_notes=secondary_result.get("consensus_notes"),
            dissent_notes=secondary_result.get("dissent_notes"),
        )

        debate_round = DebateRound(
            round_number=round_num,
            primary_response=primary_response,
            secondary_response=secondary_response,
        )
        rounds.append(debate_round)

        # Update history for next round
        primary_history += f"\n--- Round {round_num} (PRIMARY) ---\n"
        for p in primary_plans:
            primary_history += f"{p.plan_label}: {p.approach} (risk: {p.estimated_risk})\n"

        secondary_history += f"\n--- Round {round_num} (SECONDARY) ---\n"
        for p in secondary_plans:
            secondary_history += f"{p.plan_label}: {p.approach} (risk: {p.estimated_risk})\n"

        # Check for early consensus
        if round_num >= 2:
            if primary_result.get("consensus_notes") and secondary_result.get("consensus_notes"):
                logger.info("Consensus reached at round %d", round_num)
                break

    debate.rounds = rounds
    debate.status = "consensus" if len(rounds) < max_rounds else "dissent"

    # Select the best plan (lowest risk from primary agent's final round)
    if rounds:
        final_plans = rounds[-1].primary_response.proposed_plans
        if final_plans:
            best = min(
                final_plans,
                key=lambda p: ["low", "moderate", "high", "critical"].index(p.estimated_risk.value),
            )
            debate.selected_plan = best

    return debate
