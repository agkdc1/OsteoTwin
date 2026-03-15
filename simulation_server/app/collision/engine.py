"""Trimesh-based rigid-body collision detection engine.

Phase 1: Lightweight ray-casting and mesh-mesh intersection.
No FEA, no soft-tissue dynamics — strict rigid-body only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import trimesh

logger = logging.getLogger("osteotwin.collision")


class CollisionEngine:
    """Manages loaded meshes and performs collision queries.

    Each mesh is stored with an ID and a label (e.g., "distal_fragment",
    "lcp_plate_6hole"). All operations are deterministic.
    """

    def __init__(self) -> None:
        # mesh_id -> { "mesh": trimesh.Trimesh, "label": str, "type": str }
        self._meshes: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Mesh management
    # ------------------------------------------------------------------

    def load_mesh(
        self,
        mesh_id: str,
        file_path: str | Path,
        label: str = "",
        mesh_type: str = "bone",
    ) -> dict:
        """Load an STL/OBJ/PLY mesh file into the scene.

        Args:
            mesh_id: Unique identifier for this mesh.
            file_path: Path to the mesh file.
            label: Human-readable label.
            mesh_type: One of "bone", "hardware", "boundary".

        Returns:
            Dict with mesh metadata (vertex count, bounds, etc.)
        """
        mesh = trimesh.load(str(file_path), force="mesh")
        if not isinstance(mesh, trimesh.Trimesh):
            raise ValueError(f"File {file_path} did not load as a single mesh")

        self._meshes[mesh_id] = {
            "mesh": mesh,
            "label": label or mesh_id,
            "type": mesh_type,
        }

        bounds = mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]
        logger.info(
            "Loaded mesh '%s' (%s): %d vertices, %d faces",
            mesh_id,
            mesh_type,
            len(mesh.vertices),
            len(mesh.faces),
        )
        return {
            "mesh_id": mesh_id,
            "label": label,
            "type": mesh_type,
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
            "bounds_min": bounds[0].tolist(),
            "bounds_max": bounds[1].tolist(),
        }

    def load_mesh_from_trimesh(
        self,
        mesh_id: str,
        mesh: trimesh.Trimesh,
        label: str = "",
        mesh_type: str = "bone",
    ) -> None:
        """Load a pre-constructed trimesh object into the scene."""
        self._meshes[mesh_id] = {
            "mesh": mesh,
            "label": label or mesh_id,
            "type": mesh_type,
        }

    def remove_mesh(self, mesh_id: str) -> bool:
        return self._meshes.pop(mesh_id, None) is not None

    def list_meshes(self) -> list[dict]:
        return [
            {
                "mesh_id": mid,
                "label": info["label"],
                "type": info["type"],
                "vertex_count": len(info["mesh"].vertices),
            }
            for mid, info in self._meshes.items()
        ]

    # ------------------------------------------------------------------
    # Ray casting (K-wire trajectory check)
    # ------------------------------------------------------------------

    def ray_cast(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        max_length: float | None = None,
    ) -> list[dict]:
        """Cast a ray and find all intersections with loaded meshes.

        Args:
            origin: Ray origin point (x, y, z) in mm.
            direction: Ray direction vector (will be normalized).
            max_length: Optional maximum ray length in mm.

        Returns:
            List of intersection dicts sorted by distance, each containing:
            - mesh_id, mesh_label, hit_point, distance_mm, face_index, is_entry
        """
        origin_np = np.array(origin, dtype=np.float64)
        dir_np = np.array(direction, dtype=np.float64)
        dir_norm = dir_np / np.linalg.norm(dir_np)

        all_hits: list[dict] = []

        for mesh_id, info in self._meshes.items():
            mesh: trimesh.Trimesh = info["mesh"]

            # trimesh ray-mesh intersection
            locations, index_ray, index_tri = mesh.ray.intersects_location(
                ray_origins=origin_np.reshape(1, 3),
                ray_directions=dir_norm.reshape(1, 3),
            )

            if len(locations) == 0:
                continue

            for i, loc in enumerate(locations):
                distance = float(np.linalg.norm(loc - origin_np))

                # Filter by max length
                if max_length is not None and distance > max_length:
                    continue

                # Determine entry/exit using face normal
                face_idx = int(index_tri[i])
                face_normal = mesh.face_normals[face_idx]
                dot = float(np.dot(dir_norm, face_normal))
                is_entry = dot < 0  # entering if ray opposes the normal

                all_hits.append(
                    {
                        "mesh_id": mesh_id,
                        "mesh_label": info["label"],
                        "hit_point": loc.tolist(),
                        "distance_mm": round(distance, 3),
                        "face_index": face_idx,
                        "is_entry": is_entry,
                        "mesh_type": info["type"],
                    }
                )

        # Sort by distance
        all_hits.sort(key=lambda h: h["distance_mm"])
        return all_hits

    # ------------------------------------------------------------------
    # Mesh-mesh intersection (fragment-fragment / fragment-hardware)
    # ------------------------------------------------------------------

    def check_intersection(
        self, mesh_id_a: str, mesh_id_b: str
    ) -> dict:
        """Check if two meshes intersect (boolean collision).

        Returns:
            Dict with collides (bool), and if colliding, the intersection volume.
        """
        if mesh_id_a not in self._meshes:
            raise ValueError(f"Mesh '{mesh_id_a}' not loaded")
        if mesh_id_b not in self._meshes:
            raise ValueError(f"Mesh '{mesh_id_b}' not loaded")

        mesh_a: trimesh.Trimesh = self._meshes[mesh_id_a]["mesh"]
        mesh_b: trimesh.Trimesh = self._meshes[mesh_id_b]["mesh"]

        # Fast AABB check first
        if not mesh_a.bounds_tree or not mesh_b.bounds_tree:
            pass  # trimesh handles this internally

        try:
            collision_manager = trimesh.collision.CollisionManager()
            collision_manager.add_object(mesh_id_a, mesh_a)
            collides, names = collision_manager.in_collision_single(
                mesh_b, return_names=True
            )
        except Exception as exc:
            logger.warning("Collision check failed: %s", exc)
            return {
                "mesh_a": mesh_id_a,
                "mesh_b": mesh_id_b,
                "collides": False,
                "error": str(exc),
            }

        # Minimum distance between surfaces
        try:
            closest_point, distance, _ = trimesh.proximity.closest_point(
                mesh_a, mesh_b.vertices
            )
            min_distance = float(np.min(distance))
        except Exception:
            min_distance = None

        return {
            "mesh_a": mesh_id_a,
            "mesh_b": mesh_id_b,
            "collides": bool(collides),
            "min_distance_mm": min_distance,
            "label_a": self._meshes[mesh_id_a]["label"],
            "label_b": self._meshes[mesh_id_b]["label"],
        }
