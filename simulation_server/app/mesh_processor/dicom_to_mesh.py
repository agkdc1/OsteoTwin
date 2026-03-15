"""DICOM → 3D Mesh extraction pipeline using pydicom + VTK.

Phase 1: Extract bone surfaces from CT data using Hounsfield thresholding
and VTK's marching cubes algorithm. Export as STL for collision detection.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("osteotwin.dicom")


def load_dicom_volume(dicom_dir: str | Path) -> tuple[np.ndarray, dict]:
    """Load a DICOM series from a directory into a 3D numpy volume.

    Args:
        dicom_dir: Path to directory containing .dcm files.

    Returns:
        Tuple of (volume_array, metadata_dict).
        Volume is in Hounsfield Units (HU).
    """
    import pydicom

    dicom_path = Path(dicom_dir)
    dcm_files = sorted(
        dicom_path.glob("*.dcm"),
        key=lambda f: int(pydicom.dcmread(str(f), stop_before_pixels=True).InstanceNumber),
    )

    if not dcm_files:
        # Try uppercase extension
        dcm_files = sorted(
            dicom_path.glob("*.DCM"),
            key=lambda f: int(pydicom.dcmread(str(f), stop_before_pixels=True).InstanceNumber),
        )

    if not dcm_files:
        raise FileNotFoundError(f"No DICOM files found in {dicom_dir}")

    # Read first slice for metadata
    first = pydicom.dcmread(str(dcm_files[0]))
    rows, cols = int(first.Rows), int(first.Columns)
    slice_count = len(dcm_files)

    # Read all slices into volume
    volume = np.zeros((slice_count, rows, cols), dtype=np.int16)

    for i, dcm_file in enumerate(dcm_files):
        ds = pydicom.dcmread(str(dcm_file))
        # Convert to Hounsfield Units
        slope = float(getattr(ds, "RescaleSlope", 1))
        intercept = float(getattr(ds, "RescaleIntercept", 0))
        volume[i] = ds.pixel_array.astype(np.int16) * slope + intercept

    # Extract metadata
    pixel_spacing = [float(x) for x in getattr(first, "PixelSpacing", [1.0, 1.0])]
    slice_thickness = float(getattr(first, "SliceThickness", 1.0))

    metadata = {
        "rows": rows,
        "cols": cols,
        "slice_count": slice_count,
        "pixel_spacing_mm": pixel_spacing,
        "slice_thickness_mm": slice_thickness,
        "spacing": [pixel_spacing[0], pixel_spacing[1], slice_thickness],
        "modality": str(getattr(first, "Modality", "CT")),
        "patient_id": str(getattr(first, "PatientID", "anonymous")),
    }

    logger.info(
        "Loaded DICOM volume: %dx%dx%d (spacing: %.2f x %.2f x %.2f mm)",
        cols, rows, slice_count,
        pixel_spacing[0], pixel_spacing[1], slice_thickness,
    )
    return volume, metadata


def extract_bone_mesh(
    volume: np.ndarray,
    spacing: list[float],
    *,
    hu_threshold: int = 300,
    output_path: Optional[str | Path] = None,
    decimate_ratio: float = 0.5,
) -> "trimesh.Trimesh":
    """Extract bone surfaces from a CT volume using marching cubes.

    Args:
        volume: 3D numpy array in Hounsfield Units.
        spacing: Voxel spacing [x, y, z] in mm.
        hu_threshold: Hounsfield Unit threshold for bone (default 300 HU).
            Cortical bone: ~700-3000 HU
            Cancellous bone: ~300-700 HU
        output_path: Optional path to save the mesh as STL.
        decimate_ratio: Fraction of faces to keep (0.5 = reduce by half).

    Returns:
        trimesh.Trimesh of the bone surface.
    """
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk
    import trimesh

    # Create VTK image from numpy volume
    vtk_image = vtk.vtkImageData()
    vtk_image.SetDimensions(volume.shape[2], volume.shape[1], volume.shape[0])
    vtk_image.SetSpacing(spacing[0], spacing[1], spacing[2])
    vtk_image.SetOrigin(0, 0, 0)

    flat = volume.flatten(order="C").astype(np.int16)
    vtk_array = numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_SHORT)
    vtk_image.GetPointData().SetScalars(vtk_array)

    # Marching cubes
    mc = vtk.vtkMarchingCubes()
    mc.SetInputData(vtk_image)
    mc.SetValue(0, hu_threshold)
    mc.ComputeNormalsOn()
    mc.Update()

    polydata = mc.GetOutput()
    n_verts = polydata.GetNumberOfPoints()
    n_faces = polydata.GetNumberOfCells()

    if n_verts == 0:
        raise ValueError(
            f"No surfaces found at HU threshold {hu_threshold}. "
            "Try lowering the threshold."
        )

    logger.info(
        "Marching cubes: %d vertices, %d faces (threshold %d HU)",
        n_verts, n_faces, hu_threshold,
    )

    # Optional decimation for Phase 1 (reduce mesh complexity for collision detection)
    if decimate_ratio < 1.0:
        decimator = vtk.vtkDecimatePro()
        decimator.SetInputData(polydata)
        decimator.SetTargetReduction(1.0 - decimate_ratio)
        decimator.PreserveTopologyOn()
        decimator.Update()
        polydata = decimator.GetOutput()
        logger.info(
            "Decimated to %d vertices, %d faces",
            polydata.GetNumberOfPoints(),
            polydata.GetNumberOfCells(),
        )

    # Smooth
    smoother = vtk.vtkSmoothPolyDataFilter()
    smoother.SetInputData(polydata)
    smoother.SetNumberOfIterations(20)
    smoother.SetRelaxationFactor(0.1)
    smoother.FeatureEdgeSmoothingOff()
    smoother.BoundarySmoothingOn()
    smoother.Update()
    polydata = smoother.GetOutput()

    # Convert VTK polydata to trimesh
    vertices = np.array(
        [polydata.GetPoint(i) for i in range(polydata.GetNumberOfPoints())]
    )
    faces = []
    for i in range(polydata.GetNumberOfCells()):
        cell = polydata.GetCell(i)
        if cell.GetNumberOfPoints() == 3:
            faces.append(
                [cell.GetPointId(j) for j in range(3)]
            )
    faces = np.array(faces)

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.fix_normals()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(output_path))
        logger.info("Mesh exported to %s", output_path)

    return mesh


def segment_fragments(
    mesh: "trimesh.Trimesh",
    *,
    min_fragment_vertices: int = 100,
) -> list["trimesh.Trimesh"]:
    """Split a bone mesh into separate fragments (connected components).

    In a fracture, the bone mesh will have disconnected regions corresponding
    to individual fragments. This function separates them.

    Args:
        mesh: Input bone mesh (may contain multiple fragments).
        min_fragment_vertices: Minimum vertices to count as a fragment
            (filters out noise/artifacts).

    Returns:
        List of trimesh.Trimesh objects, one per fragment.
    """
    components = mesh.split(only_watertight=False)
    fragments = [
        c for c in components
        if len(c.vertices) >= min_fragment_vertices
    ]

    logger.info(
        "Segmented %d fragment(s) from %d connected components (min_verts=%d)",
        len(fragments), len(components), min_fragment_vertices,
    )
    return fragments
