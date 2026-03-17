"""THUMS mesh decimation for real-time Three.js rendering.

High-density FEA meshes (10K-50K faces) are too heavy for interactive
3D viewing. This tool creates LOD (Level of Detail) variants:
- LOD0: original (FEA-grade)
- LOD1: 50% decimation (interactive manipulation)
- LOD2: 25% decimation (scene overview, many parts visible)

Preserves anatomical boundaries by using quadric decimation
(vertex clustering would destroy thin structures like cortical shells).

Usage:
    python fea/thums_decimator.py AM50                    # all parts
    python fea/thums_decimator.py AM50 --region lower     # lower extremity
    python fea/thums_decimator.py AM50 --target-faces 2000  # custom target
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import trimesh
import meshio

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("thums_decimator")

THUMS_OUTPUT = Path(__file__).parent / "thums_output"


def decimate_mesh(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Decimate a mesh to approximately target_faces using simplify_quadric_decimation.

    Falls back to random face sampling if quadric decimation is unavailable.
    """
    if len(mesh.faces) <= target_faces:
        return mesh.copy()

    try:
        decimated = mesh.simplify_quadric_decimation(target_faces)
        if len(decimated.faces) > 0:
            return decimated
    except Exception:
        pass

    # Fallback: subsample faces
    indices = np.random.choice(len(mesh.faces), size=min(target_faces, len(mesh.faces)), replace=False)
    submesh = mesh.submesh([indices], append=True)
    return submesh


def _load_vtk_as_trimesh(vtk_path: Path) -> trimesh.Trimesh | None:
    """Load a VTK unstructured grid and extract surface triangles as trimesh."""
    m = meshio.read(str(vtk_path))
    if len(m.points) == 0:
        return None

    faces = []
    for cell_block in m.cells:
        if cell_block.type == "hexahedron":
            for hex_nodes in cell_block.data:
                for face_ids in [(0,1,2,3),(4,5,6,7),(0,1,5,4),(2,3,7,6),(0,3,7,4),(1,2,6,5)]:
                    f = hex_nodes[list(face_ids)]
                    faces.append([f[0], f[1], f[2]])
                    faces.append([f[0], f[2], f[3]])
        elif cell_block.type == "tetra":
            for tet in cell_block.data:
                for face_ids in [(0,1,2),(0,1,3),(0,2,3),(1,2,3)]:
                    faces.append(tet[list(face_ids)].tolist())
        elif cell_block.type in ("quad",):
            for f in cell_block.data:
                faces.append([f[0], f[1], f[2]])
                faces.append([f[0], f[2], f[3]])
        elif cell_block.type in ("triangle",):
            faces.extend(f.tolist() for f in cell_block.data)
        elif cell_block.type == "wedge":
            for w in cell_block.data:
                # 2 triangular faces + 3 quad faces
                faces.append([w[0], w[1], w[2]])
                faces.append([w[3], w[4], w[5]])
                for qf in [(0,1,4,3),(1,2,5,4),(0,2,5,3)]:
                    f = w[list(qf)]
                    faces.append([f[0], f[1], f[2]])
                    faces.append([f[0], f[2], f[3]])

    if not faces:
        return None

    return trimesh.Trimesh(vertices=m.points, faces=np.array(faces), process=False)


def decimate_part(
    vtk_path: Path,
    output_dir: Path,
    part_id: int,
    lod_targets: dict[str, int],
) -> dict:
    """Decimate a single VTK part into multiple LODs.

    Args:
        vtk_path: Path to source VTK file
        output_dir: Base output directory
        part_id: THUMS part ID
        lod_targets: {"lod1": 5000, "lod2": 2000} face targets

    Returns:
        Dict with LOD metadata
    """
    try:
        mesh = _load_vtk_as_trimesh(vtk_path)
        if mesh is None or len(mesh.faces) == 0:
            return {"part_id": part_id, "error": "empty mesh"}
    except Exception as exc:
        return {"part_id": part_id, "error": str(exc)}

    original_faces = len(mesh.faces)
    results = {
        "part_id": part_id,
        "original_faces": original_faces,
        "lods": {},
    }

    for lod_name, target in lod_targets.items():
        if original_faces <= target:
            # Already small enough, just copy
            lod_dir = output_dir / lod_name
            lod_dir.mkdir(parents=True, exist_ok=True)
            out_path = lod_dir / f"part_{part_id}.stl"
            mesh.export(str(out_path))
            results["lods"][lod_name] = {
                "faces": original_faces,
                "file": str(out_path),
                "ratio": 1.0,
            }
        else:
            decimated = decimate_mesh(mesh, target)
            lod_dir = output_dir / lod_name
            lod_dir.mkdir(parents=True, exist_ok=True)
            out_path = lod_dir / f"part_{part_id}.stl"
            decimated.export(str(out_path))
            results["lods"][lod_name] = {
                "faces": len(decimated.faces),
                "file": str(out_path),
                "ratio": round(len(decimated.faces) / original_faces, 3),
            }

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="THUMS Mesh Decimator")
    parser.add_argument("subject", help="THUMS subject (AM50, AF50, etc.)")
    parser.add_argument("--region", default="all", help="Region filter")
    parser.add_argument("--target-faces", type=int, default=0, help="Custom LOD2 target (0=auto)")
    parser.add_argument("--max-parts", type=int, default=0, help="Limit parts (0=all)")
    args = parser.parse_args()

    subject_dir = THUMS_OUTPUT / args.subject
    vtk_dir = subject_dir / "vtk"
    lod_dir = subject_dir / "lod"

    if not vtk_dir.exists():
        logger.error("VTK directory not found: %s", vtk_dir)
        sys.exit(1)

    # Load anatomical map for region filtering
    anat_path = subject_dir / "thums_anatomical_map.json"
    with open(anat_path) as f:
        anat_map = json.load(f)

    region_map = {
        "upper": ["upper_extremity_right", "upper_extremity_left"],
        "lower": ["lower_extremity_right", "lower_extremity_left"],
        "head": ["head"],
        "thorax": ["thorax"],
    }

    if args.region != "all":
        regions = region_map.get(args.region, [args.region])
        anat_map = [p for p in anat_map if p["region"] in regions]

    # Only process parts that have VTK files
    vtk_files = {int(f.stem.split("_")[1]): f for f in vtk_dir.glob("part_*.vtk")}
    parts_to_process = [p for p in anat_map if p["part_id"] in vtk_files]

    if args.max_parts > 0:
        parts_to_process = parts_to_process[:args.max_parts]

    logger.info("Decimating %d parts for %s (region=%s)", len(parts_to_process), args.subject, args.region)

    # LOD targets
    lod2_target = args.target_faces if args.target_faces > 0 else 2000
    lod_targets = {
        "lod1": 5000,   # interactive manipulation
        "lod2": lod2_target,  # scene overview
    }

    manifest = []
    for idx, part in enumerate(parts_to_process):
        pid = part["part_id"]
        vtk_path = vtk_files[pid]
        result = decimate_part(vtk_path, lod_dir, pid, lod_targets)
        manifest.append(result)

        if (idx + 1) % 50 == 0:
            logger.info("  Decimated %d/%d parts...", idx + 1, len(parts_to_process))

    # Write manifest
    lod_dir.mkdir(parents=True, exist_ok=True)
    with open(lod_dir / "decimation_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Summary
    successful = [m for m in manifest if "error" not in m]
    total_original = sum(m["original_faces"] for m in successful)
    total_lod1 = sum(m["lods"].get("lod1", {}).get("faces", 0) for m in successful)
    total_lod2 = sum(m["lods"].get("lod2", {}).get("faces", 0) for m in successful)

    logger.info("Decimation complete:")
    logger.info("  Parts processed: %d / %d", len(successful), len(manifest))
    logger.info("  Original:  %d faces total", total_original)
    logger.info("  LOD1 (50%%): %d faces (%.0f%% reduction)", total_lod1, (1 - total_lod1/max(total_original,1)) * 100)
    logger.info("  LOD2 (25%%): %d faces (%.0f%% reduction)", total_lod2, (1 - total_lod2/max(total_original,1)) * 100)


if __name__ == "__main__":
    main()
