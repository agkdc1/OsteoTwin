"""Automated bone segmentation using TotalSegmentator.

TotalSegmentator provides AI-powered CT segmentation of 117 anatomical
structures including all major bones. Runs inference on GPU (RTX 3060 8GB
is sufficient for the fast model).

Usage:
    segmentor = BoneSegmentor()
    result = segmentor.segment(dicom_dir, output_dir, task="bones")
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

import trimesh

logger = logging.getLogger("osteotwin.segmentor")

# Bone structure names output by TotalSegmentator
BONE_STRUCTURES = [
    "humerus_left", "humerus_right",
    "radius_left", "radius_right",
    "ulna_left", "ulna_right",
    "scapula_left", "scapula_right",
    "clavicle_left", "clavicle_right",
    "femur_left", "femur_right",
    "tibia_left", "tibia_right",
    "fibula_left", "fibula_right",
    "patella_left", "patella_right",
    "hip_left", "hip_right",
    "sacrum",
    "vertebrae_C1", "vertebrae_C2", "vertebrae_C3",
    "vertebrae_C4", "vertebrae_C5", "vertebrae_C6", "vertebrae_C7",
    "vertebrae_T1", "vertebrae_T2", "vertebrae_T3", "vertebrae_T4",
    "vertebrae_T5", "vertebrae_T6", "vertebrae_T7", "vertebrae_T8",
    "vertebrae_T9", "vertebrae_T10", "vertebrae_T11", "vertebrae_T12",
    "vertebrae_L1", "vertebrae_L2", "vertebrae_L3", "vertebrae_L4", "vertebrae_L5",
    "rib_left_1", "rib_left_2", "rib_left_3", "rib_left_4", "rib_left_5",
    "rib_left_6", "rib_left_7", "rib_left_8", "rib_left_9", "rib_left_10",
    "rib_left_11", "rib_left_12",
    "rib_right_1", "rib_right_2", "rib_right_3", "rib_right_4", "rib_right_5",
    "rib_right_6", "rib_right_7", "rib_right_8", "rib_right_9", "rib_right_10",
    "rib_right_11", "rib_right_12",
]


class BoneSegmentor:
    """Wrapper around TotalSegmentator for bone segmentation."""

    def segment(
        self,
        input_path: str | Path,
        output_dir: str | Path,
        *,
        task: str = "total",
        fast: bool = True,
        roi_subset: Optional[list[str]] = None,
    ) -> dict:
        """Run TotalSegmentator on a DICOM directory or NIfTI file.

        Args:
            input_path: Path to DICOM directory or .nii.gz file.
            output_dir: Directory for segmentation masks (NIfTI).
            task: "total" (all 117 structures) or specific task.
            fast: Use fast model (3mm resolution, ~30s on GPU). Set False
                  for full resolution (~3min, needs more VRAM).
            roi_subset: If set, only extract these structures.

        Returns:
            Dict with segmentation metadata and list of output files.
        """
        input_path = Path(input_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "TotalSegmentator",
            "-i", str(input_path),
            "-o", str(output_dir),
            "--task", task,
        ]
        if fast:
            cmd.append("--fast")

        if roi_subset:
            cmd.extend(["--roi_subset"] + roi_subset)

        logger.info("Running TotalSegmentator: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min max
            )
            if result.returncode != 0:
                logger.error("TotalSegmentator failed: %s", result.stderr)
                return {
                    "success": False,
                    "error": result.stderr,
                    "output_dir": str(output_dir),
                }
        except FileNotFoundError:
            return {
                "success": False,
                "error": "TotalSegmentator not installed. Run: pip install TotalSegmentator",
                "output_dir": str(output_dir),
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Segmentation timed out (>10 minutes)",
                "output_dir": str(output_dir),
            }

        # Collect output masks
        nifti_files = sorted(output_dir.glob("*.nii.gz"))
        bone_files = [
            f for f in nifti_files
            if f.stem.replace(".nii", "") in BONE_STRUCTURES
        ]

        return {
            "success": True,
            "output_dir": str(output_dir),
            "total_structures": len(nifti_files),
            "bone_structures": len(bone_files),
            "bone_files": [str(f) for f in bone_files],
            "all_files": [str(f) for f in nifti_files],
        }

    def nifti_mask_to_mesh(
        self,
        nifti_path: str | Path,
        output_stl: Optional[str | Path] = None,
        *,
        smooth_iterations: int = 15,
    ) -> trimesh.Trimesh:
        """Convert a binary NIfTI segmentation mask to a 3D mesh.

        Uses VTK marching cubes on the binary mask volume.

        Args:
            nifti_path: Path to .nii.gz binary mask file.
            output_stl: Optional path to save as STL.
            smooth_iterations: Smoothing passes (default 15).

        Returns:
            trimesh.Trimesh of the segmented structure.
        """
        import numpy as np
        import vtk
        from vtk.util.numpy_support import numpy_to_vtk

        # Load NIfTI
        reader = vtk.vtkNIFTIImageReader()
        reader.SetFileName(str(nifti_path))
        reader.Update()

        image = reader.GetOutput()

        # Marching cubes at threshold 0.5 (binary mask)
        mc = vtk.vtkMarchingCubes()
        mc.SetInputData(image)
        mc.SetValue(0, 0.5)
        mc.ComputeNormalsOn()
        mc.Update()

        polydata = mc.GetOutput()

        if polydata.GetNumberOfPoints() == 0:
            raise ValueError(f"No surface found in {nifti_path}")

        # Smooth
        if smooth_iterations > 0:
            smoother = vtk.vtkSmoothPolyDataFilter()
            smoother.SetInputData(polydata)
            smoother.SetNumberOfIterations(smooth_iterations)
            smoother.SetRelaxationFactor(0.1)
            smoother.Update()
            polydata = smoother.GetOutput()

        # Decimate to manageable size
        decimator = vtk.vtkDecimatePro()
        decimator.SetInputData(polydata)
        decimator.SetTargetReduction(0.5)
        decimator.PreserveTopologyOn()
        decimator.Update()
        polydata = decimator.GetOutput()

        # Convert to trimesh
        vertices = np.array(
            [polydata.GetPoint(i) for i in range(polydata.GetNumberOfPoints())]
        )
        faces = []
        for i in range(polydata.GetNumberOfCells()):
            cell = polydata.GetCell(i)
            if cell.GetNumberOfPoints() == 3:
                faces.append([cell.GetPointId(j) for j in range(3)])
        faces = np.array(faces)

        mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        mesh.fix_normals()

        if output_stl:
            output_stl = Path(output_stl)
            output_stl.parent.mkdir(parents=True, exist_ok=True)
            mesh.export(str(output_stl))
            logger.info("Exported mesh to %s (%d verts)", output_stl, len(mesh.vertices))

        return mesh
