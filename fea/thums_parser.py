"""THUMS v7.1 LS-DYNA Keyword File Parser.

Extracts geometry (*NODE, *ELEMENT), material (*MAT_*), and part (*PART)
data from THUMS .k files and converts to OsteoTwin-compatible formats.

THUMS unit system: mm, ton (1e-3 kg → 1 ton = 1000 kg), sec, N, MPa
OsteoTwin standard: mm, kg, sec

Usage:
    python fea/thums_parser.py AM50   # Parse AM50 subject
    python fea/thums_parser.py ALL    # Parse all subjects
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("thums_parser")

# ---------------------------------------------------------------------------
# THUMS body region numbering (from manual p.18)
# ---------------------------------------------------------------------------

REGION_MAP = {
    81: "lower_extremity_right",
    82: "lower_extremity_left",
    83: "abdomen_pelvis",
    84: "internal_organs",
    85: "upper_extremity_right",
    86: "upper_extremity_left",
    87: "neck",
    88: "head",
    89: "thorax",
    7:  "muscle",
}

def region_from_part_id(part_id: int) -> str:
    """Derive body region from THUMS part ID numbering convention."""
    if 7000000 <= part_id < 8000000:
        return "muscle"
    prefix = part_id // 1000000
    return REGION_MAP.get(prefix, f"unknown_{prefix}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MaterialCard:
    """Parsed LS-DYNA material card."""
    mat_id: int
    mat_type: str  # e.g., "MAT_ELASTIC", "MAT_MUSCLE"
    density_ton_mm3: float = 0.0  # ton/mm³ (THUMS native)
    density_kg_mm3: float = 0.0   # kg/mm³ (OsteoTwin)
    youngs_modulus_mpa: Optional[float] = None
    poisson_ratio: Optional[float] = None
    bulk_modulus_mpa: Optional[float] = None
    shear_modulus_mpa: Optional[float] = None
    yield_stress_mpa: Optional[float] = None
    # Viscoelastic
    g0: Optional[float] = None  # Short-time shear modulus
    gi: Optional[float] = None  # Long-time shear modulus
    beta: Optional[float] = None  # Decay constant
    # Muscle-specific
    peak_isometric_stress: Optional[float] = None
    damping: Optional[float] = None
    raw_card: list[str] = field(default_factory=list)


@dataclass
class PartCard:
    """Parsed LS-DYNA *PART card."""
    part_id: int
    section_id: int
    mat_id: int
    title: str = ""
    region: str = ""


@dataclass
class THUMSModel:
    """Complete parsed THUMS model."""
    subject: str  # e.g., "AM50"
    materials: dict[int, MaterialCard] = field(default_factory=dict)
    parts: dict[int, PartCard] = field(default_factory=dict)
    node_count: int = 0
    element_solid_count: int = 0
    element_shell_count: int = 0


# ---------------------------------------------------------------------------
# Fixed-width field parser (LS-DYNA uses 10-char or 8-char columns)
# ---------------------------------------------------------------------------

def parse_fields(line: str, width: int = 10) -> list[str]:
    """Parse LS-DYNA fixed-width fields."""
    fields = []
    for i in range(0, len(line), width):
        f = line[i:i+width].strip()
        if f:
            fields.append(f)
    return fields


def safe_float(s: str, default: float = 0.0) -> float:
    try:
        return float(s)
    except (ValueError, IndexError):
        return default


def safe_int(s: str, default: int = 0) -> int:
    try:
        return int(float(s))
    except (ValueError, IndexError):
        return default


# ---------------------------------------------------------------------------
# Material parsers (per MAT type)
# ---------------------------------------------------------------------------

def parse_mat_elastic(mat_type: str, lines: list[str]) -> MaterialCard:
    """Parse *MAT_ELASTIC (MAT_001) or *MAT_ELASTIC_FLUID."""
    fields = parse_fields(lines[0])
    mid = safe_int(fields[0])
    ro = safe_float(fields[1]) if len(fields) > 1 else 0.0
    e = safe_float(fields[2]) if len(fields) > 2 else None
    pr = safe_float(fields[3]) if len(fields) > 3 else None
    return MaterialCard(
        mat_id=mid, mat_type=mat_type,
        density_ton_mm3=ro, density_kg_mm3=ro * 1e3,
        youngs_modulus_mpa=e, poisson_ratio=pr,
        raw_card=lines,
    )


def parse_mat_piecewise_linear(mat_type: str, lines: list[str]) -> MaterialCard:
    """Parse *MAT_PIECEWISE_LINEAR_PLASTICITY (MAT_024)."""
    fields = parse_fields(lines[0])
    mid = safe_int(fields[0])
    ro = safe_float(fields[1]) if len(fields) > 1 else 0.0
    e = safe_float(fields[2]) if len(fields) > 2 else None
    pr = safe_float(fields[3]) if len(fields) > 3 else None
    sigy = safe_float(fields[4]) if len(fields) > 4 else None
    return MaterialCard(
        mat_id=mid, mat_type=mat_type,
        density_ton_mm3=ro, density_kg_mm3=ro * 1e3,
        youngs_modulus_mpa=e, poisson_ratio=pr,
        yield_stress_mpa=sigy,
        raw_card=lines,
    )


def parse_mat_viscoelastic(mat_type: str, lines: list[str]) -> MaterialCard:
    """Parse *MAT_VISCOELASTIC (MAT_006)."""
    fields = parse_fields(lines[0])
    mid = safe_int(fields[0])
    ro = safe_float(fields[1]) if len(fields) > 1 else 0.0
    bulk = safe_float(fields[2]) if len(fields) > 2 else None
    g0 = safe_float(fields[3]) if len(fields) > 3 else None
    gi = safe_float(fields[4]) if len(fields) > 4 else None
    beta = safe_float(fields[5]) if len(fields) > 5 else None
    return MaterialCard(
        mat_id=mid, mat_type=mat_type,
        density_ton_mm3=ro, density_kg_mm3=ro * 1e3,
        bulk_modulus_mpa=bulk, g0=g0, gi=gi, beta=beta,
        raw_card=lines,
    )


def parse_mat_kelvin_maxwell(mat_type: str, lines: list[str]) -> MaterialCard:
    """Parse *MAT_KELVIN-MAXWELL_VISCOELASTIC (MAT_061)."""
    fields = parse_fields(lines[0])
    mid = safe_int(fields[0])
    ro = safe_float(fields[1]) if len(fields) > 1 else 0.0
    bulk = safe_float(fields[2]) if len(fields) > 2 else None
    g0 = safe_float(fields[3]) if len(fields) > 3 else None
    gi = safe_float(fields[4]) if len(fields) > 4 else None
    beta = safe_float(fields[5]) if len(fields) > 5 else None
    return MaterialCard(
        mat_id=mid, mat_type=mat_type,
        density_ton_mm3=ro, density_kg_mm3=ro * 1e3,
        bulk_modulus_mpa=bulk, g0=g0, gi=gi, beta=beta,
        raw_card=lines,
    )


def parse_mat_muscle(mat_type: str, lines: list[str]) -> MaterialCard:
    """Parse *MAT_MUSCLE (MAT_156)."""
    fields = parse_fields(lines[0])
    mid = safe_int(fields[0])
    ro = safe_float(fields[1]) if len(fields) > 1 else 0.0
    pis = safe_float(fields[4]) if len(fields) > 4 else None
    dmp = safe_float(fields[7]) if len(fields) > 7 else None
    return MaterialCard(
        mat_id=mid, mat_type=mat_type,
        density_ton_mm3=ro, density_kg_mm3=ro * 1e3,
        peak_isometric_stress=pis, damping=dmp,
        raw_card=lines,
    )


def parse_mat_null(mat_type: str, lines: list[str]) -> MaterialCard:
    """Parse *MAT_NULL (MAT_009)."""
    fields = parse_fields(lines[0])
    mid = safe_int(fields[0])
    ro = safe_float(fields[1]) if len(fields) > 1 else 0.0
    return MaterialCard(
        mat_id=mid, mat_type=mat_type,
        density_ton_mm3=ro, density_kg_mm3=ro * 1e3,
        raw_card=lines,
    )


def parse_mat_generic(mat_type: str, lines: list[str]) -> MaterialCard:
    """Generic parser -extracts MID and density from first two fields."""
    fields = parse_fields(lines[0])
    mid = safe_int(fields[0])
    ro = safe_float(fields[1]) if len(fields) > 1 else 0.0
    return MaterialCard(
        mat_id=mid, mat_type=mat_type,
        density_ton_mm3=ro, density_kg_mm3=ro * 1e3,
        raw_card=lines,
    )


MAT_PARSERS = {
    "*MAT_ELASTIC": parse_mat_elastic,
    "*MAT_ELASTIC_FLUID": parse_mat_elastic,
    "*MAT_PIECEWISE_LINEAR_PLASTICITY": parse_mat_piecewise_linear,
    "*MAT_ISOTROPIC_ELASTIC_PLASTIC": parse_mat_piecewise_linear,
    "*MAT_VISCOELASTIC": parse_mat_viscoelastic,
    "*MAT_KELVIN-MAXWELL_VISCOELASTIC": parse_mat_kelvin_maxwell,
    "*MAT_MUSCLE": parse_mat_muscle,
    "*MAT_NULL": parse_mat_null,
    "*MAT_RIGID": parse_mat_generic,
    "*MAT_FABRIC": parse_mat_generic,
    "*MAT_FABRIC_TITLE": parse_mat_generic,
    "*MAT_DAMAGE_2": parse_mat_generic,
    "*MAT_PLASTICITY_WITH_DAMAGE": parse_mat_piecewise_linear,
    "*MAT_SIMPLIFIED_RUBBER": parse_mat_generic,
    "*MAT_SIMPLIFIED_RUBBER_TITLE": parse_mat_generic,
    "*MAT_FU_CHANG_FOAM": parse_mat_generic,
    "*MAT_LOW_DENSITY_FOAM": parse_mat_generic,
    "*MAT_SEATBELT": parse_mat_generic,
    "*MAT_CABLE_DISCRETE_BEAM": parse_mat_generic,
    "*MAT_ADD_EROSION": None,  # skip -modifier, not standalone
}


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_k_file(filepath: Path, subject: str) -> THUMSModel:
    """Parse a THUMS LS-DYNA .k file and extract all structural data."""
    model = THUMSModel(subject=subject)
    logger.info("Parsing %s (%s)...", filepath.name, subject)

    lines: list[str] = []
    with open(filepath, "r", errors="replace") as f:
        lines = f.readlines()

    total = len(lines)
    logger.info("  Total lines: %d", total)

    i = 0
    while i < total:
        line = lines[i].rstrip("\n")

        # Skip comments
        if line.startswith("$") or not line.strip():
            i += 1
            continue

        # --- *MAT_ cards ---
        if line.strip().startswith("*MAT_"):
            mat_keyword = line.strip().split()[0]

            # Skip title line for _TITLE variants
            if mat_keyword.endswith("_TITLE"):
                base_kw = mat_keyword  # keep as-is for parser lookup
                i += 1  # skip title line
                if i < total and not lines[i].strip().startswith("*"):
                    i += 1  # skip actual title text

            i += 1  # move to data lines

            # Collect data lines (non-comment, non-keyword)
            data_lines = []
            while i < total and not lines[i].strip().startswith("*") and not lines[i].strip().startswith("$"):
                data_lines.append(lines[i].rstrip("\n"))
                i += 1
                if len(data_lines) >= 4:  # most MAT cards have 1-4 data lines
                    break

            parser = MAT_PARSERS.get(mat_keyword)
            if parser and data_lines:
                try:
                    mat = parser(mat_keyword, data_lines)
                    model.materials[mat.mat_id] = mat
                except Exception as e:
                    logger.debug("Failed to parse %s at line %d: %s", mat_keyword, i, e)
            continue

        # --- *PART and *PART_AVERAGED cards ---
        if line.strip() in ("*PART", "*PART_AVERAGED"):
            is_averaged = "AVERAGED" in line.strip()
            i += 1

            # Parse comment lines and title lines until we hit the data line
            title = ""
            while i < total:
                cl = lines[i].rstrip("\n").strip()
                if cl.startswith("$HMNAME COMPS"):
                    # Extract anatomical name from $HMNAME COMPS <ID><Name>
                    # Format: "$HMNAME COMPS 7124000M_RectusFemoris_R"
                    parts_str = cl.replace("$HMNAME COMPS", "").strip()
                    # Name starts after the numeric ID
                    match = re.match(r"(\d+)(.*)", parts_str)
                    if match:
                        title = match.group(2).strip()
                    i += 1
                elif cl.startswith("$"):
                    i += 1  # skip other comments
                elif cl.startswith("*"):
                    break  # next keyword, no data line found
                elif not cl:
                    i += 1
                else:
                    # Could be a title text line or data line
                    # Data lines start with numbers; title lines start with letters
                    test_fields = parse_fields(cl)
                    if test_fields and re.match(r"^-?\d", test_fields[0]):
                        # This is the data line: PID, SECID, MID, ...
                        pid = safe_int(test_fields[0])
                        secid = safe_int(test_fields[1]) if len(test_fields) > 1 else 0
                        mid = safe_int(test_fields[2]) if len(test_fields) > 2 else 0
                        if not title:
                            title = f"part_{pid}"
                        model.parts[pid] = PartCard(
                            part_id=pid, section_id=secid, mat_id=mid,
                            title=title, region=region_from_part_id(pid),
                        )
                        i += 1
                        break
                    else:
                        # Title text line
                        if not title:
                            title = cl
                        i += 1
            continue

        # --- *NODE count ---
        if line.strip() == "*NODE":
            i += 1
            while i < total and not lines[i].strip().startswith("*"):
                if lines[i].strip() and not lines[i].strip().startswith("$"):
                    model.node_count += 1
                i += 1
            continue

        # --- *ELEMENT counts ---
        if line.strip().startswith("*ELEMENT_SOLID"):
            i += 1
            while i < total and not lines[i].strip().startswith("*"):
                if lines[i].strip() and not lines[i].strip().startswith("$"):
                    model.element_solid_count += 1
                i += 1
            continue

        if line.strip().startswith("*ELEMENT_SHELL"):
            i += 1
            while i < total and not lines[i].strip().startswith("*"):
                if lines[i].strip() and not lines[i].strip().startswith("$"):
                    model.element_shell_count += 1
                i += 1
            continue

        i += 1

    logger.info("  Parsed: %d materials, %d parts, %d nodes, %d solid elements, %d shell elements",
                len(model.materials), len(model.parts),
                model.node_count, model.element_solid_count, model.element_shell_count)
    return model


# ---------------------------------------------------------------------------
# Output: thums_anatomical_map.json
# ---------------------------------------------------------------------------

def build_anatomical_map(model: THUMSModel) -> list[dict]:
    """Build the anatomical map JSON from parsed model data."""
    entries = []
    for pid, part in sorted(model.parts.items()):
        mat = model.materials.get(part.mat_id)
        entry = {
            "part_id": pid,
            "title": part.title,
            "region": part.region,
            "mat_id": part.mat_id,
            "mat_type": mat.mat_type if mat else "UNKNOWN",
            "density_kg_mm3": mat.density_kg_mm3 if mat else None,
            "density_ton_mm3": mat.density_ton_mm3 if mat else None,
            "youngs_modulus_mpa": mat.youngs_modulus_mpa if mat else None,
            "poisson_ratio": mat.poisson_ratio if mat else None,
            "yield_stress_mpa": mat.yield_stress_mpa if mat else None,
            "bulk_modulus_mpa": mat.bulk_modulus_mpa if mat else None,
            "shear_modulus_g0_mpa": mat.g0 if mat else None,
            "shear_modulus_gi_mpa": mat.gi if mat else None,
            "viscoelastic_beta": mat.beta if mat else None,
            "peak_isometric_stress": mat.peak_isometric_stress if mat else None,
            "damping": mat.damping if mat else None,
        }
        entries.append(entry)
    return entries


def build_material_summary(model: THUMSModel) -> dict:
    """Build a summary of unique material types and their properties."""
    from collections import Counter
    mat_type_counts = Counter()
    region_counts = Counter()
    for part in model.parts.values():
        mat = model.materials.get(part.mat_id)
        if mat:
            mat_type_counts[mat.mat_type] += 1
        region_counts[part.region] += 1

    return {
        "subject": model.subject,
        "total_parts": len(model.parts),
        "total_materials": len(model.materials),
        "total_nodes": model.node_count,
        "total_solid_elements": model.element_solid_count,
        "total_shell_elements": model.element_shell_count,
        "material_type_counts": dict(mat_type_counts.most_common()),
        "region_counts": dict(region_counts.most_common()),
    }


# ---------------------------------------------------------------------------
# Extremity-focused extraction
# ---------------------------------------------------------------------------

def extract_extremity_parts(entries: list[dict]) -> dict:
    """Filter anatomical map to upper/lower extremity parts only."""
    extremity_regions = {
        "lower_extremity_right", "lower_extremity_left",
        "upper_extremity_right", "upper_extremity_left",
    }
    result = {
        "upper_extremity": [],
        "lower_extremity": [],
        "extremity_muscles": [],
    }
    for e in entries:
        if "upper_extremity" in e["region"]:
            result["upper_extremity"].append(e)
        elif "lower_extremity" in e["region"]:
            result["lower_extremity"].append(e)
        elif e["region"] == "muscle":
            # Check if muscle ID corresponds to extremity (71xx=leg, 75xx=arm)
            mid = e["part_id"]
            if 7100000 <= mid < 7300000 or 7500000 <= mid < 7700000:
                result["extremity_muscles"].append(e)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SUBJECT_DIRS = {
    "AF05": "AF05_V71_Occupant",
    "AF50": "AF50_V71_Occupant",
    "AM50": "AM50_V71_Occupant",
    "AM95": "AM95_V71_Occupant",
}


def main():
    base_dir = Path(__file__).parent / "thums"
    out_dir = Path(__file__).parent / "thums_output"
    out_dir.mkdir(exist_ok=True)

    subjects = sys.argv[1:] if len(sys.argv) > 1 else ["AM50"]
    if subjects == ["ALL"]:
        subjects = list(SUBJECT_DIRS.keys())

    for subj in subjects:
        dir_name = SUBJECT_DIRS.get(subj)
        if not dir_name:
            logger.error("Unknown subject: %s (choices: %s)", subj, list(SUBJECT_DIRS.keys()))
            continue

        # Find main model .k file
        model_dir = base_dir / dir_name / "THUMS_model"
        k_files = list(model_dir.glob(f"THUMS_{subj}_V71_Occupant_*.k"))
        if not k_files:
            logger.error("No main .k file found in %s", model_dir)
            continue

        k_file = k_files[0]
        model = parse_k_file(k_file, subj)

        # Build outputs
        anat_map = build_anatomical_map(model)
        summary = build_material_summary(model)
        extremities = extract_extremity_parts(anat_map)

        # Write outputs
        subj_dir = out_dir / subj
        subj_dir.mkdir(exist_ok=True)

        with open(subj_dir / "thums_anatomical_map.json", "w") as f:
            json.dump(anat_map, f, indent=2)
        logger.info("  Wrote thums_anatomical_map.json (%d entries)", len(anat_map))

        with open(subj_dir / "model_summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        logger.info("  Wrote model_summary.json")

        with open(subj_dir / "extremity_parts.json", "w") as f:
            json.dump(extremities, f, indent=2)
        logger.info("  Wrote extremity_parts.json (%d upper, %d lower, %d muscles)",
                     len(extremities["upper_extremity"]),
                     len(extremities["lower_extremity"]),
                     len(extremities["extremity_muscles"]))

        # Print extremity summary
        print(f"\n{'='*70}")
        print(f"  {subj} -Extremity Summary")
        print(f"{'='*70}")
        for region_key in ["upper_extremity", "lower_extremity"]:
            parts = extremities[region_key]
            print(f"\n  {region_key.replace('_', ' ').title()} ({len(parts)} parts):")
            # Group by mat_type
            from collections import Counter
            mt = Counter(p["mat_type"] for p in parts)
            for mat_type, count in mt.most_common():
                print(f"    {mat_type:45s} {count:>4} parts")
                # Show sample entries
                samples = [p for p in parts if p["mat_type"] == mat_type][:3]
                for s in samples:
                    props = []
                    if s["youngs_modulus_mpa"]: props.append(f"E={s['youngs_modulus_mpa']} MPa")
                    if s["poisson_ratio"]: props.append(f"nu={s['poisson_ratio']}")
                    if s["yield_stress_mpa"]: props.append(f"Sy={s['yield_stress_mpa']} MPa")
                    if s["density_kg_mm3"]: props.append(f"rho={s['density_kg_mm3']:.2e} kg/mm3")
                    print(f"      PID={s['part_id']:>10}  {s['title'][:40]:40s}  {', '.join(props)}")

        muscles = extremities["extremity_muscles"]
        print(f"\n  Extremity Muscles ({len(muscles)} parts):")
        for m in muscles[:10]:
            print(f"    PID={m['part_id']:>10}  {m['title'][:50]:50s}  rho={m.get('density_kg_mm3', 'N/A')}")
        if len(muscles) > 10:
            print(f"    ... and {len(muscles)-10} more")


if __name__ == "__main__":
    main()
