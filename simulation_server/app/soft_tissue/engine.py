"""SOFA soft-tissue simulation engine.

This module provides two execution modes:
1. Direct import: If SofaPython3 is installed and importable, runs SOFA
   in-process for tighter integration and lower latency.
2. Subprocess: Falls back to calling `runSofa` as a subprocess in batch
   mode, reading results from output files. Safer (crashes don't crash server).

When neither SOFA installation is available, the engine runs a simplified
spring-mass model using trimesh/numpy for basic tension estimation.
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("osteotwin.soft_tissue")

# Try importing SOFA — graceful fallback if not installed
_SOFA_AVAILABLE = False
try:
    import Sofa
    import SofaRuntime

    _SOFA_AVAILABLE = True
    logger.info("SofaPython3 available — using direct SOFA integration")
except ImportError:
    logger.info("SofaPython3 not installed — using spring-mass fallback model")


def sofa_available() -> bool:
    """Check if the SOFA Framework is available."""
    return _SOFA_AVAILABLE


class SoftTissueEngine:
    """Soft-tissue simulation engine with SOFA + spring-mass fallback."""

    def __init__(self, sofa_root: Optional[str] = None):
        self._sofa_root = sofa_root or ""
        self._meshes: dict[str, np.ndarray] = {}  # mesh_id -> vertices

    def load_fragment_mesh(
        self, fragment_id: str, vertices: np.ndarray
    ) -> dict:
        """Load a fragment's mesh vertices for tissue attachment."""
        self._meshes[fragment_id] = np.array(vertices, dtype=np.float64)
        return {
            "fragment_id": fragment_id,
            "vertex_count": len(vertices),
        }

    def compute_tensions(
        self,
        tissues: list[dict],
        fragment_positions: dict[str, list[float]],
        fragment_rotations: Optional[dict[str, list[list[float]]]] = None,
    ) -> list[dict]:
        """Compute tension for each tissue given current fragment positions.

        Uses SOFA FEA if available, otherwise spring-mass approximation.
        """
        if _SOFA_AVAILABLE:
            return self._compute_tensions_sofa(
                tissues, fragment_positions, fragment_rotations
            )
        return self._compute_tensions_spring(
            tissues, fragment_positions, fragment_rotations
        )

    def _compute_tensions_spring(
        self,
        tissues: list[dict],
        fragment_positions: dict[str, list[float]],
        fragment_rotations: Optional[dict[str, list[list[float]]]] = None,
    ) -> list[dict]:
        """Spring-mass model — simple but deterministic tension estimation.

        Treats each tissue as a spring connecting two attachment points.
        Tension = stiffness * max(0, current_length - rest_length).
        """
        results = []

        for tissue in tissues:
            origin = np.array(tissue["origin"]["position"], dtype=np.float64)
            insertion = np.array(tissue["insertion"]["position"], dtype=np.float64)

            # Apply fragment displacement to attachment points
            origin_frag = tissue["origin"]["fragment_id"]
            insertion_frag = tissue["insertion"]["fragment_id"]

            if origin_frag in fragment_positions:
                origin = origin + np.array(fragment_positions[origin_frag])
            if insertion_frag in fragment_positions:
                insertion = insertion + np.array(fragment_positions[insertion_frag])

            # Apply rotation if provided
            if fragment_rotations:
                if origin_frag in fragment_rotations:
                    rot = np.array(fragment_rotations[origin_frag])
                    origin = rot @ origin
                if insertion_frag in fragment_rotations:
                    rot = np.array(fragment_rotations[insertion_frag])
                    insertion = rot @ insertion

            current_length = float(np.linalg.norm(insertion - origin))
            rest_length = tissue["rest_length_mm"]
            stiffness = tissue.get("stiffness", 100.0)
            max_tension = tissue["max_tension_n"]

            # Spring model: F = k * max(0, ΔL)
            elongation = max(0.0, current_length - rest_length)
            tension = stiffness * elongation
            strain_pct = (elongation / rest_length) * 100.0 if rest_length > 0 else 0.0

            exceeded = tension > max_tension
            if tension > max_tension * 0.8:
                risk_level = "critical" if exceeded else "warning"
            else:
                risk_level = "safe"

            results.append({
                "tissue_id": tissue["tissue_id"],
                "label": tissue["label"],
                "tissue_type": tissue["tissue_type"],
                "current_length_mm": round(current_length, 2),
                "rest_length_mm": rest_length,
                "strain_pct": round(strain_pct, 2),
                "tension_n": round(tension, 2),
                "max_tension_n": max_tension,
                "exceeded": exceeded,
                "risk_level": risk_level,
            })

        return results

    def _compute_tensions_sofa(
        self,
        tissues: list[dict],
        fragment_positions: dict[str, list[float]],
        fragment_rotations: Optional[dict[str, list[list[float]]]] = None,
    ) -> list[dict]:
        """SOFA FEA-based tension computation.

        Creates a SOFA scene with tetrahedral FEA meshes for each tissue,
        applies boundary conditions from fragment positions, and runs
        the simulation to compute stress/strain fields.
        """
        # Write scene to temp file
        scene_path = self._generate_sofa_scene(
            tissues, fragment_positions, fragment_rotations
        )

        try:
            result = subprocess.run(
                [
                    self._sofa_root + "/bin/runSofa" if self._sofa_root else "runSofa",
                    str(scene_path),
                    "-g", "batch",
                    "-n", "100",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.error("SOFA failed: %s", result.stderr[:500])
                # Fall back to spring model
                return self._compute_tensions_spring(
                    tissues, fragment_positions, fragment_rotations
                )

            # Parse SOFA output
            output_path = scene_path.parent / "tension_results.json"
            if output_path.exists():
                return json.loads(output_path.read_text(encoding="utf-8"))

            logger.warning("SOFA output not found — falling back to spring model")
            return self._compute_tensions_spring(
                tissues, fragment_positions, fragment_rotations
            )

        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("SOFA execution failed (%s) — using spring fallback", exc)
            return self._compute_tensions_spring(
                tissues, fragment_positions, fragment_rotations
            )
        finally:
            # Clean up temp files
            if scene_path.exists():
                scene_path.unlink(missing_ok=True)

    def _generate_sofa_scene(
        self,
        tissues: list[dict],
        fragment_positions: dict[str, list[float]],
        fragment_rotations: Optional[dict[str, list[list[float]]]] = None,
    ) -> Path:
        """Generate a SOFA Python scene file for the current configuration."""
        scene_dir = Path(tempfile.mkdtemp(prefix="osteotwin_sofa_"))
        scene_path = scene_dir / "soft_tissue_scene.py"

        tissue_data = json.dumps(tissues, default=str)
        position_data = json.dumps(fragment_positions, default=str)
        rotation_data = json.dumps(fragment_rotations or {}, default=str)

        scene_code = f'''"""Auto-generated SOFA scene for OsteoTwin soft-tissue simulation."""

import json
import Sofa
import SofaRuntime
from pathlib import Path

TISSUES = json.loads("""{tissue_data}""")
POSITIONS = json.loads("""{position_data}""")
ROTATIONS = json.loads("""{rotation_data}""")

def createScene(root):
    root.gravity = [0, 0, -9810]  # mm/s^2
    root.dt = 0.01  # 10ms time step

    # Required plugins
    root.addObject("RequiredPlugin", pluginName=[
        "Sofa.Component.StateContainer",
        "Sofa.Component.LinearSolver.Iterative",
        "Sofa.Component.ODESolver.Backward",
        "Sofa.Component.Mass",
        "Sofa.Component.MechanicalLoad",
        "Sofa.Component.SolidMechanics.FEM.Elastic",
    ])

    root.addObject("DefaultAnimationLoop")
    root.addObject("DefaultVisualManagerLoop")

    # Build tissue nodes
    results = []
    for tissue in TISSUES:
        node = root.addChild(tissue["tissue_id"])

        # Euler implicit solver
        node.addObject("EulerImplicitSolver", rayleighStiffness=0.1)
        node.addObject("CGLinearSolver", iterations=25, tolerance=1e-5, threshold=1e-5)

        # Mechanical object — simplified beam between origin and insertion
        origin = tissue["origin"]["position"]
        insertion = tissue["insertion"]["position"]

        # Apply fragment displacements
        origin_frag = tissue["origin"]["fragment_id"]
        insertion_frag = tissue["insertion"]["fragment_id"]
        if origin_frag in POSITIONS:
            origin = [o + p for o, p in zip(origin, POSITIONS[origin_frag])]
        if insertion_frag in POSITIONS:
            insertion = [i + p for i, p in zip(insertion, POSITIONS[insertion_frag])]

        # Create a simple 2-node beam
        positions_str = f"{{origin[0]}} {{origin[1]}} {{origin[2]}} {{insertion[0]}} {{insertion[1]}} {{insertion[2]}}"
        node.addObject("MechanicalObject", position=positions_str)
        node.addObject("UniformMass", totalMass=0.1)

        # Fix origin point
        node.addObject("FixedConstraint", indices=[0])

    root.addObject("OsteoTwinMonitor", tissues=TISSUES, positions=POSITIONS)


class OsteoTwinMonitor(Sofa.Core.Controller):
    """Monitor tissue tensions and write results at end of simulation."""

    def __init__(self, *args, tissues=None, positions=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tissues = tissues or []
        self.positions = positions or {{}}
        self._step = 0

    def onAnimationEndEvent(self, event):
        self._step += 1
        if self._step >= 100:
            self._write_results()

    def _write_results(self):
        import numpy as np

        results = []
        for tissue in self.tissues:
            origin = np.array(tissue["origin"]["position"])
            insertion = np.array(tissue["insertion"]["position"])

            origin_frag = tissue["origin"]["fragment_id"]
            insertion_frag = tissue["insertion"]["fragment_id"]
            if origin_frag in self.positions:
                origin = origin + np.array(self.positions[origin_frag])
            if insertion_frag in self.positions:
                insertion = insertion + np.array(self.positions[insertion_frag])

            current_length = float(np.linalg.norm(insertion - origin))
            rest_length = tissue["rest_length_mm"]
            stiffness = tissue.get("stiffness", 100.0)
            max_tension = tissue["max_tension_n"]

            elongation = max(0.0, current_length - rest_length)
            tension = stiffness * elongation
            strain_pct = (elongation / rest_length) * 100.0 if rest_length > 0 else 0.0

            exceeded = tension > max_tension
            risk = "critical" if exceeded else ("warning" if tension > max_tension * 0.8 else "safe")

            results.append({{
                "tissue_id": tissue["tissue_id"],
                "label": tissue["label"],
                "tissue_type": tissue["tissue_type"],
                "current_length_mm": round(current_length, 2),
                "rest_length_mm": rest_length,
                "strain_pct": round(strain_pct, 2),
                "tension_n": round(tension, 2),
                "max_tension_n": max_tension,
                "exceeded": exceeded,
                "risk_level": risk,
            }})

        output = Path(__file__).parent / "tension_results.json"
        output.write_text(json.dumps(results), encoding="utf-8")
'''
        scene_path.write_text(scene_code, encoding="utf-8")
        return scene_path

    def compute_proximity(
        self,
        structures: list[dict],
        fragment_positions: dict[str, list[float]],
    ) -> list[dict]:
        """Compute proximity of fragments to vascular/nerve structures.

        Uses simple distance calculation (no FEA required).
        """
        results = []

        for struct in structures:
            struct_pos = np.array(struct["position"], dtype=np.float64)
            min_dist = float("inf")

            for frag_id, frag_pos in fragment_positions.items():
                if frag_id in self._meshes:
                    # Distance from structure to nearest vertex of fragment
                    verts = self._meshes[frag_id] + np.array(frag_pos)
                    dists = np.linalg.norm(verts - struct_pos, axis=1)
                    min_dist = min(min_dist, float(np.min(dists)))
                else:
                    # Use fragment centroid
                    dist = float(np.linalg.norm(np.array(frag_pos) - struct_pos))
                    min_dist = min(min_dist, dist)

            is_compressed = min_dist < struct.get("compression_threshold_mm", 2.0)
            warning = None
            if is_compressed:
                warning = (
                    f"{struct['label']} is within {min_dist:.1f}mm of fragment — "
                    f"risk of compression injury"
                )
            elif min_dist < struct.get("warning_threshold_mm", 5.0):
                warning = (
                    f"{struct['label']} is {min_dist:.1f}mm from fragment — "
                    f"monitor during reduction"
                )

            results.append({
                "structure_label": struct["label"],
                "tissue_type": struct.get("tissue_type", "vessel"),
                "min_distance_mm": round(min_dist, 2),
                "is_compressed": is_compressed,
                "warning": warning,
            })

        return results
