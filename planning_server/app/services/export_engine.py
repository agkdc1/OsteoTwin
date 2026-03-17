"""Multi-material 3D print export engine.

Packages finalized surgical models into printer-ready formats:
1. **3MF** (preferred) — native multi-material with extruder metadata
2. **Named-STL ZIP** (fallback) — ZIP of explicitly named STLs per extruder

Reads PrinterConfig to inject correct extruder/material assignments
so slicing software (PrusaSlicer, BambuStudio) auto-assigns nozzles.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

import sys, pathlib

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)
)
from shared.schemas import PrinterConfig, FilamentMapping

logger = logging.getLogger("osteotwin.export_engine")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

EXPORT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "exports"


class ExportPart:
    """A single geometry part with semantic metadata."""

    def __init__(
        self,
        mesh: trimesh.Trimesh,
        label: str,
        color_code: str,
        component_type: str = "fragment",
    ):
        self.mesh = mesh
        self.label = label
        self.color_code = color_code
        self.component_type = component_type


# ---------------------------------------------------------------------------
# 3MF generation
# ---------------------------------------------------------------------------

_3MF_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_3MF_MAT_NS = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"


def _mesh_to_3mf_xml(
    parts: list[ExportPart],
    printer_config: Optional[PrinterConfig],
) -> bytes:
    """Build the 3D/3dmodel.model XML for a 3MF archive.

    Each part becomes an <object> with an extruder-id property
    derived from the PrinterConfig filament mapping.
    """
    # Build color→extruder lookup
    extruder_map: dict[str, int] = {}
    if printer_config:
        for fm in printer_config.filament_mappings:
            extruder_map[fm.color_code.lower()] = fm.extruder_id

    model = ET.Element("model", {
        "unit": "millimeter",
        "xmlns": _3MF_NS,
        "xmlns:m": _3MF_MAT_NS,
    })

    resources = ET.SubElement(model, "resources")
    build = ET.SubElement(model, "build")

    for idx, part in enumerate(parts):
        obj_id = str(idx + 1)

        obj = ET.SubElement(resources, "object", {
            "id": obj_id,
            "type": "model",
            "name": part.label,
        })

        # Extruder metadata (PrusaSlicer reads this)
        ext_id = extruder_map.get(part.color_code.lower(), 0)
        meta = ET.SubElement(obj, "metadatagroup")
        ET.SubElement(meta, "metadata", {"name": "slic3r.extruder"}).text = str(ext_id + 1)

        mesh_el = ET.SubElement(obj, "mesh")

        # Vertices
        vertices_el = ET.SubElement(mesh_el, "vertices")
        for v in part.mesh.vertices:
            ET.SubElement(vertices_el, "vertex", {
                "x": f"{v[0]:.6f}",
                "y": f"{v[1]:.6f}",
                "z": f"{v[2]:.6f}",
            })

        # Triangles
        triangles_el = ET.SubElement(mesh_el, "triangles")
        for f in part.mesh.faces:
            ET.SubElement(triangles_el, "triangle", {
                "v1": str(f[0]),
                "v2": str(f[1]),
                "v3": str(f[2]),
            })

        # Build item
        ET.SubElement(build, "item", {"objectid": obj_id})

    tree = ET.ElementTree(model)
    buf = io.BytesIO()
    tree.write(buf, xml_declaration=True, encoding="UTF-8")
    return buf.getvalue()


def export_3mf(
    parts: list[ExportPart],
    printer_config: Optional[PrinterConfig],
    output_path: Path,
) -> Path:
    """Package parts into a 3MF archive with extruder metadata.

    3MF is a ZIP-based format containing:
        [Content_Types].xml
        3D/3dmodel.model        (geometry + extruder assignment)
        _rels/.rels
    """
    model_xml = _mesh_to_3mf_xml(parts, printer_config)

    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '</Types>'
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", model_xml)

    logger.info("Exported 3MF: %s (%d parts)", output_path.name, len(parts))
    return output_path


# ---------------------------------------------------------------------------
# Fallback: named-STL ZIP
# ---------------------------------------------------------------------------


def export_named_stl_zip(
    parts: list[ExportPart],
    printer_config: Optional[PrinterConfig],
    output_path: Path,
) -> Path:
    """Fallback export: ZIP containing explicitly named STLs per extruder.

    Naming convention: {label}_extruder{N}.stl
    so the user can manually assign parts in the slicer.
    """
    extruder_map: dict[str, int] = {}
    if printer_config:
        for fm in printer_config.filament_mappings:
            extruder_map[fm.color_code.lower()] = fm.extruder_id

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = []
        for part in parts:
            ext_id = extruder_map.get(part.color_code.lower(), 0)
            filename = f"{part.label}_extruder{ext_id + 1}.stl"

            buf = io.BytesIO()
            part.mesh.export(buf, file_type="stl")
            zf.writestr(filename, buf.getvalue())

            manifest.append({
                "file": filename,
                "label": part.label,
                "color_code": part.color_code,
                "extruder": ext_id + 1,
                "type": part.component_type,
            })

        # Include a manifest JSON for reference
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2),
        )

    logger.info("Exported STL ZIP: %s (%d parts)", output_path.name, len(parts))
    return output_path


# ---------------------------------------------------------------------------
# High-level export orchestrator
# ---------------------------------------------------------------------------


def export_for_print(
    parts: list[ExportPart],
    case_id: str,
    printer_config: Optional[PrinterConfig] = None,
    *,
    prefer_3mf: bool = True,
    output_dir: Optional[Path] = None,
) -> dict:
    """Export surgical model for 3D printing.

    Attempts 3MF first (native multi-material), falls back to named-STL ZIP.

    Returns metadata dict with file paths, print estimates, and part manifest.
    """
    out = output_dir or EXPORT_DIR / case_id
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    export_id = uuid.uuid4().hex[:8]
    base_name = f"{case_id}_{timestamp}_{export_id}"

    # Filter out K-wires (use real metal)
    skipped_kwires = []
    printable_parts = []
    for p in parts:
        is_kwire = "wire" in p.label.lower() or "k_wire" in p.label.lower()
        if is_kwire:
            skipped_kwires.append(p.label)
            continue
        printable_parts.append(p)

    # Try 3MF, fall back to STL ZIP
    export_format = "3mf"
    try:
        if prefer_3mf:
            path = export_3mf(
                printable_parts,
                printer_config,
                out / f"{base_name}.3mf",
            )
        else:
            raise ValueError("STL ZIP requested")
    except Exception as exc:
        logger.warning("3MF export failed (%s), falling back to STL ZIP", exc)
        export_format = "stl_zip"
        path = export_named_stl_zip(
            printable_parts,
            printer_config,
            out / f"{base_name}_stl.zip",
        )

    # Print statistics
    total_volume_mm3 = sum(
        abs(p.mesh.volume) for p in printable_parts
        if p.component_type in ("fragment", "hardware")
    )
    total_volume_cm3 = total_volume_mm3 / 1000.0

    if printable_parts:
        all_verts = np.vstack([p.mesh.vertices for p in printable_parts])
        bb_min = all_verts.min(axis=0)
        bb_max = all_verts.max(axis=0)
        bb_size = bb_max - bb_min
    else:
        bb_size = np.zeros(3)

    # Build volume check
    fits_build_volume = True
    if printer_config:
        bv = printer_config.build_volume_mm
        if bb_size[0] > bv.x or bb_size[1] > bv.y or bb_size[2] > bv.z:
            fits_build_volume = False

    return {
        "case_id": case_id,
        "export_id": export_id,
        "format": export_format,
        "file": str(path),
        "filename": path.name,
        "part_count": len(printable_parts),
        "parts": [
            {
                "label": p.label,
                "color_code": p.color_code,
                "type": p.component_type,
                "vertices": len(p.mesh.vertices),
                "faces": len(p.mesh.faces),
            }
            for p in printable_parts
        ],
        "skipped_kwires": skipped_kwires,
        "kwire_note": (
            "K-wires excluded from 3D print — use real metal K-wires for tactile practice"
            if skipped_kwires
            else None
        ),
        "printer": printer_config.printer_name if printer_config else None,
        "total_volume_cm3": round(total_volume_cm3, 2),
        "bounding_box_mm": {
            "x": round(float(bb_size[0]), 1),
            "y": round(float(bb_size[1]), 1),
            "z": round(float(bb_size[2]), 1),
        },
        "fits_build_volume": fits_build_volume,
        "print_estimate": {
            "material_g": round(total_volume_cm3 * 1.25, 1),
            "cost_usd": round(total_volume_cm3 * 1.25 * 0.025, 2),
        },
    }
