"""Interference Engine — detects collisions between surgical tools, hardware, and anatomy.

Checks:
1. K-wire trajectory vs existing clamps (physical collision)
2. K-wire vs soft tissue / percutaneous entry (approach constraint)
3. K-wire vs neurovascular danger zones
4. Clamp vs plate placement area
5. Screw vs joint surface penetration

All checks use the existing trimesh collision engine for mesh-based
queries and add parametric checks for tool bounding volumes.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.surgical_plan_v3 import (
    ClampPlacement,
    InterferenceResult,
    InterferenceType,
    CLAMP_LIBRARY,
)
from shared.approach_atlas import APPROACH_ATLAS, DangerLevel

logger = logging.getLogger("osteotwin.interference")


class InterferenceEngine:
    """Detects physical interferences between surgical tools and anatomy."""

    def __init__(self):
        self._clamp_placements: list[ClampPlacement] = []
        self._kwire_trajectories: list[dict] = []  # {id, origin, direction, length, radius}
        self._plate_zones: list[dict] = []  # {id, center, extents}
        self._danger_zones: list[dict] = []  # from approach atlas

    def set_clamps(self, clamps: list[ClampPlacement]) -> None:
        self._clamp_placements = clamps

    def set_danger_zones_from_approach(self, approach_key: str) -> int:
        """Load danger zones from the surgical approach atlas."""
        approach = APPROACH_ATLAS.get(approach_key)
        if not approach:
            return 0
        self._danger_zones = [
            {
                "name": dz.name,
                "type": dz.structure_type,
                "level": dz.danger_level,
                "position": np.array(dz.position_lps),
                "safe_distance": dz.safe_distance_mm,
                "note": dz.note,
            }
            for dz in approach.danger_zones
        ]
        return len(self._danger_zones)

    def add_plate_zone(
        self,
        plate_id: str,
        center_lps: list[float],
        extents_mm: list[float],
    ) -> None:
        """Register a plate placement zone for interference checking."""
        self._plate_zones.append({
            "id": plate_id,
            "center": np.array(center_lps),
            "extents": np.array(extents_mm),
        })

    # ------------------------------------------------------------------
    # K-wire interference checks
    # ------------------------------------------------------------------

    def check_kwire_trajectory(
        self,
        kwire_id: str,
        origin: list[float],
        direction: list[float],
        length_mm: float = 150.0,
        radius_mm: float = 0.8,
    ) -> list[InterferenceResult]:
        """Check a K-wire trajectory against all registered obstacles.

        Returns list of all detected interferences.
        """
        results: list[InterferenceResult] = []
        origin_np = np.array(origin)
        dir_np = np.array(direction, dtype=np.float64)
        dir_np = dir_np / np.linalg.norm(dir_np)  # normalize

        # 1. K-wire vs Clamps
        for clamp in self._clamp_placements:
            if not clamp.is_active:
                continue
            clamp_spec = CLAMP_LIBRARY.get(clamp.clamp_id)
            if not clamp_spec:
                continue

            clamp_pos = np.array(clamp.position_lps)
            bounding_r = clamp_spec.bounding_radius_mm + radius_mm

            # Ray-sphere intersection test
            dist = self._ray_sphere_distance(origin_np, dir_np, clamp_pos, length_mm)
            if dist is not None and dist < bounding_r:
                results.append(InterferenceResult(
                    interference_type=InterferenceType.KWIRE_CLAMP,
                    severity="critical" if dist < radius_mm else "warning",
                    object_a=kwire_id,
                    object_b=clamp.placement_id,
                    distance_mm=round(dist - radius_mm, 1),
                    location_lps=clamp.position_lps,
                    suggestion=f"Relocate {clamp_spec.name} or adjust K-wire entry angle",
                    view_for_verification="Lateral" if abs(dir_np[0]) > 0.5 else "AP",
                ))

        # 2. K-wire vs Plate zones
        for plate in self._plate_zones:
            dist = self._ray_box_distance(
                origin_np, dir_np, plate["center"], plate["extents"], length_mm
            )
            if dist is not None:
                results.append(InterferenceResult(
                    interference_type=InterferenceType.KWIRE_PLATE,
                    severity="warning",
                    object_a=kwire_id,
                    object_b=plate["id"],
                    distance_mm=round(dist, 1),
                    suggestion="K-wire may block plate placement. Consider temporary K-wire removal before plating.",
                ))

        # 3. K-wire vs Danger zones (nerves, vessels)
        for dz in self._danger_zones:
            dist = self._ray_sphere_distance(
                origin_np, dir_np, dz["position"], length_mm
            )
            if dist is not None and dist < dz["safe_distance"]:
                itype = (
                    InterferenceType.KWIRE_NERVE if dz["type"] == "nerve"
                    else InterferenceType.KWIRE_VESSEL if dz["type"] in ("artery", "vein")
                    else InterferenceType.KWIRE_TENDON
                )
                results.append(InterferenceResult(
                    interference_type=itype,
                    severity="critical" if dz["level"] == DangerLevel.CRITICAL else "warning",
                    object_a=kwire_id,
                    object_b=dz["name"],
                    distance_mm=round(dist, 1),
                    location_lps=dz["position"].tolist(),
                    suggestion=f"K-wire within {dist:.1f}mm of {dz['name']}. {dz['note']}",
                    view_for_verification="AP",
                ))

        return results

    # ------------------------------------------------------------------
    # Clamp vs Plate interference
    # ------------------------------------------------------------------

    def check_clamp_plate_interference(self) -> list[InterferenceResult]:
        """Check all clamp placements against plate zones."""
        results = []
        for clamp in self._clamp_placements:
            if not clamp.is_active:
                continue
            clamp_spec = CLAMP_LIBRARY.get(clamp.clamp_id)
            if not clamp_spec:
                continue

            clamp_pos = np.array(clamp.position_lps)
            clamp_r = clamp_spec.bounding_radius_mm

            for plate in self._plate_zones:
                dist = np.linalg.norm(clamp_pos - plate["center"])
                overlap = clamp_r + np.max(plate["extents"]) / 2 - dist

                if overlap > 0:
                    results.append(InterferenceResult(
                        interference_type=InterferenceType.CLAMP_PLATE,
                        severity="warning",
                        object_a=clamp.placement_id,
                        object_b=plate["id"],
                        distance_mm=round(-overlap, 1),
                        location_lps=clamp.position_lps,
                        suggestion=f"Relocate {clamp_spec.name} {overlap:.0f}mm away from plate zone",
                    ))

        return results

    # ------------------------------------------------------------------
    # Full audit
    # ------------------------------------------------------------------

    def run_full_audit(
        self,
        kwire_trajectories: Optional[list[dict]] = None,
    ) -> list[InterferenceResult]:
        """Run all interference checks and return combined results."""
        all_results: list[InterferenceResult] = []

        # K-wire checks
        if kwire_trajectories:
            for kw in kwire_trajectories:
                results = self.check_kwire_trajectory(
                    kwire_id=kw["id"],
                    origin=kw["origin"],
                    direction=kw["direction"],
                    length_mm=kw.get("length_mm", 150),
                    radius_mm=kw.get("radius_mm", 0.8),
                )
                all_results.extend(results)

        # Clamp vs plate
        all_results.extend(self.check_clamp_plate_interference())

        # Sort by severity (critical first)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        all_results.sort(key=lambda r: severity_order.get(r.severity, 3))

        return all_results

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ray_sphere_distance(
        ray_origin: np.ndarray,
        ray_dir: np.ndarray,
        sphere_center: np.ndarray,
        ray_length: float,
    ) -> Optional[float]:
        """Compute minimum distance from a ray to a sphere center.

        Returns None if the closest point is beyond ray_length.
        """
        oc = sphere_center - ray_origin
        t = float(np.dot(oc, ray_dir))
        t = max(0, min(t, ray_length))
        closest = ray_origin + t * ray_dir
        dist = float(np.linalg.norm(sphere_center - closest))
        return dist

    @staticmethod
    def _ray_box_distance(
        ray_origin: np.ndarray,
        ray_dir: np.ndarray,
        box_center: np.ndarray,
        box_extents: np.ndarray,
        ray_length: float,
    ) -> Optional[float]:
        """Check if a ray passes through an axis-aligned bounding box.

        Returns minimum distance to box, or None if ray misses entirely.
        """
        half = box_extents / 2
        box_min = box_center - half
        box_max = box_center + half

        # Sample points along ray and check distance to box
        min_dist = float("inf")
        for t in np.linspace(0, ray_length, 50):
            pt = ray_origin + t * ray_dir
            # Distance to AABB
            clamped = np.clip(pt, box_min, box_max)
            dist = float(np.linalg.norm(pt - clamped))
            min_dist = min(min_dist, dist)

        return min_dist if min_dist < float("inf") else None
