"""Clinical Case Logging schemas for Firestore.

Captures the full lifecycle of a surgical case for retrospective
academic studies and statistical analysis:
- Quantitative: AI plan vs surgeon final plan, delta metrics, timing
- Qualitative: intent mismatch logs, post-op deviation logs (free-text)

Collection: `clinical_case_logs` in Firestore (Native Mode).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class PlanSnapshot(BaseModel):
    """Snapshot of a surgical plan (either AI-proposed or surgeon-final).

    Captures fragment positions, implant selections, and reduction parameters.
    """

    fragment_positions: dict[str, list[float]] = Field(
        default_factory=dict,
        description="fragment_id → [x, y, z] position in LPS mm",
    )
    fragment_rotations: dict[str, list[float]] = Field(
        default_factory=dict,
        description="fragment_id → [rx, ry, rz] Euler degrees (LPS)",
    )
    implants_selected: list[str] = Field(
        default_factory=list,
        description='Implant IDs used, e.g. ["SYN_LCP_Volar_7Hole", "k_wire_1.6mm"]',
    )
    reduction_sequence: list[str] = Field(
        default_factory=list,
        description="Ordered reduction steps as natural language",
    )
    approach: Optional[str] = Field(
        None, description="Surgical approach (e.g., 'volar', 'dorsal')"
    )


class DeltaMetrics(BaseModel):
    """Automatically computed differences between AI plan and surgeon final plan.

    These quantify how much the surgeon deviated from the AI's recommendation.
    """

    translation_deltas_mm: dict[str, list[float]] = Field(
        default_factory=dict,
        description="fragment_id → [dx, dy, dz] translation difference in mm",
    )
    rotation_deltas_deg: dict[str, list[float]] = Field(
        default_factory=dict,
        description="fragment_id → [drx, dry, drz] rotation difference in degrees",
    )
    max_translation_mm: float = Field(
        0.0, description="Maximum translation delta across all fragments"
    )
    max_rotation_deg: float = Field(
        0.0, description="Maximum rotation delta across all fragments"
    )
    implants_added: list[str] = Field(
        default_factory=list,
        description="Implants the surgeon added that AI didn't propose",
    )
    implants_removed: list[str] = Field(
        default_factory=list,
        description="Implants the AI proposed that surgeon removed",
    )
    approach_changed: bool = Field(
        False, description="True if surgeon changed the surgical approach"
    )


# ---------------------------------------------------------------------------
# Main log document
# ---------------------------------------------------------------------------


class SurgicalCaseLog(BaseModel):
    """A single clinical case log document stored in Firestore.

    Represents the complete lifecycle: AI proposal → surgeon review →
    final approval → optional post-op feedback.
    """

    # --- Metadata ---
    log_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Unique log document ID",
    )
    case_id: str = Field(..., description="Reference to FractureCase.case_id")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this log was created",
    )
    surgeon_id: str = Field(
        ..., description="Authenticated surgeon user ID"
    )
    target_anatomy: str = Field(
        ...,
        description="Target anatomy, e.g. 'distal_radius', 'proximal_humerus'",
    )
    ao_code: Optional[str] = Field(
        None, description="AO classification code (e.g., '23-C2.1')"
    )

    # --- Quantitative Metrics ---
    time_to_decision_sec: Optional[float] = Field(
        None,
        ge=0,
        description="Seconds from AI plan presentation to surgeon approval",
    )
    ai_proposed_plan: Optional[PlanSnapshot] = Field(
        None, description="The AI's initial surgical plan"
    )
    surgeon_final_plan: Optional[PlanSnapshot] = Field(
        None, description="The surgeon's approved final plan"
    )
    delta_metrics: Optional[DeltaMetrics] = Field(
        None,
        description="Auto-computed differences between AI and surgeon plans",
    )
    debate_rounds: Optional[int] = Field(
        None, ge=0, description="Number of multi-agent debate rounds used"
    )
    simulation_count: Optional[int] = Field(
        None, ge=0, description="Total simulation tool calls during planning"
    )

    # --- Qualitative Metrics (Free-text / Natural Language) ---
    intent_mismatch_log: Optional[str] = Field(
        None,
        description=(
            "Why the surgeon modified the AI's plan during pre-op. "
            "Free-text. e.g., 'AI missed the radial nerve trajectory, "
            "moved plate 5mm distally'"
        ),
    )
    post_op_deviation_log: Optional[str] = Field(
        None,
        description=(
            "Real-world variables in the OR that caused deviation from plan. "
            "Free-text. e.g., 'Comminution was worse than CT showed, "
            "cortical support failed, altered screw angle'"
        ),
    )
    surgeon_satisfaction: Optional[int] = Field(
        None,
        ge=1,
        le=5,
        description="1-5 satisfaction score with the AI planning session",
    )
    additional_notes: Optional[str] = Field(
        None, description="Any other free-text notes from the surgeon"
    )

    # --- System Metadata ---
    planning_server_version: str = Field(
        default="0.1.0", description="Planning server version at time of logging"
    )
    claude_model: Optional[str] = Field(
        None, description="Claude model ID used for this session"
    )
    gemini_model: Optional[str] = Field(
        None, description="Gemini model ID used for this session"
    )


# ---------------------------------------------------------------------------
# Helper: compute delta metrics
# ---------------------------------------------------------------------------


def compute_delta_metrics(
    ai_plan: PlanSnapshot,
    surgeon_plan: PlanSnapshot,
) -> DeltaMetrics:
    """Compute quantitative deltas between AI and surgeon plans."""
    trans_deltas: dict[str, list[float]] = {}
    rot_deltas: dict[str, list[float]] = {}
    max_trans = 0.0
    max_rot = 0.0

    # Translation deltas
    all_frags = set(ai_plan.fragment_positions) | set(surgeon_plan.fragment_positions)
    for fid in all_frags:
        ai_pos = ai_plan.fragment_positions.get(fid, [0, 0, 0])
        sg_pos = surgeon_plan.fragment_positions.get(fid, [0, 0, 0])
        delta = [sg_pos[i] - ai_pos[i] for i in range(3)]
        trans_deltas[fid] = [round(d, 2) for d in delta]
        mag = sum(d ** 2 for d in delta) ** 0.5
        max_trans = max(max_trans, mag)

    # Rotation deltas
    all_rot_frags = set(ai_plan.fragment_rotations) | set(surgeon_plan.fragment_rotations)
    for fid in all_rot_frags:
        ai_rot = ai_plan.fragment_rotations.get(fid, [0, 0, 0])
        sg_rot = surgeon_plan.fragment_rotations.get(fid, [0, 0, 0])
        delta = [sg_rot[i] - ai_rot[i] for i in range(3)]
        rot_deltas[fid] = [round(d, 2) for d in delta]
        mag = max(abs(d) for d in delta)
        max_rot = max(max_rot, mag)

    # Implant differences
    ai_set = set(ai_plan.implants_selected)
    sg_set = set(surgeon_plan.implants_selected)

    return DeltaMetrics(
        translation_deltas_mm=trans_deltas,
        rotation_deltas_deg=rot_deltas,
        max_translation_mm=round(max_trans, 2),
        max_rotation_deg=round(max_rot, 2),
        implants_added=sorted(sg_set - ai_set),
        implants_removed=sorted(ai_set - sg_set),
        approach_changed=(ai_plan.approach != surgeon_plan.approach),
    )
