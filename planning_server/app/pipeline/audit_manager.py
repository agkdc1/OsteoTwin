"""Grand Surgical Audit Pipeline — Two-Stage LLM Verification.

Phase 1 (Gemini Flash): Synthesize chat history + plans into structured
    audit package. Extract only relevant anatomy from cached textbook.
Phase 2 (Gemini Pro/Ultra): Devil's Advocate audit with Zero-Suggestion Policy.
Phase 3: User Resolution Loop — surgeon must fix identified risks.

Architecture:
    Flash  -> condenses 100K+ tokens into ~10K audit package
    Pro    -> audits package against 6-axis renderings (~4K output)
    Loop   -> repeat Phase 2 until Pro approves or surgeon overrides

Model mapping:
    Flash  = config.GEMINI_MODEL (gemini-3-flash-preview)
    Ultra  = gemini-3.1-pro-preview (used as the auditor)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .. import config
from .llm import generate_text, Provider

logger = logging.getLogger("osteotwin.audit")

# The "Ultra" model for the Grand Audit (Phase 2)
AUDIT_MODEL = "gemini-3.1-pro-preview"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class AuditSeverity(str, Enum):
    CRITICAL = "critical"      # Must be resolved before proceeding
    WARNING = "warning"        # Should be addressed
    INFO = "info"              # Observation, no action required
    APPROVED = "approved"      # This aspect passes audit


class AuditFinding(BaseModel):
    """A single finding from the Grand Surgical Audit."""

    finding_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    severity: AuditSeverity
    category: str = Field(
        ..., description="'anatomical', 'biomechanical', 'interference', 'carm_access'"
    )
    plan_ref: str = Field(..., description="Which plan: 'Plan A', 'Plan B', etc.")
    description: str = Field(
        ..., description="The identified risk — NEVER contains a suggestion"
    )
    textbook_reference: Optional[str] = Field(
        None, description="Source citation from the extracted textbook context"
    )
    interrogation: Optional[str] = Field(
        None,
        description="Question demanding surgeon's resolution (Zero-Suggestion Policy)",
    )
    resolved: bool = Field(default=False)
    surgeon_resolution: Optional[str] = Field(
        None, description="Surgeon's response to the interrogation"
    )


class AuditPackage(BaseModel):
    """Condensed output from Phase 1 (Flash)."""

    package_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    case_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Formalized plans
    plans: list[dict] = Field(
        ..., description="Structured Plan A, B, C with entry points, clamps, trajectories"
    )

    # Extracted anatomy (narrowed from full textbook)
    anatomical_context: str = Field(
        ..., description="Relevant paragraphs, spatial relations, danger zones from textbook"
    )
    anatomical_regions: list[str] = Field(
        default_factory=list,
        description="Identified regions (e.g., 'distal_radius_volar')",
    )

    # Metadata
    source_token_count: int = Field(default=0, description="Tokens in original chat + textbook")
    condensed_token_count: int = Field(default=0, description="Tokens in this package")


class AuditReport(BaseModel):
    """Output from Phase 2 (Pro/Ultra audit)."""

    report_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    case_id: str
    audit_round: int = Field(default=1)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Findings
    findings: list[AuditFinding] = Field(default_factory=list)

    # Verdict
    has_critical: bool = Field(default=False)
    is_approved: bool = Field(default=False)
    verdict_summary: str = Field(default="")

    # The package that was audited
    package_id: str = Field(default="")

    @property
    def unresolved_critical(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.severity == AuditSeverity.CRITICAL and not f.resolved]


# ---------------------------------------------------------------------------
# Phase 1: Flash — Context Narrowing & Plan Formalization
# ---------------------------------------------------------------------------

PHASE1_SYSTEM_PROMPT = """\
You are OsteoTwin's Surgical Plan Synthesizer (Phase 1).

You receive:
1. A messy pre-operative discussion log between the surgeon and AI
2. Draft surgical plans (Plan A, B, C)
3. Relevant cached anatomy textbook content

Your tasks:
TASK 1 (Plan Formalization):
Synthesize the discussion into a structured document defining each plan:
- Entry points (LPS coordinates if available)
- Clamp types and positions
- K-wire trajectories (origin, direction, diameter)
- Plate placement zone
- Reduction sequence

TASK 2 (Targeted Extraction):
Identify the specific anatomical regions involved in the plans.
Extract ONLY the relevant paragraphs from the textbook:
- Spatial relations of nerves, vessels, tendons in the operative field
- Danger zones with distance thresholds
- Anatomical landmarks for the specific approach

Output a JSON object with:
{
  "plans": [
    {
      "plan_id": "Plan A",
      "approach": "...",
      "entry_points": [...],
      "clamp_placements": [...],
      "kwire_trajectories": [...],
      "plate_zone": {...},
      "reduction_steps": [...]
    }
  ],
  "anatomical_context": "Extracted text from textbook...",
  "anatomical_regions": ["distal_radius_volar", ...]
}

Be thorough but concise. The output feeds directly into the Grand Audit.
"""


async def phase1_condense(
    case_id: str,
    discussion_log: str,
    draft_plans: list[dict],
    textbook_content: str,
) -> AuditPackage:
    """Phase 1: Flash condenses discussion + textbook into audit package."""
    source_tokens = len(discussion_log.split()) + len(textbook_content.split())

    prompt = (
        f"## Pre-Operative Discussion Log:\n{discussion_log}\n\n"
        f"## Draft Plans:\n{json.dumps(draft_plans, indent=2)}\n\n"
        f"## Anatomy Textbook Content:\n{textbook_content[:50000]}\n\n"  # cap at ~50K chars
        f"Synthesize into structured audit package."
    )

    raw = await generate_text(
        prompt,
        system=PHASE1_SYSTEM_PROMPT,
        provider=Provider.GEMINI,
        max_tokens=8192,
    )

    # Parse JSON from response
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            data = {"plans": draft_plans, "anatomical_context": raw[:5000], "anatomical_regions": []}
    else:
        data = {"plans": draft_plans, "anatomical_context": raw[:5000], "anatomical_regions": []}

    condensed_tokens = len(raw.split())

    return AuditPackage(
        case_id=case_id,
        plans=data.get("plans", draft_plans),
        anatomical_context=data.get("anatomical_context", ""),
        anatomical_regions=data.get("anatomical_regions", []),
        source_token_count=source_tokens,
        condensed_token_count=condensed_tokens,
    )


# ---------------------------------------------------------------------------
# Phase 2: Pro/Ultra — Grand Surgical Audit (Zero-Suggestion Policy)
# ---------------------------------------------------------------------------

PHASE2_SYSTEM_PROMPT = """\
You are OsteoTwin's Chief Surgical Auditor (Phase 2 - Grand Audit).

## YOUR ROLE
You are the Devil's Advocate. Your job is to find every possible risk,
collision, and anatomical inconsistency in the proposed surgical plans.

## AUDIT CRITERIA
1. **Anatomical Consistency:** Does any K-wire trajectory, clamp placement,
   or screw path intersect with danger zones defined in the provided
   anatomical context? Check nerve paths, vessel courses, tendon routes.

2. **Biomechanical Consistency:** Can the proposed clamps physically overcome
   the estimated soft-tissue tension? Is the reduction sequence physically
   realizable given the fragment positions?

3. **Interference:** Is there physical collision between:
   - K-wire and existing clamps
   - Clamp and C-arm arc at the required imaging angle
   - Clamp and planned plate position
   - Drill trajectory and temporary fixation

4. **C-arm Access:** Can the C-arm achieve the verification view without
   hitting the bed, patient, or surgical tools?

## ZERO-SUGGESTION POLICY (ABSOLUTE RULE)
You MUST NOT suggest alternatives, modifications, or solutions.
You ONLY identify the risk and demand a resolution from the surgeon.

BAD (REJECT): "The K-wire hits the median nerve. You should move the entry point 5mm laterally."
GOOD (ACCEPT): "CRITICAL RISK in Plan A: The 45-degree K-wire trajectory intersects the median nerve path (Ref: Textbook Ch.7, paragraph 3). State your proposed modification to avoid this neurovascular bundle."

BAD: "Consider using a smaller clamp to avoid C-arm collision."
GOOD: "WARNING in Plan B: The Jungbluth pelvic clamp (200mm bounding radius) will collide with the C-arm arc at the required 30-degree oblique view. How do you intend to obtain intraoperative imaging verification with this clamp in place?"

## OUTPUT FORMAT
Return a JSON array of findings:
[
  {
    "severity": "critical|warning|info|approved",
    "category": "anatomical|biomechanical|interference|carm_access",
    "plan_ref": "Plan A",
    "description": "The identified risk...",
    "textbook_reference": "Source citation if applicable",
    "interrogation": "Question for the surgeon (null if severity=approved)"
  }
]
"""


async def phase2_audit(
    package: AuditPackage,
    rendering_data: Optional[dict] = None,
    audit_round: int = 1,
    previous_resolutions: Optional[list[dict]] = None,
) -> AuditReport:
    """Phase 2: Pro/Ultra audits the condensed package.

    Uses gemini-3.1-pro-preview as the auditor model.
    """
    from google import genai

    prompt_parts = [
        f"## AUDIT ROUND {audit_round}\n",
        f"## Surgical Plans:\n{json.dumps(package.plans, indent=2)}\n\n",
        f"## Anatomical Context (from textbook):\n{package.anatomical_context}\n\n",
    ]

    if rendering_data:
        prompt_parts.append(
            f"## 6-Axis Rendering Data:\n{json.dumps(rendering_data, indent=2)}\n\n"
        )

    if previous_resolutions:
        prompt_parts.append(
            f"## Surgeon's Resolutions from Previous Round:\n"
            f"{json.dumps(previous_resolutions, indent=2)}\n\n"
            f"Re-audit considering these resolutions. "
            f"Mark resolved issues as 'approved'. Find any remaining risks.\n"
        )

    prompt_parts.append(
        "Perform the Grand Surgical Audit. "
        "Output findings as a JSON array. "
        "Remember: ZERO suggestions. Only identify risks and interrogate."
    )

    prompt = "".join(prompt_parts)

    # Call the Pro/Ultra model directly (not through fallback chain)
    try:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=AUDIT_MODEL,
            contents=f"{PHASE2_SYSTEM_PROMPT}\n\n{prompt}",
            config=genai.types.GenerateContentConfig(
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
        )
        raw = resp.text or "[]"
    except Exception as exc:
        logger.error("Phase 2 audit failed with %s: %s", AUDIT_MODEL, exc)
        # Fallback: try gemini-2.5-pro
        try:
            raw = await generate_text(
                prompt, system=PHASE2_SYSTEM_PROMPT,
                provider=Provider.GEMINI, max_tokens=8192,
            )
        except Exception as exc2:
            logger.error("Phase 2 fallback also failed: %s", exc2)
            raw = "[]"

    # Parse findings
    findings: list[AuditFinding] = []
    try:
        json_match = re.search(r"\[[\s\S]*\]", raw)
        if json_match:
            raw_findings = json.loads(json_match.group())
        else:
            raw_findings = json.loads(raw) if raw.strip().startswith("[") else []

        for rf in raw_findings:
            findings.append(AuditFinding(
                severity=AuditSeverity(rf.get("severity", "info")),
                category=rf.get("category", ""),
                plan_ref=rf.get("plan_ref", ""),
                description=rf.get("description", ""),
                textbook_reference=rf.get("textbook_reference"),
                interrogation=rf.get("interrogation"),
            ))
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Failed to parse audit findings: %s", exc)
        findings.append(AuditFinding(
            severity=AuditSeverity.WARNING,
            category="system",
            plan_ref="all",
            description=f"Audit parse error. Raw output: {raw[:500]}",
        ))

    has_critical = any(f.severity == AuditSeverity.CRITICAL for f in findings)
    is_approved = not has_critical and all(
        f.severity in (AuditSeverity.APPROVED, AuditSeverity.INFO) for f in findings
    )

    verdict = ""
    if is_approved:
        verdict = "All plans pass the Grand Surgical Audit. No critical risks identified."
    elif has_critical:
        crit_count = sum(1 for f in findings if f.severity == AuditSeverity.CRITICAL)
        verdict = f"{crit_count} CRITICAL risk(s) identified. Surgeon must resolve before proceeding."
    else:
        warn_count = sum(1 for f in findings if f.severity == AuditSeverity.WARNING)
        verdict = f"{warn_count} warning(s) identified. Review recommended before proceeding."

    return AuditReport(
        case_id=package.case_id,
        audit_round=audit_round,
        findings=findings,
        has_critical=has_critical,
        is_approved=is_approved,
        verdict_summary=verdict,
        package_id=package.package_id,
    )


# ---------------------------------------------------------------------------
# Phase 3: Resolution Loop
# ---------------------------------------------------------------------------


async def resolution_loop(
    package: AuditPackage,
    rendering_data: Optional[dict] = None,
    max_rounds: int = 5,
) -> tuple[AuditReport, list[AuditReport]]:
    """Run the full audit -> resolution -> re-audit loop.

    Returns (final_report, all_rounds).
    The loop terminates when:
    - All critical findings are resolved (approved)
    - Max rounds reached (surgeon must override)
    """
    all_rounds: list[AuditReport] = []
    resolutions: list[dict] = []

    for round_num in range(1, max_rounds + 1):
        logger.info("Grand Audit round %d/%d for case %s", round_num, max_rounds, package.case_id)

        report = await phase2_audit(
            package,
            rendering_data=rendering_data,
            audit_round=round_num,
            previous_resolutions=resolutions if round_num > 1 else None,
        )
        all_rounds.append(report)

        if report.is_approved:
            logger.info("Audit APPROVED on round %d", round_num)
            break

        if not report.has_critical:
            logger.info("No critical findings on round %d (warnings only)", round_num)
            break

        # In automated mode, we can't get surgeon input — break here
        # The API caller handles the resolution loop via repeated calls
        logger.info(
            "Round %d: %d critical findings pending resolution",
            round_num, len(report.unresolved_critical),
        )
        break  # Return to caller for surgeon input

    return all_rounds[-1], all_rounds


# ---------------------------------------------------------------------------
# Full pipeline entry point
# ---------------------------------------------------------------------------


async def run_grand_audit(
    case_id: str,
    discussion_log: str,
    draft_plans: list[dict],
    textbook_content: str,
    rendering_data: Optional[dict] = None,
) -> dict[str, Any]:
    """Run the complete Grand Surgical Audit pipeline.

    Phase 1: Flash condenses
    Phase 2: Pro/Ultra audits
    Returns package + report for the frontend to display.
    """
    # Phase 1
    logger.info("Phase 1: Condensing audit package for case %s", case_id)
    package = await phase1_condense(case_id, discussion_log, draft_plans, textbook_content)
    logger.info(
        "Phase 1 complete: %d source tokens -> %d condensed tokens (%.0f%% reduction)",
        package.source_token_count,
        package.condensed_token_count,
        (1 - package.condensed_token_count / max(package.source_token_count, 1)) * 100,
    )

    # Phase 2
    logger.info("Phase 2: Grand Audit by %s", AUDIT_MODEL)
    report, all_rounds = await resolution_loop(package, rendering_data)

    return {
        "package": package.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
        "all_rounds": [r.model_dump(mode="json") for r in all_rounds],
        "status": "approved" if report.is_approved else "pending_resolution",
    }
