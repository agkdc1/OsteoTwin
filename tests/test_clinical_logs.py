"""Unit tests for clinical logging schemas and delta computation."""

from __future__ import annotations

import pytest

from shared.clinical_log_schemas import (
    DeltaMetrics,
    PlanSnapshot,
    SurgicalCaseLog,
    compute_delta_metrics,
)


class TestPlanSnapshot:
    def test_empty_plan(self):
        p = PlanSnapshot()
        assert len(p.fragment_positions) == 0
        assert len(p.implants_selected) == 0

    def test_with_data(self):
        p = PlanSnapshot(
            fragment_positions={"frag1": [0, 0, 0], "frag2": [10, 5, -3]},
            implants_selected=["SYN_LCP_Volar_7Hole"],
            approach="volar",
        )
        assert len(p.fragment_positions) == 2
        assert p.approach == "volar"


class TestDeltaMetrics:
    def test_identical_plans(self):
        plan = PlanSnapshot(
            fragment_positions={"f1": [1, 2, 3]},
            implants_selected=["plate_A"],
            approach="volar",
        )
        delta = compute_delta_metrics(plan, plan)
        assert delta.max_translation_mm == 0.0
        assert len(delta.implants_added) == 0
        assert len(delta.implants_removed) == 0
        assert not delta.approach_changed

    def test_translation_delta(self):
        ai = PlanSnapshot(fragment_positions={"f1": [0, 0, 0]})
        surgeon = PlanSnapshot(fragment_positions={"f1": [0, 0, -5]})
        delta = compute_delta_metrics(ai, surgeon)
        assert delta.translation_deltas_mm["f1"] == [0.0, 0.0, -5.0]
        assert delta.max_translation_mm == pytest.approx(5.0)

    def test_implant_changes(self):
        ai = PlanSnapshot(implants_selected=["plate_A", "kwire_1"])
        surgeon = PlanSnapshot(implants_selected=["plate_A", "plate_B"])
        delta = compute_delta_metrics(ai, surgeon)
        assert "plate_B" in delta.implants_added
        assert "kwire_1" in delta.implants_removed

    def test_approach_changed(self):
        ai = PlanSnapshot(approach="dorsal")
        surgeon = PlanSnapshot(approach="volar")
        delta = compute_delta_metrics(ai, surgeon)
        assert delta.approach_changed

    def test_multi_fragment_max(self):
        ai = PlanSnapshot(fragment_positions={"f1": [0, 0, 0], "f2": [10, 0, 0]})
        surgeon = PlanSnapshot(fragment_positions={"f1": [1, 0, 0], "f2": [10, 0, -8]})
        delta = compute_delta_metrics(ai, surgeon)
        assert delta.max_translation_mm == pytest.approx(8.0)
        assert delta.translation_deltas_mm["f1"] == [1.0, 0.0, 0.0]
        assert delta.translation_deltas_mm["f2"] == [0.0, 0.0, -8.0]


class TestSurgicalCaseLog:
    def test_basic_log(self):
        log = SurgicalCaseLog(
            case_id="case-001",
            surgeon_id="dr-kim",
            target_anatomy="distal_radius",
        )
        assert log.case_id == "case-001"
        assert log.log_id  # auto-generated UUID
        assert log.timestamp

    def test_full_log_with_plans(self):
        log = SurgicalCaseLog(
            case_id="case-002",
            surgeon_id="dr-kim",
            target_anatomy="proximal_humerus",
            ao_code="11-C2.1",
            time_to_decision_sec=120.5,
            ai_proposed_plan=PlanSnapshot(
                fragment_positions={"frag1": [0, 0, 0]},
                implants_selected=["lcp_plate"],
                approach="deltopectoral",
            ),
            surgeon_final_plan=PlanSnapshot(
                fragment_positions={"frag1": [2, 0, -3]},
                implants_selected=["lcp_plate", "k_wire_1.6mm"],
                approach="deltopectoral",
            ),
            intent_mismatch_log="Added K-wire for rotational stability",
            surgeon_satisfaction=4,
        )
        assert log.time_to_decision_sec == 120.5
        assert log.surgeon_satisfaction == 4
        assert "K-wire" in log.intent_mismatch_log

    def test_satisfaction_range(self):
        with pytest.raises(Exception):
            SurgicalCaseLog(
                case_id="t", surgeon_id="t", target_anatomy="t",
                surgeon_satisfaction=6,
            )

    def test_json_roundtrip(self):
        log = SurgicalCaseLog(
            case_id="rt-001",
            surgeon_id="dr-test",
            target_anatomy="distal_radius",
            intent_mismatch_log="test",
            post_op_deviation_log="cortical comminution",
        )
        j = log.model_dump_json()
        log2 = SurgicalCaseLog.model_validate_json(j)
        assert log2.case_id == "rt-001"
        assert log2.post_op_deviation_log == "cortical comminution"
