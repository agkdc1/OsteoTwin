"""Unit tests for shared Pydantic schemas.

Covers: LPS coordinate system, FragmentIdentity, SurgicalAction,
SemanticMovement, PrinterConfig, FilamentMapping, ValidationFeedback.
"""

from __future__ import annotations

import json

import pytest

from shared.schemas import (
    ActionType,
    AnatomicalDirection,
    CorrectionSuggestion,
    DIRECTION_LPS_MAP,
    FilamentMapping,
    FragmentIdentity,
    LPSRotation,
    LPSVector,
    MaterialType,
    PrinterConfig,
    SemanticMovement,
    SurgicalAction,
    ValidationFeedback,
)


class TestLPSVector:
    def test_default_zero(self):
        v = LPSVector()
        assert v.x == 0.0 and v.y == 0.0 and v.z == 0.0

    def test_custom_values(self):
        v = LPSVector(x=1.5, y=-2.3, z=10.0)
        assert v.x == 1.5
        assert v.y == -2.3
        assert v.z == 10.0

    def test_json_roundtrip(self):
        v = LPSVector(x=3.14, y=-1.0, z=42.0)
        j = v.model_dump_json()
        v2 = LPSVector.model_validate_json(j)
        assert v2.x == v.x and v2.y == v.y and v2.z == v.z


class TestFragmentIdentity:
    def test_required_fields(self):
        f = FragmentIdentity(
            fragment_id="tibia_R_frag1_proximal",
            color_code="Green",
            volume_mm3=12500.0,
        )
        assert f.fragment_id == "tibia_R_frag1_proximal"
        assert f.color_code == "Green"
        assert f.volume_mm3 == 12500.0

    def test_volume_non_negative(self):
        with pytest.raises(Exception):
            FragmentIdentity(
                fragment_id="test", color_code="Red", volume_mm3=-100
            )

    def test_optional_fields(self):
        f = FragmentIdentity(
            fragment_id="humerus_L_frag2",
            color_code="Blue",
            volume_mm3=8000,
            bone="humerus",
            side="L",
            qualifier="shaft",
        )
        assert f.bone == "humerus"
        assert f.side == "L"


class TestSemanticMovement:
    def test_basic_movement(self):
        m = SemanticMovement(
            direction=AnatomicalDirection.DISTAL, magnitude=2.0, side="R"
        )
        assert m.direction == AnatomicalDirection.DISTAL
        assert m.magnitude == 2.0
        assert m.side == "R"

    def test_magnitude_must_be_positive(self):
        with pytest.raises(Exception):
            SemanticMovement(
                direction=AnatomicalDirection.PROXIMAL, magnitude=-1.0
            )

    def test_all_directions_mapped(self):
        """Every AnatomicalDirection (except compound) must have an LPS mapping."""
        for d in AnatomicalDirection:
            if d in (AnatomicalDirection.COMPRESSION, AnatomicalDirection.DISTRACTION):
                continue
            assert d in DIRECTION_LPS_MAP, f"Missing LPS mapping for {d}"


class TestSurgicalAction:
    def test_full_action(self):
        action = SurgicalAction(
            action_type=ActionType.TRANSLATE_AND_ROTATE,
            target=FragmentIdentity(
                fragment_id="tibia_R_frag1", color_code="Green", volume_mm3=12500
            ),
            clinical_intent="Move green fragment 2mm distally and 3 deg valgus",
            movements=[
                SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=2.0, side="R"),
                SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=3.0, side="R"),
            ],
            case_id="test-001",
            source_agent="claude",
        )
        assert action.action_type == ActionType.TRANSLATE_AND_ROTATE
        assert len(action.movements) == 2
        assert action.branch == "LLM_Hypothesis"

    def test_json_roundtrip(self):
        action = SurgicalAction(
            action_type=ActionType.INSERT_K_WIRE,
            target=FragmentIdentity(fragment_id="radius_R_frag1", color_code="Blue", volume_mm3=5000),
            clinical_intent="Insert 1.6mm K-wire",
            hardware_id="k_wire_1.6mm",
        )
        j = action.model_dump_json()
        action2 = SurgicalAction.model_validate_json(j)
        assert action2.hardware_id == "k_wire_1.6mm"
        assert action2.target.fragment_id == "radius_R_frag1"

    def test_all_action_types(self):
        for at in ActionType:
            action = SurgicalAction(
                action_type=at,
                target=FragmentIdentity(fragment_id="test", color_code="Red", volume_mm3=100),
                clinical_intent=f"Test {at.value}",
            )
            assert action.action_type == at


class TestValidationFeedback:
    def test_approved_feedback(self):
        fb = ValidationFeedback(
            original_action=SurgicalAction(
                action_type=ActionType.TRANSLATE,
                target=FragmentIdentity(fragment_id="t", color_code="R", volume_mm3=1),
                clinical_intent="test",
            ),
            is_acceptable=True,
            visual_assessment="Looks correct",
        )
        assert fb.is_acceptable
        assert len(fb.corrections) == 0

    def test_rejected_with_corrections(self):
        fb = ValidationFeedback(
            original_action=SurgicalAction(
                action_type=ActionType.TRANSLATE,
                target=FragmentIdentity(fragment_id="t", color_code="R", volume_mm3=1),
                clinical_intent="test",
            ),
            is_acceptable=False,
            corrections=[
                CorrectionSuggestion(
                    fragment_id="t",
                    reason="Gap too large",
                    correction_translation_mm=LPSVector(x=0, y=0, z=-2),
                    confidence=0.85,
                )
            ],
            visual_assessment="Fragment gap visible",
        )
        assert not fb.is_acceptable
        assert len(fb.corrections) == 1
        assert fb.corrections[0].confidence == 0.85


class TestPrinterConfig:
    def test_basic_config(self):
        pc = PrinterConfig(
            printer_id="prusa-xl-5t",
            printer_name="Prusa XL 5-Toolhead",
            num_extruders=5,
        )
        assert pc.num_extruders == 5
        assert not pc.is_default

    def test_filament_mapping(self):
        fm = FilamentMapping(
            color_code="White",
            extruder_id=0,
            material_type=MaterialType.PC,
            material_label="Bone-Simulating PC",
            color_hex="#F5F0E1",
        )
        assert fm.extruder_id == 0
        assert fm.material_type == MaterialType.PC

    def test_color_hex_validation(self):
        with pytest.raises(Exception):
            FilamentMapping(
                color_code="Red",
                extruder_id=1,
                material_type=MaterialType.PETG,
                color_hex="not-a-hex",
            )

    def test_full_config_roundtrip(self):
        pc = PrinterConfig(
            printer_id="test",
            printer_name="Test Printer",
            num_extruders=3,
            filament_mappings=[
                FilamentMapping(color_code="White", extruder_id=0, material_type=MaterialType.PLA),
                FilamentMapping(color_code="Red", extruder_id=1, material_type=MaterialType.PETG),
            ],
            is_default=True,
        )
        j = pc.model_dump_json()
        pc2 = PrinterConfig.model_validate_json(j)
        assert pc2.num_extruders == 3
        assert len(pc2.filament_mappings) == 2
        assert pc2.is_default
