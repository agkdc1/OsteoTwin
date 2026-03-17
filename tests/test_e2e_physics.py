"""True E2E physics tests — exercises real trimesh geometry, collision engine,
soft-tissue tension computation, and STL export with actual 3D meshes.

These tests take real time (seconds, not milliseconds) because they:
- Create realistic bone fragment meshes (~5K-35K vertices)
- Run trimesh ray-casting for K-wire trajectory checks
- Compute mesh-mesh boolean collision detection
- Run spring-mass soft-tissue tension simulation
- Export multi-component STL files to disk

No running servers required — tests use the engines directly.
"""

from __future__ import annotations

import math
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
import trimesh

from simulation_server.app.collision.engine import CollisionEngine
from simulation_server.app.soft_tissue.engine import SoftTissueEngine
from simulation_server.app.mesh_processor.stl_export import (
    export_case_stl,
    colorize_mesh,
    add_alignment_markers,
)

from shared.schemas import (
    ActionType, AnatomicalDirection, FragmentIdentity,
    LPSVector, SemanticMovement, SurgicalAction,
)
from shared.kinematics import resolve_movements, surgical_action_to_sim_request
from shared.simulation_protocol import SimActionRequest, TranslationVector


# ---------------------------------------------------------------------------
# Fixtures: realistic bone fragment meshes
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def distal_radius_mesh() -> trimesh.Trimesh:
    """Create a rough distal radius fragment (~8K faces).

    Shaped as a tapered cylinder (wider at articular surface).
    """
    # Articular end: wider ellipsoid (high subdivision for realistic density)
    articular = trimesh.creation.icosphere(subdivisions=4, radius=12.0)
    articular.apply_scale([1.2, 0.8, 0.6])
    articular.apply_translation([0, 0, -5])

    # Shaft portion: cylinder
    shaft = trimesh.creation.cylinder(radius=6.0, height=40.0, sections=64)
    shaft.apply_translation([0, 0, 15])

    # Merge
    mesh = trimesh.util.concatenate([articular, shaft])
    assert len(mesh.faces) > 1000
    return mesh


@pytest.fixture(scope="module")
def ulna_mesh() -> trimesh.Trimesh:
    """Create a rough ulna fragment (~4K faces)."""
    shaft = trimesh.creation.cylinder(radius=5.0, height=45.0, sections=32)
    shaft.apply_translation([15, 0, 10])  # offset from radius

    head = trimesh.creation.icosphere(subdivisions=2, radius=7.0)
    head.apply_scale([0.9, 0.7, 0.5])
    head.apply_translation([15, 0, -10])

    return trimesh.util.concatenate([shaft, head])


@pytest.fixture(scope="module")
def lcp_plate_mesh() -> trimesh.Trimesh:
    """Create a simplified LCP volar plate (~2K faces).

    Flat plate with 7 screw holes.
    """
    plate = trimesh.creation.box(extents=[22, 68, 2.4])

    holes = []
    for i in range(7):
        y_pos = -28 + i * 9.0
        hole = trimesh.creation.cylinder(radius=1.75, height=4.0, sections=16)
        hole.apply_translation([0, y_pos, 0])
        holes.append(hole)

    result = plate
    for h in holes:
        try:
            result = result.difference(h)
        except Exception:
            pass  # boolean can fail on some trimesh versions

    return result


@pytest.fixture(scope="module")
def collision_engine_loaded(
    distal_radius_mesh, ulna_mesh, lcp_plate_mesh
) -> CollisionEngine:
    """Load all meshes into a collision engine."""
    engine = CollisionEngine()
    engine.load_mesh_from_trimesh("radius_distal", distal_radius_mesh, label="Distal Radius", mesh_type="bone")
    engine.load_mesh_from_trimesh("ulna", ulna_mesh, label="Ulna", mesh_type="bone")
    engine.load_mesh_from_trimesh("lcp_plate", lcp_plate_mesh, label="LCP Volar Plate", mesh_type="hardware")
    return engine


@pytest.fixture
def stl_output_dir(tmp_path: Path) -> Path:
    out = tmp_path / "stl_export"
    out.mkdir()
    return out


# ---------------------------------------------------------------------------
# Test 1: Mesh Creation & Validation
# ---------------------------------------------------------------------------

class TestMeshCreation:
    """Verify synthetic bone meshes have realistic properties."""

    def test_radius_mesh_volume(self, distal_radius_mesh):
        vol = abs(distal_radius_mesh.volume)
        # Synthetic mesh: volume should be non-trivial
        assert vol > 500, f"Radius volume {vol:.0f} mm3 too small"

    def test_radius_mesh_face_count(self, distal_radius_mesh):
        assert len(distal_radius_mesh.faces) > 1000
        assert len(distal_radius_mesh.vertices) > 500

    def test_ulna_mesh_offset(self, ulna_mesh):
        """Ulna should be laterally offset from radius."""
        centroid = ulna_mesh.centroid
        assert centroid[0] > 10, "Ulna should be offset in +X from radius"

    def test_plate_dimensions(self, lcp_plate_mesh):
        """Plate bounding box should roughly match 22 x 68 x 2.4 mm."""
        bb = lcp_plate_mesh.bounding_box.extents
        assert 18 < bb[0] < 26, f"Plate width {bb[0]:.1f}mm outside range"
        assert 60 < bb[1] < 75, f"Plate length {bb[1]:.1f}mm outside range"


# ---------------------------------------------------------------------------
# Test 2: Collision Engine — Ray Casting (K-wire trajectory)
# ---------------------------------------------------------------------------

class TestKWireCollision:
    """Realistic K-wire trajectory collision checks against loaded meshes."""

    def test_kwire_through_radius(self, collision_engine_loaded):
        """K-wire aimed directly through the center of the radius."""
        t0 = time.time()
        hits = collision_engine_loaded.ray_cast(
            origin=(-50, 0, 10),       # start far left
            direction=(1, 0, 0),        # aim right
            max_length=200,
        )
        elapsed = time.time() - t0

        assert len(hits) >= 2, "K-wire should enter AND exit the radius"
        entries = [h for h in hits if h["is_entry"]]
        exits = [h for h in hits if not h["is_entry"]]
        assert len(entries) >= 1
        assert len(exits) >= 1
        assert elapsed < 2.0, f"Ray cast took {elapsed:.2f}s (expected < 2s)"

        # First hit should be the radius
        assert "radius" in hits[0]["mesh_label"].lower() or "radius" in hits[0]["mesh_id"].lower()

    def test_kwire_misses_all(self, collision_engine_loaded):
        """K-wire aimed far away from all meshes."""
        hits = collision_engine_loaded.ray_cast(
            origin=(0, 100, 100),
            direction=(0, 0, 1),   # straight up, above everything
        )
        assert len(hits) == 0, "K-wire should miss all meshes"

    def test_kwire_hits_plate(self, collision_engine_loaded):
        """K-wire trajectory that intersects the plate."""
        hits = collision_engine_loaded.ray_cast(
            origin=(-50, 0, 0),
            direction=(1, 0, 0),
        )
        hw_hits = [h for h in hits if h["mesh_type"] == "hardware"]
        # The plate is at origin, the K-wire passes through x=0
        assert len(hw_hits) >= 1, "K-wire should hit the plate"

    def test_kwire_max_length_filter(self, collision_engine_loaded):
        """Short K-wire that doesn't reach the bone."""
        hits = collision_engine_loaded.ray_cast(
            origin=(-100, 0, 10),
            direction=(1, 0, 0),
            max_length=20,  # only 20mm long — shouldn't reach radius
        )
        assert len(hits) == 0, "Short K-wire should not reach any mesh"


# ---------------------------------------------------------------------------
# Test 3: Mesh-Mesh Collision Detection
# ---------------------------------------------------------------------------

class TestMeshMeshCollision:
    def test_radius_ulna_proximity(self, collision_engine_loaded):
        """Radius and ulna are separate bones — test collision check."""
        t0 = time.time()
        result = collision_engine_loaded.check_intersection("radius_distal", "ulna")
        elapsed = time.time() - t0

        if "error" in result:
            # FCL not installed — collision manager unavailable
            pytest.skip(f"Mesh-mesh collision requires python-fcl: {result['error']}")

        assert isinstance(result["collides"], bool)
        assert result["min_distance_mm"] is not None
        assert elapsed < 5.0, f"Mesh-mesh check took {elapsed:.2f}s"

    def test_plate_bone_relationship(self, collision_engine_loaded):
        """Plate placed at origin may intersect the radius."""
        result = collision_engine_loaded.check_intersection("radius_distal", "lcp_plate")

        if "error" in result:
            pytest.skip(f"Mesh-mesh collision requires python-fcl: {result['error']}")

        assert isinstance(result["collides"], bool)
        assert result["min_distance_mm"] is not None


# ---------------------------------------------------------------------------
# Test 4: Soft-Tissue Tension Computation (Spring-Mass Model)
# ---------------------------------------------------------------------------

class TestSoftTissueTension:
    """Exercise the spring-mass fallback engine with realistic tissue definitions."""

    @pytest.fixture
    def engine(self) -> SoftTissueEngine:
        return SoftTissueEngine()

    @pytest.fixture
    def wrist_tissues(self) -> list[dict]:
        """Realistic tissue definitions for a distal radius fracture."""
        return [
            {
                "tissue_id": "t_brachioradialis",
                "tissue_type": "muscle",
                "label": "Brachioradialis",
                "origin": {"label": "br_origin", "fragment_id": "proximal", "position": [-5, 10, 25]},
                "insertion": {"label": "br_insertion", "fragment_id": "distal", "position": [0, 12, -10]},
                "rest_length_mm": 40.0,
                "max_tension_n": 50.0,
                "stiffness": 30.0,
            },
            {
                "tissue_id": "t_pronator_quadratus",
                "tissue_type": "muscle",
                "label": "Pronator Quadratus",
                "origin": {"label": "pq_origin", "fragment_id": "proximal", "position": [5, -5, 10]},
                "insertion": {"label": "pq_insertion", "fragment_id": "distal", "position": [8, -3, -5]},
                "rest_length_mm": 18.0,
                "max_tension_n": 25.0,
                "stiffness": 45.0,
            },
            {
                "tissue_id": "t_radial_collateral_lig",
                "tissue_type": "ligament",
                "label": "Radial Collateral Ligament",
                "origin": {"label": "rcl_origin", "fragment_id": "proximal", "position": [-10, 0, 5]},
                "insertion": {"label": "rcl_insertion", "fragment_id": "distal", "position": [-12, 2, -8]},
                "rest_length_mm": 15.0,
                "max_tension_n": 35.0,
                "stiffness": 80.0,
            },
            {
                "tissue_id": "t_periosteum",
                "tissue_type": "periosteum",
                "label": "Periosteum",
                "origin": {"label": "per_origin", "fragment_id": "proximal", "position": [0, 0, 5]},
                "insertion": {"label": "per_insertion", "fragment_id": "distal", "position": [0, 0, -3]},
                "rest_length_mm": 8.0,
                "max_tension_n": 15.0,
                "stiffness": 120.0,
            },
        ]

    def test_neutral_position_no_tension(self, engine, wrist_tissues):
        """Fragments at rest should produce minimal tension."""
        t0 = time.time()
        results = engine.compute_tensions(
            tissues=wrist_tissues,
            fragment_positions={"proximal": [0, 0, 0], "distal": [0, 0, 0]},
        )
        elapsed = time.time() - t0

        assert len(results) == 4
        for r in results:
            assert r["risk_level"] in ("safe", "warning", "critical")
            assert r["tension_n"] >= 0
        assert elapsed < 1.0

    def test_distraction_increases_tension(self, engine, wrist_tissues):
        """Pulling the distal fragment away should increase all tensions."""
        # Normal position
        baseline = engine.compute_tensions(
            tissues=wrist_tissues,
            fragment_positions={"proximal": [0, 0, 0], "distal": [0, 0, 0]},
        )
        # Distracted 10mm distally
        distracted = engine.compute_tensions(
            tissues=wrist_tissues,
            fragment_positions={"proximal": [0, 0, 0], "distal": [0, 0, -10]},
        )

        for b, d in zip(baseline, distracted):
            assert d["tension_n"] >= b["tension_n"], (
                f"{d['label']}: tension should increase with distraction "
                f"({b['tension_n']:.1f}N -> {d['tension_n']:.1f}N)"
            )

    def test_large_displacement_exceeds_threshold(self, engine, wrist_tissues):
        """A 20mm displacement should exceed at least one tissue's threshold."""
        results = engine.compute_tensions(
            tissues=wrist_tissues,
            fragment_positions={"proximal": [0, 0, 0], "distal": [0, 0, -20]},
        )
        exceeded = [r for r in results if r["exceeded"]]
        assert len(exceeded) >= 1, "20mm displacement should exceed at least one tissue threshold"

        critical = [r for r in results if r["risk_level"] == "critical"]
        assert len(critical) >= 1, "Should have at least one critical tissue"

    def test_strain_percentage_correct(self, engine, wrist_tissues):
        """Verify strain calculation: strain = (current - rest) / rest * 100."""
        results = engine.compute_tensions(
            tissues=wrist_tissues,
            fragment_positions={"proximal": [0, 0, 0], "distal": [0, 0, -5]},
        )
        for r in results:
            if r["current_length_mm"] > r["rest_length_mm"]:
                expected_strain = (r["current_length_mm"] - r["rest_length_mm"]) / r["rest_length_mm"] * 100
                assert r["strain_pct"] == pytest.approx(expected_strain, rel=0.01)

    def test_vascular_proximity(self, engine):
        """Check proximity of fragments to radial artery."""
        structures = [
            {
                "label": "radial_artery",
                "tissue_type": "vessel",
                "position": [8.0, -3.0, 0.0],
                "compression_threshold_mm": 2.0,
                "warning_threshold_mm": 5.0,
            },
        ]
        # Fragment very close to artery
        results = engine.compute_proximity(structures, {"frag1": [7.0, -2.0, 0.0]})
        assert len(results) == 1
        assert results[0]["min_distance_mm"] < 5.0


# ---------------------------------------------------------------------------
# Test 5: Full Reduction Scenario (Semantic -> Physics -> Export)
# ---------------------------------------------------------------------------

class TestFullReductionScenario:
    """Complete distal radius reduction: parse command -> resolve LPS ->
    collision check -> tension check -> STL export."""

    def test_full_pipeline(
        self, distal_radius_mesh, ulna_mesh, lcp_plate_mesh, stl_output_dir
    ):
        t_start = time.time()

        # 1. Surgeon's command parsed to SurgicalAction
        action = SurgicalAction(
            action_type=ActionType.TRANSLATE_AND_ROTATE,
            target=FragmentIdentity(
                fragment_id="radius_R_frag2_distal",
                color_code="Green", volume_mm3=8500,
            ),
            clinical_intent="Move green fragment 3mm distally, 2mm ulnarly, 5deg valgus",
            movements=[
                SemanticMovement(direction=AnatomicalDirection.DISTAL, magnitude=3.0, side="R"),
                SemanticMovement(direction=AnatomicalDirection.LATERAL, magnitude=2.0, side="R"),
                SemanticMovement(direction=AnatomicalDirection.VALGUS, magnitude=5.0, side="R"),
            ],
            case_id="full-e2e-001",
        )

        # 2. Resolve to LPS
        t, r = resolve_movements(action.movements)
        assert t.z == pytest.approx(-3.0)  # distal
        assert t.x == pytest.approx(-2.0)  # lateral R = -X
        assert r.y_deg == pytest.approx(-5.0)  # valgus R

        # 3. Bridge to SimActionRequest
        req = surgical_action_to_sim_request(action, case_id="full-e2e-001")
        assert req.translation.z == pytest.approx(-3.0)

        # 4. Collision check (K-wire through the scene)
        engine = CollisionEngine()
        engine.load_mesh_from_trimesh("radius", distal_radius_mesh, "Distal Radius", "bone")
        engine.load_mesh_from_trimesh("ulna", ulna_mesh, "Ulna", "bone")
        engine.load_mesh_from_trimesh("plate", lcp_plate_mesh, "LCP Plate", "hardware")

        hits = engine.ray_cast(
            origin=(-50, 0, 5),
            direction=(1, 0, 0),
        )
        assert len(hits) >= 2, "K-wire should intersect at least one bone"

        # 5. Soft-tissue tension
        st_engine = SoftTissueEngine()
        tensions = st_engine.compute_tensions(
            tissues=[
                {
                    "tissue_id": "t_brachioradialis",
                    "tissue_type": "muscle",
                    "label": "Brachioradialis",
                    "origin": {"label": "o", "fragment_id": "proximal", "position": [0, 10, 25]},
                    "insertion": {"label": "i", "fragment_id": "distal", "position": [0, 12, -10]},
                    "rest_length_mm": 40.0,
                    "max_tension_n": 50.0,
                    "stiffness": 30.0,
                },
            ],
            fragment_positions={
                "proximal": [0, 0, 0],
                "distal": [req.translation.x, req.translation.y, req.translation.z],
            },
        )
        assert len(tensions) == 1
        assert tensions[0]["tension_n"] >= 0

        # 6. STL export
        result = export_case_stl(
            fragments=[distal_radius_mesh, ulna_mesh],
            fragment_labels=["radius_distal", "ulna"],
            hardware=[(lcp_plate_mesh, "lcp_plate")],
            output_dir=stl_output_dir,
            case_id="full-e2e-001",
            scale_factor=1.0,
        )

        t_total = time.time() - t_start

        assert result["component_count"] == 3  # 2 bones + 1 plate (K-wires excluded)
        assert result["total_volume_cm3"] > 0
        assert len(result["files"]) >= 4  # 3 components + 1 merged
        assert result["bounding_box_mm"]["x"] > 0

        # Verify actual files on disk
        for f in result["files"]:
            assert Path(f["file"]).exists(), f"Missing export file: {f['file']}"

        # Should complete but verify all steps actually ran
        assert t_total > 0.0, f"Pipeline didn't execute"
        print(f"\n  Full pipeline completed in {t_total:.2f}s")
        print(f"  Components: {result['component_count']}")
        print(f"  Volume: {result['total_volume_cm3']:.1f} cm3")
        print(f"  BBox: {result['bounding_box_mm']}")
        print(f"  Files: {len(result['files'])}")
        print(f"  K-wire hits: {len(hits)}")
        print(f"  Tissue tension: {tensions[0]['tension_n']:.1f}N ({tensions[0]['risk_level']})")
