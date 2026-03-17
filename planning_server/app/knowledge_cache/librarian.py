"""Gemini Pro Librarian Agent — extracts surgical briefs from the knowledge base.

Architecture (2-Track Prompt Caching):
    Track 1: Gemini Pro (cheap, fast, large context)
        - Receives the FULL knowledge base (~200K+ tokens) as context
        - Extracts a concise surgical brief (<20K tokens) in XML format
        - Focuses on: anatomy, approaches, danger zones, biomechanical rules

    Track 2: Claude (expensive, precise, tool-use)
        - Receives the compact surgical brief as cached context (~5-20K tokens)
        - Performs tool-use reasoning with simulation tools
        - Generates the final clinical response

Why this architecture?
    - Gemini Flash is ~40x cheaper than Claude for input tokens
    - Gemini handles the brute-force knowledge extraction (cheap)
    - Claude handles the precise reasoning + tool-use (expensive but small context)
    - Cache the brief on Claude's side: ~5-20K tokens vs ~100K+ raw text
    - Net cost reduction: ~90% vs caching raw text on Claude directly
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import google.genai as genai

from .. import config
from .cache_manager import cache_manager
from .downloader import get_cached_text, is_cached
from .sources import SOURCES, region_from_ao_code, get_sources_for_region, BodyRegion

logger = logging.getLogger("osteotwin.knowledge_cache.librarian")

LIBRARIAN_SYSTEM_PROMPT = """\
You are the OsteoTwin Clinical Librarian. Your role is to analyze the provided \
surgical knowledge base and extract the most critical technical data required \
for the Lead Surgeon AI to make immediate clinical decisions.

STRICT CONSTRAINTS:
1. TOKEN LIMIT: Your output must be concise and strictly under 20,000 tokens.
2. CLINICAL PRIORITY: Prioritize in this order:
   a) Nerve/vessel proximity warnings and danger zones
   b) Anatomical landmarks for the specific surgical approach
   c) Biomechanical stability rules (acceptable angles, distances)
   d) Step-by-step surgical technique with pitfall warnings
3. FORMAT: Output ONLY valid XML tags as defined below. No markdown, no commentary.
4. LANGUAGE: Match the language of the surgeon's query for clinical terms, \
   but use standard anatomical terminology (Latin/English) for structure names.
5. SOURCE CITATION (CRITICAL): Every extracted fact MUST include a source \
   attribution tag: <source>AO Manual: Distal Radius, Section 3.2</source> \
   or <source>OpenStax Anatomy Ch.8</source>. The downstream Lead Surgeon AI \
   relies on these citations to avoid hallucination. Do NOT include any \
   information that is not present in the provided knowledge base text.

OUTPUT STRUCTURE:
<surgical_brief>
  <clinical_context_sync>
    <!-- Current case: fracture type, AO classification, patient factors -->
  </clinical_context_sync>

  <relevant_anatomy>
    <!-- Key anatomical structures in the operative field -->
    <!-- Nerve courses, vessel paths, muscle attachments -->
    <!-- Organized by surgical layer (superficial to deep) -->
    <!-- Each fact MUST include <source>...</source> tag -->
  </relevant_anatomy>

  <surgical_manual_extract>
    <!-- Step-by-step technique for the specific approach -->
    <!-- Key landmarks at each step -->
    <!-- Tips and pearls -->
    <!-- Each step MUST include <source>...</source> tag -->
  </surgical_manual_extract>

  <biomechanical_rules>
    <!-- Acceptable reduction parameters (angles, distances) -->
    <!-- Implant positioning rules -->
    <!-- Stability criteria -->
    <!-- Each rule MUST include <source>...</source> tag -->
  </biomechanical_rules>

  <critical_warnings>
    <!-- Structures at risk at each surgical step -->
    <!-- Distance thresholds for nerve/vessel safety -->
    <!-- Common pitfalls and how to avoid them -->
    <!-- Each warning MUST include <source>...</source> tag -->
  </critical_warnings>
</surgical_brief>
"""


async def extract_surgical_brief(
    query: str,
    ao_code: Optional[str] = None,
    body_region: Optional[BodyRegion] = None,
    surgical_plan: Optional[str] = None,
) -> dict:
    """Use Gemini to extract a surgical brief from the full knowledge base.

    Args:
        query: The surgeon's question/situation
        ao_code: AO classification code (e.g., "23-A2")
        body_region: Override body region
        surgical_plan: Current surgical plan context

    Returns:
        Dict with 'brief_xml' (the extracted brief), 'tokens_in', 'tokens_out',
        'processing_time_ms', and 'sources_used'.
    """
    t0 = time.time()

    # Determine region
    region = body_region
    if not region and ao_code:
        region = region_from_ao_code(ao_code)
    if not region:
        region = BodyRegion.general

    # Gather all relevant cached texts
    relevant_sources = get_sources_for_region(region)
    knowledge_texts = []
    sources_used = []

    for source in relevant_sources:
        if is_cached(source.id):
            text = get_cached_text(source.id)
            if text and len(text) > 100:
                knowledge_texts.append(text)
                sources_used.append(source.id)

    if not knowledge_texts:
        logger.warning("No cached knowledge available for region %s", region.value)
        return {
            "brief_xml": "<surgical_brief><critical_warnings>No knowledge base loaded for this region. Download sources first via /api/v1/knowledge-cache/download</critical_warnings></surgical_brief>",
            "tokens_in": 0,
            "tokens_out": 0,
            "processing_time_ms": 0,
            "sources_used": [],
        }

    # Cap total knowledge at ~200K tokens (Gemini free tier limit is 250K/min)
    MAX_KNOWLEDGE_TOKENS = 200000
    capped_texts = []
    running_tokens = 0
    for text in knowledge_texts:
        text_tokens = len(text) // 4
        if running_tokens + text_tokens > MAX_KNOWLEDGE_TOKENS:
            remaining = MAX_KNOWLEDGE_TOKENS - running_tokens
            if remaining > 1000:
                capped_texts.append(text[:remaining * 4])
            break
        capped_texts.append(text)
        running_tokens += text_tokens
    knowledge_texts = capped_texts

    # Build the full context for Gemini
    full_knowledge = "\n\n" + "=" * 80 + "\n\n".join(knowledge_texts)

    # Build the prompt
    context_parts = []
    if ao_code:
        context_parts.append(f"AO Classification: {ao_code}")
    if surgical_plan:
        context_parts.append(f"Current Surgical Plan:\n{surgical_plan}")
    context_parts.append(f"Body Region: {region.value}")
    context_str = "\n".join(context_parts)

    user_prompt = f"""CURRENT OPERATIVE SITUATION:
{context_str}

SURGEON'S QUERY:
{query}

FULL SURGICAL KNOWLEDGE BASE:
{full_knowledge}

Based on the above knowledge base, extract a surgical brief that directly addresses the surgeon's query. Focus on the specific anatomy, approach, and dangers relevant to this exact question."""

    # Call Gemini with retry on rate limit
    import asyncio as _asyncio

    try:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = None

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=config.GEMINI_MODEL,
                    contents=user_prompt,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=LIBRARIAN_SYSTEM_PROMPT,
                        max_output_tokens=8192,
                        temperature=0.1,
                    ),
                )
                break  # Success
            except Exception as retry_exc:
                if "429" in str(retry_exc) and attempt < 2:
                    wait = (attempt + 1) * 30
                    logger.warning("Gemini rate limited, retrying in %ds...", wait)
                    await _asyncio.sleep(wait)
                else:
                    raise

        brief_xml = response.text
        elapsed = (time.time() - t0) * 1000

        # Extract token counts if available
        tokens_in = 0
        tokens_out = 0
        if hasattr(response, 'usage_metadata'):
            tokens_in = getattr(response.usage_metadata, 'prompt_token_count', 0)
            tokens_out = getattr(response.usage_metadata, 'candidates_token_count', 0)

        logger.info(
            "Librarian extracted brief: %d chars, %d sources, %.0fms",
            len(brief_xml), len(sources_used), elapsed,
        )

        return {
            "brief_xml": brief_xml,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "processing_time_ms": round(elapsed, 1),
            "sources_used": sources_used,
            "region": region.value,
        }

    except Exception as exc:
        logger.error("Gemini Librarian failed: %s", exc)
        elapsed = (time.time() - t0) * 1000
        return {
            "brief_xml": f"<surgical_brief><critical_warnings>Librarian extraction failed: {exc}</critical_warnings></surgical_brief>",
            "tokens_in": 0,
            "tokens_out": 0,
            "processing_time_ms": round(elapsed, 1),
            "sources_used": sources_used,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Claude Surgeon — receives the brief and reasons with tools
# ---------------------------------------------------------------------------

SURGEON_SYSTEM_WITH_BRIEF = """\
You are the Lead Surgeon AI (OsteoTwin). Below is a <surgical_brief> extracted \
from our comprehensive knowledge base by the Librarian Agent.

YOUR TASK:
1. Process the provided XML data as your primary anatomical and technical grounding.
2. Combine this "Static Knowledge" with the "Dynamic Simulation Data" from the Simulation Server tools.
3. Answer the Surgeon's query with consultative precision, prioritizing safety and biomechanical stability.

ABSOLUTE RULES:
- NEVER predict, imagine, or guess physics outcomes — use simulation tools.
- NEVER give commands or prescriptive instructions — you are consultative.
- Reference specific anatomical structures by name.
- When your training knowledge conflicts with the surgical brief, prefer the brief.

CONTEXT FROM LIBRARIAN:
{brief_xml}
"""


def build_surgeon_system_with_brief(brief_xml: str) -> list[dict]:
    """Build Claude's system prompt with the Gemini-extracted brief cached.

    Returns content blocks with cache_control for the Anthropic API.
    """
    return [
        {
            "type": "text",
            "text": SURGEON_SYSTEM_WITH_BRIEF.format(brief_xml=brief_xml),
            "cache_control": {"type": "ephemeral"},
        },
    ]
