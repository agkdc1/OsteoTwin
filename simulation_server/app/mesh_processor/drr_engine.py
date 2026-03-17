"""Digitally Reconstructed Radiograph (DRR) Engine.

Generates simulated C-arm fluoroscopy images from 3D bone meshes.
This allows surgeons to preview what the C-arm monitor will show
at specific projection angles BEFORE entering the OR.

Method: ray-casting through the bone mesh volume. Each pixel's
intensity is proportional to the total bone thickness traversed
by the ray (Beer-Lambert attenuation model).

Supported projections:
- AP (Anteroposterior): Y-axis beam (posterior -> anterior)
- Lateral: X-axis beam (left -> right or right -> left)
- Oblique: arbitrary angle around the long axis of the bone

Usage:
    engine = DRREngine()
    engine.load_bone_meshes([mesh1, mesh2])
    image = engine.render_ap(image_size=(512, 512))
    image.save("drr_ap.png")
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import trimesh

logger = logging.getLogger("osteotwin.drr")


class DRREngine:
    """Generates Digitally Reconstructed Radiographs from bone meshes.

    Uses parallel ray-casting (orthographic projection) through
    the combined bone volume. Intensity = sum of intersection lengths
    through bone (thicker bone = brighter on DRR).
    """

    def __init__(self):
        self._meshes: list[trimesh.Trimesh] = []
        self._combined: Optional[trimesh.Trimesh] = None
        self._bounds: Optional[np.ndarray] = None

    def load_bone_meshes(self, meshes: list[trimesh.Trimesh]) -> dict:
        """Load bone meshes for DRR rendering."""
        self._meshes = meshes
        if meshes:
            self._combined = trimesh.util.concatenate(meshes)
            self._bounds = self._combined.bounds  # [[min_x,y,z], [max_x,y,z]]
        else:
            self._combined = None
            self._bounds = None

        total_verts = sum(len(m.vertices) for m in meshes)
        total_faces = sum(len(m.faces) for m in meshes)
        logger.info("DRR engine loaded %d meshes (%d verts, %d faces)",
                     len(meshes), total_verts, total_faces)
        return {
            "mesh_count": len(meshes),
            "total_vertices": total_verts,
            "total_faces": total_faces,
        }

    def render(
        self,
        projection: str = "ap",
        image_size: tuple[int, int] = (512, 512),
        angle_deg: float = 0.0,
        padding_mm: float = 20.0,
        invert: bool = True,
    ) -> np.ndarray:
        """Render a DRR image for the given projection.

        Args:
            projection: "ap" (front), "lateral" (side), or "oblique"
            image_size: (width, height) in pixels
            angle_deg: For oblique projection, rotation around Z-axis (LPS Superior)
            padding_mm: Extra padding around the bone bounding box
            invert: If True, bone=white on black (standard X-ray look)

        Returns:
            2D numpy array (uint8, 0-255) representing the DRR image.
        """
        if self._combined is None or self._bounds is None:
            return np.zeros(image_size[::-1], dtype=np.uint8)

        bb_min, bb_max = self._bounds
        bb_size = bb_max - bb_min
        center = (bb_min + bb_max) / 2

        W, H = image_size

        # Determine ray direction and image plane based on projection
        if projection == "ap":
            # Beam goes Y+ to Y- (posterior to anterior)
            ray_dir = np.array([0, -1, 0], dtype=np.float64)
            # Image plane: X (left-right) x Z (superior-inferior)
            u_axis = np.array([1, 0, 0], dtype=np.float64)  # image horizontal
            v_axis = np.array([0, 0, 1], dtype=np.float64)  # image vertical
            plane_width = bb_size[0] + 2 * padding_mm
            plane_height = bb_size[2] + 2 * padding_mm
            ray_origin_offset = center.copy()
            ray_origin_offset[1] = bb_max[1] + 50  # start behind

        elif projection == "lateral":
            # Beam goes X+ to X- (left to right in LPS)
            ray_dir = np.array([-1, 0, 0], dtype=np.float64)
            u_axis = np.array([0, -1, 0], dtype=np.float64)  # anterior-posterior
            v_axis = np.array([0, 0, 1], dtype=np.float64)   # superior-inferior
            plane_width = bb_size[1] + 2 * padding_mm
            plane_height = bb_size[2] + 2 * padding_mm
            ray_origin_offset = center.copy()
            ray_origin_offset[0] = bb_max[0] + 50

        elif projection == "oblique":
            # Rotate ray direction around Z-axis by angle_deg
            rad = math.radians(angle_deg)
            ray_dir = np.array([-math.sin(rad), -math.cos(rad), 0], dtype=np.float64)
            u_axis = np.array([math.cos(rad), -math.sin(rad), 0], dtype=np.float64)
            v_axis = np.array([0, 0, 1], dtype=np.float64)
            plane_width = max(bb_size[0], bb_size[1]) + 2 * padding_mm
            plane_height = bb_size[2] + 2 * padding_mm
            ray_origin_offset = center - ray_dir * (max(bb_size) + 50)

        else:
            raise ValueError(f"Unknown projection: {projection}")

        # Generate ray grid
        u_coords = np.linspace(-plane_width / 2, plane_width / 2, W)
        v_coords = np.linspace(-plane_height / 2, plane_height / 2, H)

        # Build ray origins on the image plane
        origins = np.zeros((W * H, 3), dtype=np.float64)
        for j, v in enumerate(v_coords):
            for i, u in enumerate(u_coords):
                idx = j * W + i
                origins[idx] = ray_origin_offset + u * u_axis + v * v_axis

        directions = np.tile(ray_dir, (W * H, 1))

        # Ray-cast through all meshes
        # For each ray, sum the total bone thickness traversed
        thickness = np.zeros(W * H, dtype=np.float64)

        # Process in batches to manage memory
        batch_size = 10000
        for start in range(0, len(origins), batch_size):
            end = min(start + batch_size, len(origins))
            batch_origins = origins[start:end]
            batch_dirs = directions[start:end]

            locations, index_ray, _ = self._combined.ray.intersects_location(
                ray_origins=batch_origins,
                ray_directions=batch_dirs,
            )

            if len(locations) == 0:
                continue

            # For each ray, find entry/exit pairs and sum distances
            for ray_idx in range(end - start):
                mask = index_ray == ray_idx
                if not np.any(mask):
                    continue
                hits = locations[mask]
                # Sort by distance along ray
                dists = np.dot(hits - batch_origins[ray_idx], batch_dirs[ray_idx])
                dists.sort()
                # Sum pairwise distances (entry-exit pairs)
                total = 0.0
                for k in range(0, len(dists) - 1, 2):
                    total += dists[k + 1] - dists[k]
                thickness[start + ray_idx] = total

        # Normalize to 0-255
        image = thickness.reshape(H, W)
        if image.max() > 0:
            image = (image / image.max() * 255).astype(np.uint8)
        else:
            image = image.astype(np.uint8)

        if invert:
            # Standard X-ray: bone=white, air=black
            pass  # already white=thick
        else:
            image = 255 - image

        # Flip vertically (image origin is top-left, but Z+ is up)
        image = np.flipud(image)

        return image

    def render_to_png(
        self,
        output_path: str,
        projection: str = "ap",
        image_size: tuple[int, int] = (512, 512),
        angle_deg: float = 0.0,
    ) -> str:
        """Render DRR and save as PNG file."""
        image = self.render(projection, image_size, angle_deg)

        try:
            from PIL import Image
            img = Image.fromarray(image, mode="L")
            img.save(output_path)
        except ImportError:
            # Fallback: save as raw numpy
            np.save(output_path.replace(".png", ".npy"), image)
            output_path = output_path.replace(".png", ".npy")

        logger.info("DRR rendered: %s (%s, %dx%d)", output_path, projection, *image_size)
        return output_path

    def render_multiview(
        self,
        output_dir: str,
        image_size: tuple[int, int] = (512, 512),
        prefix: str = "drr",
    ) -> list[str]:
        """Render standard C-arm views: AP, Lateral, and 2 obliques."""
        from pathlib import Path
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        views = [
            ("ap", 0.0),
            ("lateral", 0.0),
            ("oblique", 30.0),
            ("oblique", 45.0),
            ("oblique", 60.0),
        ]

        paths = []
        for proj, angle in views:
            name = f"{prefix}_{proj}" + (f"_{int(angle)}deg" if proj == "oblique" else "") + ".png"
            path = self.render_to_png(str(out / name), proj, image_size, angle)
            paths.append(path)

        return paths
