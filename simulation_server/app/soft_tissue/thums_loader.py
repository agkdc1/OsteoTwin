"""THUMS v7.1 material data loader for the SOFA soft-tissue engine.

Reads the parsed thums_anatomical_map.json and material_configs.json
to provide anatomically accurate tissue properties for patient-specific
simulation, rather than hardcoded defaults.

Unit conversions:
    THUMS: mm, ton, sec (density in ton/mm3)
    OsteoTwin: mm, kg, sec (density in kg/mm3)
    SOFA: mm, kg, sec (density in kg/m3 for some fields)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("osteotwin.thums_loader")

# Default path to THUMS parsed output
THUMS_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fea" / "thums_output"


class THUMSMaterialDB:
    """In-memory database of THUMS material properties.

    Loads from the parsed thums_anatomical_map.json and provides
    lookup by part_id, region, or tissue type.
    """

    def __init__(self, subject: str = "AM50"):
        self.subject = subject
        self._parts: list[dict] = []
        self._by_id: dict[int, dict] = {}
        self._sofa_configs: list[dict] = []
        self._loaded = False

    def load(self, base_dir: Optional[Path] = None) -> bool:
        """Load parsed THUMS data from JSON files."""
        data_dir = (base_dir or THUMS_OUTPUT_DIR) / self.subject

        anat_path = data_dir / "thums_anatomical_map.json"
        sofa_path = data_dir / "material_configs.json"

        if not anat_path.exists():
            logger.warning("THUMS data not found for %s at %s", self.subject, anat_path)
            return False

        with open(anat_path) as f:
            self._parts = json.load(f)
        self._by_id = {p["part_id"]: p for p in self._parts}

        if sofa_path.exists():
            with open(sofa_path) as f:
                self._sofa_configs = json.load(f)

        self._loaded = True
        logger.info(
            "THUMS %s loaded: %d parts, %d SOFA configs",
            self.subject, len(self._parts), len(self._sofa_configs),
        )
        return True

    @property
    def available(self) -> bool:
        return self._loaded

    def get_part(self, part_id: int) -> Optional[dict]:
        return self._by_id.get(part_id)

    def get_parts_by_region(self, region: str) -> list[dict]:
        """Get all parts for a body region (e.g., 'lower_extremity_right')."""
        return [p for p in self._parts if p["region"] == region]

    def get_parts_by_mat_type(self, mat_type: str) -> list[dict]:
        """Get all parts with a specific material type."""
        return [p for p in self._parts if p["mat_type"] == mat_type]

    def get_bone_parts(self, region: Optional[str] = None) -> list[dict]:
        """Get cortical and cancellous bone parts."""
        bone_mats = {
            "*MAT_PIECEWISE_LINEAR_PLASTICITY",
            "*MAT_ISOTROPIC_ELASTIC_PLASTIC",
            "*MAT_ELASTIC",
            "*MAT_DAMAGE_2",
        }
        parts = [p for p in self._parts if p["mat_type"] in bone_mats]
        if region:
            parts = [p for p in parts if p["region"] == region]
        return parts

    def get_soft_tissue_parts(self, region: Optional[str] = None) -> list[dict]:
        """Get soft tissue parts (flesh, ligaments, tendons)."""
        soft_mats = {
            "*MAT_SIMPLIFIED_RUBBER",
            "*MAT_SIMPLIFIED_RUBBER_TITLE",
            "*MAT_VISCOELASTIC",
            "*MAT_KELVIN-MAXWELL_VISCOELASTIC",
            "*MAT_FABRIC",
            "*MAT_FABRIC_TITLE",
            "*MAT_LOW_DENSITY_FOAM",
        }
        parts = [p for p in self._parts if p["mat_type"] in soft_mats]
        if region:
            parts = [p for p in parts if p["region"] == region]
        return parts

    def get_muscle_parts(self) -> list[dict]:
        """Get all Hill-type muscle parts."""
        return [p for p in self._parts if p["mat_type"] == "*MAT_MUSCLE"]

    def get_sofa_config(self, part_id: int) -> Optional[dict]:
        """Get SOFA force field configuration for a specific part."""
        for cfg in self._sofa_configs:
            if cfg["part_id"] == part_id:
                return cfg
        return None

    def build_tissue_definitions(self, region: str) -> list[dict]:
        """Build SoftTissueDefinition-compatible dicts from THUMS data.

        Maps THUMS soft tissue parts to the protocol expected by
        the soft-tissue simulation endpoint.
        """
        soft_parts = self.get_soft_tissue_parts(region)
        definitions = []

        for part in soft_parts:
            # Determine tissue type from part title
            title_lower = part["title"].lower()
            if "lig" in title_lower:
                tissue_type = "ligament"
            elif "tendon" in title_lower or "achilles" in title_lower:
                tissue_type = "tendon"
            elif "flesh" in title_lower or "muscle" in title_lower:
                tissue_type = "muscle"
            elif "periosteum" in title_lower:
                tissue_type = "periosteum"
            elif "nerve" in title_lower:
                tissue_type = "nerve"
            elif "artery" in title_lower or "vessel" in title_lower or "vein" in title_lower:
                tissue_type = "vessel"
            else:
                tissue_type = "ligament"  # default for connective tissue

            # Estimate stiffness from material properties
            E = part.get("youngs_modulus_mpa")
            stiffness = E if E and E > 0 else 100.0  # N/mm default

            # Estimate max tension based on tissue type
            max_tension_map = {
                "ligament": 40.0,
                "tendon": 60.0,
                "muscle": 50.0,
                "periosteum": 15.0,
                "nerve": 5.0,
                "vessel": 10.0,
            }
            max_tension = max_tension_map.get(tissue_type, 30.0)

            definitions.append({
                "tissue_id": f"thums_{part['part_id']}",
                "tissue_type": tissue_type,
                "label": part["title"],
                "origin": {
                    "label": f"{part['title']}_origin",
                    "fragment_id": "proximal",
                    "position": [0.0, 0.0, 0.0],  # populated at runtime from mesh
                },
                "insertion": {
                    "label": f"{part['title']}_insertion",
                    "fragment_id": "distal",
                    "position": [0.0, 0.0, 0.0],  # populated at runtime from mesh
                },
                "rest_length_mm": 30.0,  # populated at runtime from mesh
                "max_tension_n": max_tension,
                "stiffness": stiffness,
                "thums_part_id": part["part_id"],
                "thums_mat_type": part["mat_type"],
                "density_kg_mm3": part.get("density_kg_mm3"),
            })

        return definitions

    def summary(self) -> dict:
        """Return a summary of loaded THUMS data."""
        if not self._loaded:
            return {"loaded": False, "subject": self.subject}

        from collections import Counter
        mat_counts = Counter(p["mat_type"] for p in self._parts)
        region_counts = Counter(p["region"] for p in self._parts)

        return {
            "loaded": True,
            "subject": self.subject,
            "total_parts": len(self._parts),
            "sofa_configs": len(self._sofa_configs),
            "material_types": dict(mat_counts.most_common()),
            "regions": dict(region_counts.most_common()),
            "bone_parts": len(self.get_bone_parts()),
            "soft_tissue_parts": len(self.get_soft_tissue_parts()),
            "muscle_parts": len(self.get_muscle_parts()),
        }


# ---------------------------------------------------------------------------
# Singleton instance (initialized on first access)
# ---------------------------------------------------------------------------

_db: Optional[THUMSMaterialDB] = None


def get_thums_db(subject: str = "AM50") -> THUMSMaterialDB:
    """Get or create the THUMS material database singleton."""
    global _db
    if _db is None or _db.subject != subject:
        _db = THUMSMaterialDB(subject)
        _db.load()
    return _db
