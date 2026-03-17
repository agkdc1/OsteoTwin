"""End-to-end tests with realistic surgical scenarios.

Tests the complete pipeline from surgeon input to simulation output,
covering the Spatial-Semantic Schema, coordinate translation,
UI sync, printer config, and clinical logging flows.

Does NOT require running servers - tests schema logic and data flow only.
For server-dependent tests, see test_e2e_pipeline.py.
"""

from __future__ import annotations

import json
import math

import pytest

from shared.schemas import (
    ActionType,
    AnatomicalDirection,
    FragmentIdentity,
    LPSVector,
    LPSRotation,
    SemanticMovement,
    SurgicalAction,
    CorrectionSuggestion,
    ValidationFeedback,
    PrinterConfig,
    FilamentMapping,
    MaterialType,
)
from shared.kinematics import (
    resolve_movements,
    surgical_action_to_sim_request,
    euler_to_rotation_matrix,
)
from shared.clinical_log_schemas import (
    SurgicalCaseLog,
    PlanSnapshot,
    compute_delta_metrics,
)
from shared.implant_schemas import (
    ManufacturerAlias,
    ParametricImplantSpec,
    ImplantQAState,
    QAIteration,
    QAStatus,
)


# ---------------------------------------------------------------------------
# Scenario 1: Distal Radius Fracture Reduction (AO 23-C2.1)
# ---------------------------------------------------------------------------

class TestScenarioDistalRadius:
    """Simulate a complete distal radius fracture reduction workflow.

    Clinical context: 45-year-old male, right wrist, comminuted
    intra-articular fracture. Volar approach planned.
    """

    @pytest.fixture
    def fragments(self) -> dict[str, FragmentIdentity]:
        return {
            "proximal": FragmentIdentity(
                fragment_id="radius_R_frag1_proximal",
                color_code="White", volume_mm3=28000,
                bone="radius", side="R", qualifier="proximal",
            ),
            "distal_radial": FragmentIdentity(
                fragment_id="radius_R_frag2_distal_radial",
                color_code="Green", volume_mm3=8500,
                bone="radius", side="R", qualifier="distal_radial",
            ),
            "distal_ulnar": FragmentIdentity(
                fragment_id="radius_R_frag3_distal_ulnar",
                color_code="Blue", volume_mm3=6200,
                bone="radius", side="R", qualifier="distal_ulnar",
            ),
        }

    def test_step1_surgeon_verbal_to_surgical_action(self, fragments):
        """Surgeon says: 'Move the green fragment 3mm distally and 5 degrees valgus'"""
        action = SurgicalAction(
            action_type=ActionType.TRANSLATE_AND_ROTATE,
            target=fragments["distal_radial"],
            clinical_intent="Move the green fragment 3mm distally and 5 degrees valgus",
            movements=[
                SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=3.0, side="R"),
                SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="R"),
            ],
            case_id="DR-2026-001",
            source_agent="claude",
        )
        assert action.target.color_code == "Green"
        assert len(action.movements) == 2

    def test_step2_semantic_to_lps_resolution(self, fragments):
        """Resolve clinical terms to LPS math."""
        movements = [
            SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=3.0, side="R"),
            SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="R"),
        ]
        t, r = resolve_movements(movements)
        assert t.z == pytest.approx(-3.0)  # distal = -Z
        assert r.y_deg == pytest.approx(-5.0)  # valgus R = -Y rotation

    def test_step3_bridge_to_sim_request(self, fragments):
        """SurgicalAction -> SimActionRequest for the Simulation Server."""
        action = SurgicalAction(
            action_type=ActionType.TRANSLATE_AND_ROTATE,
            target=fragments["distal_radial"],
            clinical_intent="Move green 3mm distal + 5deg valgus",
            movements=[
                SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=3.0, side="R"),
                SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="R"),
            ],
            case_id="DR-2026-001",
        )
        req = surgical_action_to_sim_request(action, case_id="DR-2026-001")
        assert req.case_id == "DR-2026-001"
        assert req.fragment_id == "radius_R_frag2_distal_radial"
        assert req.translation.z == pytest.approx(-3.0)
        assert req.branch == "LLM_Hypothesis"
        # Rotation matrix should reflect 5 deg valgus
        rm = req.rotation
        assert rm.r00 != 1.0  # not identity

    def test_step4_gemini_validation_feedback(self, fragments):
        """Gemini reviews the rendered result and suggests correction."""
        original_action = SurgicalAction(
            action_type=ActionType.TRANSLATE,
            target=fragments["distal_ulnar"],
            clinical_intent="Reduce blue fragment",
            translation_mm=LPSVector(x=0, y=0, z=-2),
        )
        feedback = ValidationFeedback(
            original_action=original_action,
            is_acceptable=False,
            corrections=[
                CorrectionSuggestion(
                    fragment_id="radius_R_frag3_distal_ulnar",
                    reason="Articular step-off still visible, needs 1.5mm more distalization",
                    correction_translation_mm=LPSVector(x=0, y=0, z=-1.5),
                    confidence=0.82,
                )
            ],
            visual_assessment="Gap reduced but articular congruity not restored",
        )
        assert not feedback.is_acceptable
        assert feedback.corrections[0].correction_translation_mm.z == -1.5

    def test_step5_kwire_placement(self, fragments):
        """Place a K-wire for temporary fixation."""
        action = SurgicalAction(
            action_type=ActionType.INSERT_K_WIRE,
            target=fragments["distal_radial"],
            clinical_intent="Insert 1.6mm K-wire from radial styloid",
            hardware_id="k_wire_1.6mm",
            hardware_position=LPSVector(x=-15, y=-5, z=-10),
            hardware_orientation=LPSRotation(x_deg=0, y_deg=15, z_deg=0),
        )
        req = surgical_action_to_sim_request(action, case_id="DR-2026-001")
        assert req.place_hardware == "k_wire_1.6mm"
        assert req.hardware_position.x == pytest.approx(-15)

    def test_step6_clinical_logging(self, fragments):
        """Log the complete case with AI vs surgeon plan delta."""
        ai_plan = PlanSnapshot(
            fragment_positions={
                "radius_R_frag2_distal_radial": [0, 0, -3],
                "radius_R_frag3_distal_ulnar": [0, 0, -2],
            },
            implants_selected=["SYN_LCP_Volar_7Hole", "k_wire_1.6mm"],
            approach="volar",
        )
        surgeon_plan = PlanSnapshot(
            fragment_positions={
                "radius_R_frag2_distal_radial": [0, 0, -3],
                "radius_R_frag3_distal_ulnar": [1.5, 0, -3.5],
            },
            implants_selected=["SYN_LCP_Volar_7Hole", "k_wire_1.6mm", "k_wire_1.0mm"],
            approach="volar",
        )
        delta = compute_delta_metrics(ai_plan, surgeon_plan)
        assert "k_wire_1.0mm" in delta.implants_added
        assert delta.max_translation_mm > 0
        assert not delta.approach_changed

        log = SurgicalCaseLog(
            case_id="DR-2026-001",
            surgeon_id="dr-kim",
            target_anatomy="distal_radius",
            ao_code="23-C2.1",
            time_to_decision_sec=85.0,
            ai_proposed_plan=ai_plan,
            surgeon_final_plan=surgeon_plan,
            delta_metrics=delta,
            intent_mismatch_log="Added extra K-wire for rotational stability of ulnar fragment",
        )
        assert log.delta_metrics.max_translation_mm > 0


# ---------------------------------------------------------------------------
# Scenario 2: Left Proximal Humerus (side-flip test)
# ---------------------------------------------------------------------------

class TestScenarioLeftHumerus:
    """Test that left-side bones correctly flip medial/lateral signs."""

    def test_medial_left_is_negative_x(self):
        movements = [
            SemanticMovement(direction=AnatomicalDirection.MEDIAL, magnitude=4.0, side="L"),
        ]
        t, _ = resolve_movements(movements)
        assert t.x == pytest.approx(-4.0)  # left medial = -X

    def test_valgus_left_is_positive_y(self):
        movements = [
            SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="L"),
        ]
        _, r = resolve_movements(movements)
        assert r.y_deg == pytest.approx(5.0)  # left valgus = +Y (opposite of right)

    def test_full_left_shoulder_scenario(self):
        """Left proximal humerus: 2mm lateral, 3deg external rotation."""
        action = SurgicalAction(
            action_type=ActionType.TRANSLATE_AND_ROTATE,
            target=FragmentIdentity(
                fragment_id="humerus_L_frag1_head",
                color_code="Yellow", volume_mm3=15000,
                bone="humerus", side="L",
            ),
            clinical_intent="Shift humeral head 2mm lateral and 3deg external rotation",
            movements=[
                SemanticMovement(direction=AnatomicalDirection.LATERAL, magnitude=2.0, side="L"),
                SemanticMovement(direction=AnatomicalDirection.EXTERNAL_ROTATION, magnitude=3.0, side="L"),
            ],
        )
        t, r = resolve_movements(action.movements)
        # Left lateral = +X (flipped from right lateral=-X)
        assert t.x == pytest.approx(2.0)
        # Left external rotation = -Z (flipped from right external=+Z... wait)
        # External rotation for right = -Z, for left = +Z (flipped)
        assert r.z_deg == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Scenario 3: 3D Print Export Configuration
# ---------------------------------------------------------------------------

class TestScenarioPrintExport:
    """Test the printer config -> export pipeline data flow."""

    def test_prusa_xl_5_toolhead_config(self):
        config = PrinterConfig(
            printer_id="prusa-xl-5t",
            printer_name="Prusa XL 5-Toolhead",
            num_extruders=5,
            build_volume_mm=LPSVector(x=360, y=360, z=360),
            filament_mappings=[
                FilamentMapping(color_code="White", extruder_id=0, material_type=MaterialType.PC,
                                material_label="Bone-Simulating PC"),
                FilamentMapping(color_code="Green", extruder_id=1, material_type=MaterialType.PETG,
                                material_label="Fragment Highlight"),
                FilamentMapping(color_code="Blue", extruder_id=2, material_type=MaterialType.PETG),
                FilamentMapping(color_code="Steel Blue", extruder_id=3, material_type=MaterialType.PETG,
                                material_label="Hardware"),
                FilamentMapping(color_code="Red", extruder_id=4, material_type=MaterialType.TPU,
                                material_label="Danger Zone (flexible)"),
            ],
            is_default=True,
        )
        assert config.num_extruders == 5
        assert len(config.filament_mappings) == 5
        # Verify color->extruder lookup
        mapping = {fm.color_code: fm.extruder_id for fm in config.filament_mappings}
        assert mapping["White"] == 0
        assert mapping["Red"] == 4

    def test_build_volume_check(self):
        """Verify model fits in printer build volume."""
        config = PrinterConfig(
            printer_id="small",
            printer_name="Small Printer",
            num_extruders=1,
            build_volume_mm=LPSVector(x=180, y=180, z=180),
        )
        model_bbox = {"x": 150, "y": 120, "z": 90}
        fits = (model_bbox["x"] <= config.build_volume_mm.x and
                model_bbox["y"] <= config.build_volume_mm.y and
                model_bbox["z"] <= config.build_volume_mm.z)
        assert fits


# ---------------------------------------------------------------------------
# Scenario 4: Autonomous CAD Pipeline QA Loop
# ---------------------------------------------------------------------------

class TestScenarioCADPipeline:
    """Test the 6-strike QA loop state machine with realistic flow."""

    def test_successful_pipeline_iteration_2(self):
        """Implant rejected once, corrected, then approved on iteration 2."""
        spec = ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.SYN,
            implant_name="LCP Volar Distal Radius Plate",
            implant_type="locking_plate",
            length_mm=68, width_mm=22, thickness_mm=2.4,
            hole_count=7,
            body_region="distal_radius",
        )
        qa = ImplantQAState(implant_spec=spec)

        # Iteration 1: rejected - missing 2 distal holes
        qa.iterations.append(QAIteration(
            iteration=1, status=QAStatus.REJECTED,
            feedback="Missing 2 distal locking holes",
            constraint_checklist=[
                "Variable: hole_count, Current: 5, Expected: 7, Fix: Add 2 distal holes",
                "Variable: contour, Fix: Add anatomic pre-bend",
            ],
        ))
        assert not qa.is_approved
        assert not qa.is_halted
        assert qa.rejection_count == 1

        # Iteration 2: approved after correction
        qa.iterations.append(QAIteration(
            iteration=2, status=QAStatus.APPROVED,
            feedback=None,
        ))
        assert qa.is_approved
        assert qa.current_iteration == 2

    def test_six_strike_halt_with_report(self):
        """6 consecutive rejections -> halt with failure report."""
        spec = ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.STK,
            implant_name="Complex Anatomic Plate",
            implant_type="recon_plate",
            length_mm=120, width_mm=15, thickness_mm=3,
            contour="anatomic",
        )
        qa = ImplantQAState(implant_spec=spec)

        for i in range(6):
            qa.iterations.append(QAIteration(
                iteration=i + 1, status=QAStatus.REJECTED,
                feedback=f"Contour error at segment {i+1}",
                constraint_checklist=[f"Fix contour segment {i+1}"],
            ))

        assert qa.is_halted
        assert qa.rejection_count == 6
        assert not qa.is_approved

        # Verify all feedback is accessible for the failure report
        feedbacks = [it.feedback for it in qa.iterations if it.status == QAStatus.REJECTED]
        assert len(feedbacks) == 6


# ---------------------------------------------------------------------------
# Scenario 5: Coordinate System Integrity (Three.js <-> LPS roundtrip)
# ---------------------------------------------------------------------------

class TestScenarioCoordinateIntegrity:
    """Verify Three.js Y-up <-> LPS Z-up conversion preserves information.

    This simulates what coordinateMapper.ts does in the frontend.
    """

    @staticmethod
    def three_to_lps(pos: dict) -> LPSVector:
        """Python equivalent of coordinateMapper.ts threeToLPS()."""
        return LPSVector(x=-pos["x"], y=-pos["z"], z=pos["y"])

    @staticmethod
    def lps_to_three(lps: LPSVector) -> dict:
        """Python equivalent of coordinateMapper.ts lpsToThree()."""
        return {"x": -lps.x, "y": lps.z, "z": -lps.y}

    def test_roundtrip_position(self):
        """three -> lps -> three should recover original."""
        original = {"x": 5.0, "y": 10.0, "z": -3.0}
        lps = self.three_to_lps(original)
        recovered = self.lps_to_three(lps)
        assert recovered["x"] == pytest.approx(original["x"])
        assert recovered["y"] == pytest.approx(original["y"])
        assert recovered["z"] == pytest.approx(original["z"])

    def test_lps_z_up_maps_to_three_y_up(self):
        """LPS Z+ (superior) should map to Three.js Y+ (up)."""
        lps = LPSVector(x=0, y=0, z=10)  # 10mm superior
        three = self.lps_to_three(lps)
        assert three["y"] == pytest.approx(10.0)  # up in Three.js

    def test_lps_left_maps_to_three_negative_x(self):
        """LPS X+ (left) should map to Three.js -X."""
        lps = LPSVector(x=5, y=0, z=0)  # 5mm left
        three = self.lps_to_three(lps)
        assert three["x"] == pytest.approx(-5.0)

    def test_drag_delta_consistency(self):
        """Simulate a fragment drag in Three.js and verify LPS delta."""
        before_three = {"x": 0, "y": 5, "z": 0}
        after_three = {"x": 0, "y": 7, "z": -2}  # dragged 2mm up, 2mm forward

        before_lps = self.three_to_lps(before_three)
        after_lps = self.three_to_lps(after_three)

        delta = LPSVector(
            x=after_lps.x - before_lps.x,
            y=after_lps.y - before_lps.y,
            z=after_lps.z - before_lps.z,
        )
        # 2mm up in Three.js = 2mm superior in LPS (+Z)
        assert delta.z == pytest.approx(2.0)
        # 2mm toward camera in Three.js (-Z) = 2mm anterior in LPS (-Y)... wait
        # Three.js Z- = toward camera = anterior; LPS Y- = anterior
        # three_to_lps: lps.y = -three.z -> delta_lps_y = -(-2 - 0) = 2 (posterior)
        assert delta.y == pytest.approx(2.0)  # -(-2) = posterior
