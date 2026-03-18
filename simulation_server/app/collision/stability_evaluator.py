"""Stability Evaluator — computes fragment stability and delta-stability on clamp removal.

Evaluates how stable a fracture reduction is given the current fixation
(clamps, K-wires, plates). Computes what happens to stability when
a temporary clamp is removed — critical for deciding the safe sequence
of temporary-to-permanent fixation conversion.

Stability model:
    Each fixation point contributes stiffness (N/mm) based on:
    - Clamps: force / jaw_span (spring model)
    - K-wires: bending stiffness (EI/L^3)
    - Plate + screws: very high stiffness (assumed rigid)

    Total junction stability = sum of individual fixation stiffnesses.
    Delta stability = (after_removal - before) / before * 100%.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.surgical_plan_v3 import (
    ClampPlacement,
    DeltaStability,
    StabilityMetric,
    CLAMP_LIBRARY,
)

logger = logging.getLogger("osteotwin.stability")

# Material constants
KWIRE_YOUNGS_MODULUS_MPA = 200000  # Stainless steel ~200 GPa
KWIRE_STIFFNESS_FACTOR = 3.0       # 3EI/L^3 for cantilever beam model


class StabilityEvaluator:
    """Evaluates fracture fixation stability and delta-stability on clamp removal."""

    def __init__(self, min_safe_stability: float = 50.0):
        """
        Args:
            min_safe_stability: Minimum acceptable stability (N/mm) after clamp removal.
        """
        self.min_safe_stability = min_safe_stability

    def compute_clamp_stiffness(self, clamp: ClampPlacement) -> float:
        """Estimate stiffness contribution of a single clamp (N/mm).

        Model: clamp acts as a spring with stiffness proportional to
        applied force / jaw compliance.
        """
        spec = CLAMP_LIBRARY.get(clamp.clamp_id)
        if not spec or not clamp.is_active:
            return 0.0

        # Stiffness = applied_force / estimated_jaw_deflection
        # Typical jaw compliance ~0.5mm at max force
        jaw_compliance_mm = 0.5
        force = clamp.applied_force_n if clamp.applied_force_n > 0 else spec.force_at_typical_use_n
        stiffness = force / jaw_compliance_mm
        return stiffness

    def compute_kwire_stiffness(
        self,
        diameter_mm: float,
        length_mm: float,
        bicortical: bool = True,
    ) -> float:
        """Estimate stiffness contribution of a K-wire (N/mm).

        Model: cantilever beam bending stiffness = 3EI/L^3
        For bicortical fixation, multiply by 2 (fixed-fixed beam).
        """
        radius = diameter_mm / 2
        I = math.pi * radius ** 4 / 4  # moment of inertia (mm^4)
        stiffness = KWIRE_STIFFNESS_FACTOR * KWIRE_YOUNGS_MODULUS_MPA * I / (length_mm ** 3)
        if bicortical:
            stiffness *= 4  # fixed-fixed vs cantilever

        return stiffness

    def compute_plate_stiffness(
        self,
        num_screws_per_fragment: int = 3,
    ) -> float:
        """Estimate stiffness of plate + screw fixation (N/mm).

        Plate fixation is effectively rigid — returns very high stiffness.
        """
        # Each screw contributes ~500 N/mm in pullout stiffness
        # Plate bridging adds bending stiffness
        per_screw = 500.0
        plate_bending = 1000.0
        return plate_bending + per_screw * num_screws_per_fragment

    def compute_junction_stability(
        self,
        clamps: list[ClampPlacement],
        kwires: Optional[list[dict]] = None,
        plate_screws: Optional[int] = None,
        fragment_a_id: str = "",
        fragment_b_id: str = "",
    ) -> StabilityMetric:
        """Compute total stability at a fragment-fragment junction.

        Args:
            clamps: Active clamps at this junction
            kwires: K-wire specs [{diameter_mm, length_mm, bicortical}]
            plate_screws: Number of screws per fragment if plate is placed
        """
        total_stiffness = 0.0
        fixation_parts = []

        # Clamp contributions
        for clamp in clamps:
            if clamp.is_active:
                s = self.compute_clamp_stiffness(clamp)
                total_stiffness += s
                if s > 0:
                    fixation_parts.append("clamp")

        # K-wire contributions
        if kwires:
            for kw in kwires:
                s = self.compute_kwire_stiffness(
                    kw.get("diameter_mm", 1.6),
                    kw.get("length_mm", 40),
                    kw.get("bicortical", True),
                )
                total_stiffness += s
                fixation_parts.append("kwire")

        # Plate contributions
        if plate_screws and plate_screws > 0:
            s = self.compute_plate_stiffness(plate_screws)
            total_stiffness += s
            fixation_parts.append("plate_screws")

        # Determine fixation method description
        unique_parts = sorted(set(fixation_parts))
        method = "+".join(unique_parts) if unique_parts else "none"

        # Estimate displacement under load (10N physiological load)
        load_n = 10.0
        displacement = load_n / total_stiffness if total_stiffness > 0 else float("inf")

        # Risk level
        if total_stiffness < self.min_safe_stability:
            risk = "unstable"
        elif total_stiffness < self.min_safe_stability * 2:
            risk = "marginal"
        else:
            risk = "safe"

        return StabilityMetric(
            fragment_a_id=fragment_a_id,
            fragment_b_id=fragment_b_id,
            stability_n_per_mm=round(total_stiffness, 1),
            max_displacement_under_load_mm=round(displacement, 3),
            fixation_method=method,
            risk_level=risk,
        )

    def compute_delta_stability(
        self,
        clamp_to_remove: ClampPlacement,
        all_clamps: list[ClampPlacement],
        kwires: Optional[list[dict]] = None,
        plate_screws: Optional[int] = None,
        fragment_a_id: str = "",
        fragment_b_id: str = "",
    ) -> DeltaStability:
        """Compute what happens to stability when a specific clamp is removed.

        Computes stability before and after removal.
        """
        # Before: all fixation active
        before = self.compute_junction_stability(
            all_clamps, kwires, plate_screws, fragment_a_id, fragment_b_id
        )

        # After: clamp deactivated
        after_clamps = []
        for c in all_clamps:
            if c.placement_id == clamp_to_remove.placement_id:
                deactivated = c.model_copy()
                deactivated.is_active = False
                after_clamps.append(deactivated)
            else:
                after_clamps.append(c)

        after = self.compute_junction_stability(
            after_clamps, kwires, plate_screws, fragment_a_id, fragment_b_id
        )

        delta_pct = (
            (after.stability_n_per_mm - before.stability_n_per_mm)
            / max(before.stability_n_per_mm, 0.01) * 100
        )

        safe = after.stability_n_per_mm >= self.min_safe_stability
        notes = ""
        if not safe:
            notes = (
                f"Removing {clamp_to_remove.placement_id} drops stability to "
                f"{after.stability_n_per_mm:.0f} N/mm (below {self.min_safe_stability} threshold). "
                f"Add K-wire or plate fixation before removing this clamp."
            )

        return DeltaStability(
            removed_clamp_id=clamp_to_remove.placement_id,
            before_stability_n_per_mm=before.stability_n_per_mm,
            after_stability_n_per_mm=after.stability_n_per_mm,
            delta_pct=round(delta_pct, 1),
            is_safe_to_remove=safe,
            minimum_required_n_per_mm=self.min_safe_stability,
            notes=notes,
        )
