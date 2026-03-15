"""STL export pipeline for 3D printing.

Exports fracture cases as printable STL files with:
- Color-coded bone fragments (each fragment a separate shell)
- Implant placements (plates, screws, K-wires)
- Optional soft-tissue footprints
- Assembly guide markers

Supports both single-file (merged) and multi-file (per-component) export.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import trimesh

logger = logging.getLogger("osteotwin.stl_export")


@dataclass
class ExportComponent:
    """A single component in the 3D print export."""

    mesh: trimesh.Trimesh
    label: str
    component_type: str  # "fragment", "hardware", "marker", "boundary"
    color: tuple[int, int, int, int] = (200, 200, 200, 255)  # RGBA


# Color palette for fragments and hardware
FRAGMENT_COLORS = [
    (230, 210, 180, 255),  # Bone white
    (180, 160, 140, 255),  # Darker bone
    (200, 180, 160, 255),  # Mid bone
    (220, 200, 170, 255),  # Light bone
    (190, 170, 150, 255),  # Warm bone
    (210, 190, 165, 255),  # Tan bone
]

HARDWARE_COLOR = (80, 130, 200, 255)   # Steel blue
KWIRE_COLOR = (200, 200, 220, 255)     # Silver
DANGER_ZONE_COLOR = (220, 60, 60, 180) # Translucent red
MARKER_COLOR = (60, 200, 60, 255)      # Green


def colorize_mesh(mesh: trimesh.Trimesh, rgba: tuple[int, int, int, int]) -> trimesh.Trimesh:
    """Apply a uniform color to all faces of a mesh."""
    colors = np.full((len(mesh.faces), 4), rgba, dtype=np.uint8)
    mesh.visual.face_colors = colors
    return mesh


def add_alignment_markers(
    mesh: trimesh.Trimesh,
    marker_size_mm: float = 3.0,
) -> list[trimesh.Trimesh]:
    """Add small spherical alignment markers at the bounding box corners.

    These markers help align multi-part prints during assembly.
    """
    bounds = mesh.bounds
    corners = [
        bounds[0],  # min corner
        bounds[1],  # max corner
        [bounds[0][0], bounds[0][1], bounds[1][2]],  # mixed
    ]

    markers = []
    for corner in corners:
        sphere = trimesh.creation.icosphere(subdivisions=2, radius=marker_size_mm / 2)
        sphere.apply_translation(corner)
        colorize_mesh(sphere, MARKER_COLOR)
        markers.append(sphere)

    return markers


def add_scale_bar(length_mm: float = 20.0) -> trimesh.Trimesh:
    """Create a scale bar for the 3D print."""
    bar = trimesh.creation.box(extents=[length_mm, 2, 2])
    colorize_mesh(bar, (50, 50, 50, 255))
    return bar


def export_case_stl(
    fragments: list[trimesh.Trimesh],
    fragment_labels: list[str],
    *,
    hardware: Optional[list[tuple[trimesh.Trimesh, str]]] = None,
    danger_zones: Optional[list[trimesh.Trimesh]] = None,
    output_dir: str | Path,
    case_id: str,
    merged: bool = True,
    per_component: bool = True,
    add_markers: bool = True,
    scale_factor: float = 1.0,
) -> dict:
    """Export a fracture case as 3D-printable STL files.

    Args:
        fragments: List of bone fragment meshes.
        fragment_labels: Labels for each fragment.
        hardware: Optional list of (mesh, label) tuples for implants.
        danger_zones: Optional nerve/vessel boundary meshes (printed translucent).
        output_dir: Output directory for STL files.
        case_id: Case identifier for filenames.
        merged: If True, export a single merged STL with all components.
        per_component: If True, export separate STL per component.
        add_markers: Add alignment markers for multi-part assembly.
        scale_factor: Scale factor (1.0 = original size, 2.0 = double).

    Returns:
        Dict with export metadata and file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    components: list[ExportComponent] = []
    exported_files: list[dict] = []

    # Color-code fragments
    for i, (frag, label) in enumerate(zip(fragments, fragment_labels)):
        color = FRAGMENT_COLORS[i % len(FRAGMENT_COLORS)]
        frag_copy = frag.copy()
        if scale_factor != 1.0:
            frag_copy.apply_scale(scale_factor)
        colorize_mesh(frag_copy, color)
        components.append(ExportComponent(
            mesh=frag_copy, label=label,
            component_type="fragment", color=color,
        ))

    # Hardware (exclude K-wires — too thin for 3D printing, use real metal)
    skipped_kwires: list[str] = []
    if hardware:
        for hw_mesh, hw_label in hardware:
            is_kwire = "wire" in hw_label.lower() or "k_wire" in hw_label.lower()
            if is_kwire:
                skipped_kwires.append(hw_label)
                continue  # skip — use real metal K-wires for practice
            hw_copy = hw_mesh.copy()
            if scale_factor != 1.0:
                hw_copy.apply_scale(scale_factor)
            colorize_mesh(hw_copy, HARDWARE_COLOR)
            components.append(ExportComponent(
                mesh=hw_copy, label=hw_label,
                component_type="hardware", color=HARDWARE_COLOR,
            ))

    # Danger zones (nerves, vessels)
    if danger_zones:
        for j, dz in enumerate(danger_zones):
            dz_copy = dz.copy()
            if scale_factor != 1.0:
                dz_copy.apply_scale(scale_factor)
            colorize_mesh(dz_copy, DANGER_ZONE_COLOR)
            components.append(ExportComponent(
                mesh=dz_copy, label=f"danger_zone_{j}",
                component_type="boundary", color=DANGER_ZONE_COLOR,
            ))

    # Per-component export
    if per_component:
        for comp in components:
            filename = f"{case_id}_{comp.label}.stl"
            filepath = output_dir / filename
            comp.mesh.export(str(filepath))
            exported_files.append({
                "file": str(filepath),
                "label": comp.label,
                "type": comp.component_type,
                "vertices": len(comp.mesh.vertices),
                "faces": len(comp.mesh.faces),
            })
            logger.info("Exported component: %s (%d faces)", filename, len(comp.mesh.faces))

    # Merged export
    merged_path = None
    if merged:
        all_meshes = [comp.mesh for comp in components]

        # Add alignment markers
        if add_markers and fragments:
            full_bounds_mesh = trimesh.util.concatenate(
                [comp.mesh for comp in components if comp.component_type == "fragment"]
            )
            markers = add_alignment_markers(full_bounds_mesh)
            all_meshes.extend(markers)

        # Add scale bar
        scale_bar = add_scale_bar(20.0 * scale_factor)
        # Position below the model
        if fragments:
            min_z = min(comp.mesh.bounds[0][2] for comp in components)
            scale_bar.apply_translation([0, 0, min_z - 10 * scale_factor])
        all_meshes.append(scale_bar)

        merged_mesh = trimesh.util.concatenate(all_meshes)
        merged_filename = f"{case_id}_full_assembly.stl"
        merged_path = output_dir / merged_filename
        merged_mesh.export(str(merged_path))
        exported_files.append({
            "file": str(merged_path),
            "label": "full_assembly",
            "type": "merged",
            "vertices": len(merged_mesh.vertices),
            "faces": len(merged_mesh.faces),
        })
        logger.info(
            "Exported merged assembly: %s (%d faces)",
            merged_filename, len(merged_mesh.faces),
        )

    # Compute print stats
    total_volume_mm3 = sum(
        abs(comp.mesh.volume) for comp in components
        if comp.component_type in ("fragment", "hardware")
    )
    total_volume_cm3 = total_volume_mm3 / 1000.0

    # Bounding box for print bed check
    if components:
        all_verts = np.vstack([comp.mesh.vertices for comp in components])
        bb_min = all_verts.min(axis=0)
        bb_max = all_verts.max(axis=0)
        bb_size = bb_max - bb_min
    else:
        bb_size = np.zeros(3)

    return {
        "case_id": case_id,
        "files": exported_files,
        "component_count": len(components),
        "skipped_kwires": skipped_kwires,
        "kwire_note": "K-wires excluded from 3D print — use real metal K-wires for tactile practice" if skipped_kwires else None,
        "total_volume_cm3": round(total_volume_cm3, 2),
        "bounding_box_mm": {
            "x": round(float(bb_size[0]), 1),
            "y": round(float(bb_size[1]), 1),
            "z": round(float(bb_size[2]), 1),
        },
        "scale_factor": scale_factor,
        "print_estimate": {
            "material_g": round(total_volume_cm3 * 1.25, 1),  # PLA ~1.25 g/cm³
            "cost_usd": round(total_volume_cm3 * 1.25 * 0.025, 2),  # ~$25/kg PLA
        },
    }
