"""API routes for automated DICOM segmentation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import verify_api_key
from .. import config
from .segmentor import BoneSegmentor

router = APIRouter(prefix="/api/v1/segment", tags=["segmentation"])

_segmentor = BoneSegmentor()


class SegmentRequest(BaseModel):
    case_id: str = Field(..., description="FractureCase ID")
    input_path: str = Field(
        ..., description="Path to DICOM directory or .nii.gz file"
    )
    fast: bool = Field(
        default=True,
        description="Use fast model (3mm, ~30s) vs full (1.5mm, ~3min)",
    )
    roi_subset: Optional[list[str]] = Field(
        None,
        description='Only segment these structures, e.g. ["radius_left", "ulna_left"]',
    )
    convert_to_stl: bool = Field(
        default=True,
        description="Convert segmentation masks to STL meshes",
    )


@router.post("/auto", dependencies=[Depends(verify_api_key)])
async def auto_segment(req: SegmentRequest):
    """Run TotalSegmentator on DICOM data to automatically segment bones.

    Pipeline: DICOM → TotalSegmentator → NIfTI masks → STL meshes
    """
    input_path = Path(req.input_path)
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input not found: {req.input_path}")

    # Output directories
    seg_dir = config.MESH_CACHE_DIR / req.case_id / "segmentation"
    mesh_dir = config.MESH_CACHE_DIR / req.case_id / "meshes"

    # Step 1: Run TotalSegmentator
    seg_result = _segmentor.segment(
        input_path,
        seg_dir,
        fast=req.fast,
        roi_subset=req.roi_subset,
    )

    if not seg_result["success"]:
        raise HTTPException(status_code=500, detail=seg_result.get("error", "Segmentation failed"))

    response = {
        "case_id": req.case_id,
        "segmentation": seg_result,
        "meshes": [],
    }

    # Step 2: Convert masks to STL
    if req.convert_to_stl and seg_result.get("bone_files"):
        mesh_dir.mkdir(parents=True, exist_ok=True)
        for nifti_path in seg_result["bone_files"]:
            nifti = Path(nifti_path)
            structure_name = nifti.stem.replace(".nii", "")
            stl_path = mesh_dir / f"{structure_name}.stl"

            try:
                mesh = _segmentor.nifti_mask_to_mesh(nifti, output_stl=stl_path)
                response["meshes"].append({
                    "structure": structure_name,
                    "stl_path": str(stl_path),
                    "vertex_count": len(mesh.vertices),
                    "face_count": len(mesh.faces),
                })
            except ValueError as exc:
                response["meshes"].append({
                    "structure": structure_name,
                    "error": str(exc),
                })

    return response
