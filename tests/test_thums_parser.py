"""Unit tests for THUMS v7.1 parser and mesh converter.

Tests parsing logic, anatomical map generation, unit conversion,
and mass validation against known THUMS properties.
"""

from __future__ import annotations

import json

import pytest

from fea.thums_parser import (
    parse_fields,
    safe_float,
    safe_int,
    region_from_part_id,
    parse_mat_elastic,
    parse_mat_muscle,
    parse_mat_piecewise_linear,
    build_anatomical_map,
    THUMSModel,
    MaterialCard,
    PartCard,
)


class TestFieldParsing:
    def test_fixed_width_10(self):
        line = "  81000000 8.615E-10     160.0      0.45      32.0"
        fields = parse_fields(line, 10)
        assert fields[0] == "81000000"
        assert fields[1] == "8.615E-10"

    def test_safe_float(self):
        assert safe_float("3.14") == pytest.approx(3.14)
        assert safe_float("1.0E-9") == pytest.approx(1e-9)
        assert safe_float("bad", 0.0) == 0.0

    def test_safe_int(self):
        assert safe_int("42") == 42
        assert safe_int("8.615E-10") == 0  # not an int
        assert safe_int("bad", -1) == -1


class TestRegionMapping:
    def test_lower_extremity_right(self):
        assert region_from_part_id(81000000) == "lower_extremity_right"
        assert region_from_part_id(81999999) == "lower_extremity_right"

    def test_lower_extremity_left(self):
        assert region_from_part_id(82000000) == "lower_extremity_left"

    def test_upper_extremity_right(self):
        assert region_from_part_id(85000100) == "upper_extremity_right"

    def test_upper_extremity_left(self):
        assert region_from_part_id(86000000) == "upper_extremity_left"

    def test_muscle(self):
        assert region_from_part_id(7121100) == "muscle"
        assert region_from_part_id(7500001) == "muscle"

    def test_head(self):
        assert region_from_part_id(88000000) == "head"

    def test_thorax(self):
        assert region_from_part_id(89000000) == "thorax"


class TestMaterialParsers:
    def test_parse_mat_elastic(self):
        lines = ["  85000600    1.0E-9      40.0      0.45"]
        mat = parse_mat_elastic("*MAT_ELASTIC", lines)
        assert mat.mat_id == 85000600
        assert mat.density_ton_mm3 == pytest.approx(1e-9)
        assert mat.density_kg_mm3 == pytest.approx(1e-6)  # ton/mm3 * 1e3
        assert mat.youngs_modulus_mpa == pytest.approx(40.0)
        assert mat.poisson_ratio == pytest.approx(0.45)

    def test_parse_mat_piecewise_linear(self):
        lines = ["  81000100    2.0E-9   17300.0       0.3      34.5   15600.0"]
        mat = parse_mat_piecewise_linear("*MAT_PIECEWISE_LINEAR_PLASTICITY", lines)
        assert mat.mat_id == 81000100
        assert mat.youngs_modulus_mpa == pytest.approx(17300.0)
        assert mat.poisson_ratio == pytest.approx(0.3)
        assert mat.yield_stress_mpa == pytest.approx(34.5)
        assert mat.density_kg_mm3 == pytest.approx(2e-6)

    def test_parse_mat_muscle(self):
        lines = ["   7121100   3.0E-12       1.0       1.0      0.55       0.0       0.0     0.002"]
        mat = parse_mat_muscle("*MAT_MUSCLE", lines)
        assert mat.mat_id == 7121100
        assert mat.peak_isometric_stress == pytest.approx(0.55)
        assert mat.damping == pytest.approx(0.002)
        assert mat.density_ton_mm3 == pytest.approx(3e-12)

    def test_unit_conversion_density(self):
        """THUMS ton/mm3 -> OsteoTwin kg/mm3 (multiply by 1000)."""
        lines = ["  89000001    2.0E-9     100.0      0.30"]
        mat = parse_mat_elastic("*MAT_ELASTIC", lines)
        # 2.0E-9 ton/mm3 = 2.0E-6 kg/mm3
        assert mat.density_kg_mm3 == pytest.approx(2.0e-6)


class TestAnatomicalMapBuild:
    def test_builds_from_model(self):
        model = THUMSModel(subject="TEST")
        model.materials[100] = MaterialCard(
            mat_id=100, mat_type="*MAT_ELASTIC",
            density_ton_mm3=1e-9, density_kg_mm3=1e-6,
            youngs_modulus_mpa=40.0, poisson_ratio=0.45,
        )
        model.parts[85000600] = PartCard(
            part_id=85000600, section_id=1, mat_id=100,
            title="R_CAPITATE_SPON", region="upper_extremity_right",
        )
        entries = build_anatomical_map(model)
        assert len(entries) == 1
        assert entries[0]["part_id"] == 85000600
        assert entries[0]["mat_type"] == "*MAT_ELASTIC"
        assert entries[0]["youngs_modulus_mpa"] == 40.0


class TestTHUMSParsedOutput:
    """Tests against actual parsed THUMS data (requires prior parse run)."""

    def test_anatomical_map_exists(self, thums_output_dir):
        path = thums_output_dir / "thums_anatomical_map.json"
        assert path.exists()
        with open(path) as f:
            data = json.load(f)
        assert len(data) > 2000, "Expected 2000+ parts in AM50"

    def test_model_summary(self, thums_output_dir):
        path = thums_output_dir / "model_summary.json"
        assert path.exists()
        with open(path) as f:
            s = json.load(f)
        assert s["total_parts"] > 2000
        assert s["total_nodes"] > 800000
        assert "*MAT_MUSCLE" in s["material_type_counts"]

    def test_extremity_parts(self, thums_output_dir):
        path = thums_output_dir / "extremity_parts.json"
        assert path.exists()
        with open(path) as f:
            e = json.load(f)
        assert len(e["upper_extremity"]) >= 100
        assert len(e["lower_extremity"]) >= 100
        assert len(e["extremity_muscles"]) >= 200

    def test_bone_material_constants(self, thums_output_dir):
        """Verify known material constants from THUMS manual."""
        with open(thums_output_dir / "thums_anatomical_map.json") as f:
            parts = json.load(f)
        by_id = {p["part_id"]: p for p in parts}

        # Femur cortical: E ~ 17300 MPa (from mat_bone_no_fracture.k)
        femur_cort = by_id.get(81000100)
        if femur_cort and femur_cort["youngs_modulus_mpa"]:
            assert femur_cort["youngs_modulus_mpa"] == pytest.approx(17300.0, rel=0.01)
            assert femur_cort["poisson_ratio"] == pytest.approx(0.3)
            assert femur_cort["density_kg_mm3"] == pytest.approx(2e-6, rel=0.01)

        # Humerus cortical: E ~ 11000 MPa
        humerus_cort = by_id.get(85000100)
        if humerus_cort and humerus_cort["youngs_modulus_mpa"]:
            assert humerus_cort["youngs_modulus_mpa"] == pytest.approx(11000.0, rel=0.05)

    def test_no_zero_density_bones(self, thums_output_dir):
        """All bone parts should have non-zero density."""
        with open(thums_output_dir / "thums_anatomical_map.json") as f:
            parts = json.load(f)
        bone_mats = {"*MAT_PIECEWISE_LINEAR_PLASTICITY", "*MAT_ELASTIC"}
        bones = [p for p in parts if p["mat_type"] in bone_mats]
        zero_density = [p for p in bones if not p.get("density_kg_mm3") or p["density_kg_mm3"] == 0]
        assert len(zero_density) == 0, f"{len(zero_density)} bone parts have zero density"
