"""Unit tests for implant schemas and CAD pipeline logic.

Covers: ManufacturerAlias, ParametricImplantSpec, QA state machine,
6-strike rule, file prefix generation.
"""

from __future__ import annotations

import pytest

from shared.implant_schemas import (
    ALIAS_DISPLAY_MAP,
    HoleSpec,
    HoleType,
    ImplantCADResult,
    ImplantQAState,
    ManufacturerAlias,
    ParametricImplantSpec,
    PlateContour,
    QAIteration,
    QAStatus,
)


class TestManufacturerAlias:
    def test_all_aliases_3_chars(self):
        for alias in ManufacturerAlias:
            assert len(alias.value) == 3, f"{alias} is not 3 characters"

    def test_display_map_covers_all(self):
        for alias in ManufacturerAlias:
            assert alias in ALIAS_DISPLAY_MAP, f"Missing display name for {alias}"

    def test_known_aliases(self):
        assert ManufacturerAlias.SYN.value == "SYN"
        assert ManufacturerAlias.STK.value == "STK"
        assert ManufacturerAlias.GEN.value == "GEN"
        assert ALIAS_DISPLAY_MAP[ManufacturerAlias.SYN] == "Synthes"


class TestParametricImplantSpec:
    def test_file_prefix_format(self):
        spec = ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.SYN,
            implant_name="LCP Volar Distal Radius Plate",
            implant_type="locking_plate",
            length_mm=68.0, width_mm=22.0, thickness_mm=2.4,
            hole_count=7,
        )
        prefix = spec.file_prefix
        assert prefix.startswith("SYN_")
        assert "7Hole" in prefix
        assert " " not in prefix  # no spaces in filename

    def test_file_prefix_no_holes(self):
        spec = ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.STK,
            implant_name="Cortical Screw 3.5mm",
            implant_type="cortical_screw",
            length_mm=20.0, width_mm=3.5, thickness_mm=3.5,
        )
        assert "Hole" not in spec.file_prefix
        assert spec.file_prefix.startswith("STK_")

    def test_holes_spec(self):
        holes = [
            HoleSpec(index=i, hole_type=HoleType.COMBINATION, diameter_mm=3.5)
            for i in range(7)
        ]
        spec = ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.SYN,
            implant_name="Test Plate",
            implant_type="locking_plate",
            length_mm=50, width_mm=10, thickness_mm=2,
            hole_count=7, holes=holes,
        )
        assert len(spec.holes) == 7
        assert spec.holes[3].hole_type == HoleType.COMBINATION

    def test_json_roundtrip(self):
        spec = ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.ACM,
            implant_name="Acu-Loc 2 Plate",
            implant_type="locking_plate",
            length_mm=72, width_mm=24, thickness_mm=2.5,
            contour=PlateContour.ANATOMIC,
            body_region="distal_radius",
            side_specific=True,
            material="Titanium",
        )
        j = spec.model_dump_json()
        spec2 = ParametricImplantSpec.model_validate_json(j)
        assert spec2.manufacturer_alias == ManufacturerAlias.ACM
        assert spec2.contour == PlateContour.ANATOMIC
        assert spec2.side_specific is True


class TestImplantQAState:
    def _make_spec(self) -> ParametricImplantSpec:
        return ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.GEN,
            implant_name="Test", implant_type="plate",
            length_mm=50, width_mm=10, thickness_mm=2,
        )

    def test_initial_state(self):
        qa = ImplantQAState(implant_spec=self._make_spec())
        assert qa.current_iteration == 0
        assert qa.rejection_count == 0
        assert not qa.is_approved
        assert not qa.is_halted

    def test_approved_on_first_try(self):
        qa = ImplantQAState(implant_spec=self._make_spec())
        qa.iterations.append(QAIteration(iteration=1, status=QAStatus.APPROVED))
        assert qa.is_approved
        assert not qa.is_halted
        assert qa.rejection_count == 0

    def test_reject_then_approve(self):
        qa = ImplantQAState(implant_spec=self._make_spec())
        qa.iterations.append(QAIteration(iteration=1, status=QAStatus.REJECTED, feedback="Bad holes"))
        qa.iterations.append(QAIteration(iteration=2, status=QAStatus.APPROVED))
        assert qa.is_approved
        assert qa.rejection_count == 1

    def test_six_strike_halt(self):
        qa = ImplantQAState(implant_spec=self._make_spec())
        for i in range(6):
            qa.iterations.append(QAIteration(
                iteration=i + 1, status=QAStatus.REJECTED,
                feedback=f"Error {i+1}",
                constraint_checklist=[f"Fix item {i+1}"],
            ))
        assert qa.is_halted
        assert qa.rejection_count == 6
        assert not qa.is_approved

    def test_five_rejections_not_halted(self):
        qa = ImplantQAState(implant_spec=self._make_spec())
        for i in range(5):
            qa.iterations.append(QAIteration(iteration=i + 1, status=QAStatus.REJECTED))
        assert not qa.is_halted
        assert qa.rejection_count == 5


class TestImplantCADResult:
    def test_approved_result(self):
        spec = ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.SYN,
            implant_name="Test", implant_type="plate",
            length_mm=50, width_mm=10, thickness_mm=2,
        )
        result = ImplantCADResult(
            spec=spec,
            scad_code="module test() {}",
            stl_path="/out/test.stl",
            qa_iterations=2,
            approved=True,
        )
        assert result.approved
        assert result.failure_report is None

    def test_halted_result(self):
        spec = ParametricImplantSpec(
            manufacturer_alias=ManufacturerAlias.GEN,
            implant_name="Failed", implant_type="plate",
            length_mm=50, width_mm=10, thickness_mm=2,
        )
        result = ImplantCADResult(
            spec=spec,
            scad_code="module fail() {}",
            qa_iterations=6,
            approved=False,
            failure_report="# 6-STRIKE FAILURE",
        )
        assert not result.approved
        assert "6-STRIKE" in result.failure_report
