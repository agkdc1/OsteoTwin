"""Unit tests for shared/kinematics.py.

Covers: LPS resolution, side-aware sign flips, Euler/rotation matrix
conversion, SurgicalAction-to-SimActionRequest bridge.
"""

from __future__ import annotations

import math

import pytest

from shared.schemas import (
    ActionType,
    AnatomicalDirection,
    FragmentIdentity,
    LPSRotation,
    LPSVector,
    SemanticMovement,
    SurgicalAction,
)
from shared.kinematics import (
    euler_to_rotation_matrix,
    resolve_movement,
    resolve_movements,
    rotation_matrix_to_euler,
    surgical_action_to_sim_request,
    valgus_to_rotation_matrix,
    varus_to_rotation_matrix,
    flexion_to_rotation_matrix,
    internal_rotation_to_matrix,
)


def _frag(fid: str = "test_frag", color: str = "Green") -> FragmentIdentity:
    return FragmentIdentity(fragment_id=fid, color_code=color, volume_mm3=1000)


class TestResolveMovement:
    """Test single anatomical movement -> LPS vector."""

    def test_distal_is_negative_z(self):
        t, r = resolve_movement(SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=5.0, side="R"))
        assert t.z == pytest.approx(-5.0)
        assert t.x == 0 and t.y == 0

    def test_proximal_is_positive_z(self):
        t, r = resolve_movement(SemanticMovement(direction=AnatomicalDirection.PROXIMAL, magnitude=3.0, side="R"))
        assert t.z == pytest.approx(3.0)

    def test_anterior_is_negative_y(self):
        t, r = resolve_movement(SemanticMovement(direction=AnatomicalDirection.ANTERIOR, magnitude=2.0, side="R"))
        assert t.y == pytest.approx(-2.0)

    def test_posterior_is_positive_y(self):
        t, r = resolve_movement(SemanticMovement(direction=AnatomicalDirection.POSTERIOR, magnitude=1.0, side="R"))
        assert t.y == pytest.approx(1.0)

    def test_medial_right_is_positive_x(self):
        t, _ = resolve_movement(SemanticMovement(direction=AnatomicalDirection.MEDIAL, magnitude=4.0, side="R"))
        assert t.x == pytest.approx(4.0)

    def test_medial_left_is_negative_x(self):
        """Left-side medial flips to -X."""
        t, _ = resolve_movement(SemanticMovement(direction=AnatomicalDirection.MEDIAL, magnitude=4.0, side="L"))
        assert t.x == pytest.approx(-4.0)

    def test_lateral_right_is_negative_x(self):
        t, _ = resolve_movement(SemanticMovement(direction=AnatomicalDirection.LATERAL, magnitude=3.0, side="R"))
        assert t.x == pytest.approx(-3.0)

    def test_lateral_left_is_positive_x(self):
        t, _ = resolve_movement(SemanticMovement(direction=AnatomicalDirection.LATERAL, magnitude=3.0, side="L"))
        assert t.x == pytest.approx(3.0)

    def test_valgus_is_rotation(self):
        _, r = resolve_movement(SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="R"))
        assert r.y_deg == pytest.approx(-5.0)
        assert r.x_deg == 0 and r.z_deg == 0

    def test_varus_is_opposite_valgus(self):
        _, r = resolve_movement(SemanticMovement(direction=AnatomicalDirection.VARUS, magnitude=5.0, side="R"))
        assert r.y_deg == pytest.approx(5.0)

    def test_valgus_left_flipped(self):
        _, r_R = resolve_movement(SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="R"))
        _, r_L = resolve_movement(SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="L"))
        assert r_R.y_deg == pytest.approx(-r_L.y_deg)

    def test_flexion(self):
        _, r = resolve_movement(SemanticMovement(direction=AnatomicalDirection.FLEXION, magnitude=10.0, side="R"))
        assert r.x_deg == pytest.approx(10.0)

    def test_internal_rotation(self):
        _, r = resolve_movement(SemanticMovement(direction=AnatomicalDirection.INTERNAL_ROTATION, magnitude=15.0, side="R"))
        assert r.z_deg == pytest.approx(15.0)


class TestResolveMultipleMovements:
    """Test compound movements sum correctly."""

    def test_distal_plus_valgus(self):
        movements = [
            SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=2.0, side="R"),
            SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=3.0, side="R"),
        ]
        t, r = resolve_movements(movements)
        assert t.z == pytest.approx(-2.0)
        assert r.y_deg == pytest.approx(-3.0)

    def test_three_translations_sum(self):
        movements = [
            SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=1.0, side="R"),
            SemanticMovement(direction=AnatomicalDirection.MEDIAL, magnitude=2.0, side="R"),
            SemanticMovement(direction=AnatomicalDirection.ANTERIOR, magnitude=3.0, side="R"),
        ]
        t, r = resolve_movements(movements)
        assert t.x == pytest.approx(2.0)   # medial R = +X
        assert t.y == pytest.approx(-3.0)  # anterior = -Y
        assert t.z == pytest.approx(-1.0)  # distal = -Z

    def test_empty_movements(self):
        t, r = resolve_movements([])
        assert t.x == 0 and t.y == 0 and t.z == 0
        assert r.x_deg == 0 and r.y_deg == 0 and r.z_deg == 0


class TestEulerRotationMatrix:
    def test_identity(self):
        rm = euler_to_rotation_matrix(0, 0, 0)
        assert rm.r00 == pytest.approx(1.0)
        assert rm.r11 == pytest.approx(1.0)
        assert rm.r22 == pytest.approx(1.0)

    def test_90deg_x(self):
        rm = euler_to_rotation_matrix(90, 0, 0)
        assert rm.r11 == pytest.approx(0.0, abs=1e-10)
        assert rm.r22 == pytest.approx(0.0, abs=1e-10)

    def test_roundtrip(self):
        """Euler -> matrix -> Euler should recover original angles."""
        original = LPSRotation(x_deg=15.0, y_deg=-8.0, z_deg=22.0)
        rm = euler_to_rotation_matrix(original.x_deg, original.y_deg, original.z_deg)
        recovered = rotation_matrix_to_euler(rm)
        assert recovered.x_deg == pytest.approx(original.x_deg, abs=0.01)
        assert recovered.y_deg == pytest.approx(original.y_deg, abs=0.01)
        assert recovered.z_deg == pytest.approx(original.z_deg, abs=0.01)

    def test_small_angle_roundtrip(self):
        """Typical surgical corrections are < 10 degrees."""
        for x, y, z in [(3, -2, 5), (-1.5, 4.0, -0.5), (0, 0, 7)]:
            rm = euler_to_rotation_matrix(x, y, z)
            rec = rotation_matrix_to_euler(rm)
            assert rec.x_deg == pytest.approx(x, abs=0.01)
            assert rec.y_deg == pytest.approx(y, abs=0.01)
            assert rec.z_deg == pytest.approx(z, abs=0.01)


class TestConvenienceFunctions:
    def test_valgus_right(self):
        rm = valgus_to_rotation_matrix("R", 5.0)
        assert rm.r00 != 1.0  # not identity

    def test_varus_right(self):
        rm = varus_to_rotation_matrix("R", 5.0)
        euler = rotation_matrix_to_euler(rm)
        assert euler.y_deg == pytest.approx(5.0, abs=0.01)

    def test_flexion(self):
        rm = flexion_to_rotation_matrix("R", 10.0)
        euler = rotation_matrix_to_euler(rm)
        assert euler.x_deg == pytest.approx(10.0, abs=0.01)

    def test_internal_rotation(self):
        rm = internal_rotation_to_matrix("R", 20.0)
        euler = rotation_matrix_to_euler(rm)
        assert euler.z_deg == pytest.approx(20.0, abs=0.01)


class TestSurgicalActionToSimRequest:
    def test_basic_translation(self):
        action = SurgicalAction(
            action_type=ActionType.TRANSLATE,
            target=_frag(),
            clinical_intent="Move 5mm distal",
            movements=[SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=5.0, side="R")],
        )
        req = surgical_action_to_sim_request(action, case_id="c001")
        assert req.case_id == "c001"
        assert req.fragment_id == "test_frag"
        assert req.translation.z == pytest.approx(-5.0)
        assert req.branch == "LLM_Hypothesis"

    def test_rotation_generates_matrix(self):
        action = SurgicalAction(
            action_type=ActionType.ROTATE,
            target=_frag(),
            clinical_intent="5 deg valgus",
            movements=[SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="R")],
        )
        req = surgical_action_to_sim_request(action)
        # Rotation matrix should not be identity
        assert req.rotation.r00 != 1.0 or req.rotation.r11 != 1.0

    def test_pre_resolved_bypasses_movements(self):
        """If translation_mm is already set, don't re-resolve."""
        action = SurgicalAction(
            action_type=ActionType.TRANSLATE,
            target=_frag(),
            clinical_intent="Pre-resolved",
            translation_mm=LPSVector(x=1.0, y=2.0, z=3.0),
        )
        req = surgical_action_to_sim_request(action)
        assert req.translation.x == pytest.approx(1.0)
        assert req.translation.y == pytest.approx(2.0)
        assert req.translation.z == pytest.approx(3.0)

    def test_hardware_passthrough(self):
        action = SurgicalAction(
            action_type=ActionType.INSERT_K_WIRE,
            target=_frag(),
            clinical_intent="Insert K-wire",
            hardware_id="k_wire_1.6mm",
            hardware_position=LPSVector(x=10, y=5, z=20),
        )
        req = surgical_action_to_sim_request(action)
        assert req.place_hardware == "k_wire_1.6mm"
        assert req.hardware_position.x == pytest.approx(10.0)
