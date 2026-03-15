"""API routes for DICOM ingestion and mesh processing."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import verify_api_key
from .. import config
from .dicom_to_mesh import load_dicom_volume, extract_bone_mesh, segment_fragments

router = APIRouter(prefix="/api/v1/dicom", tags=["dicom"])


class DicomIngestRequest(BaseModel):
    case_id: str = Field(..., description="FractureCase ID")
    dicom_dir: str = Field(..., description="Path to directory containing .dcm files")
    hu_threshold: int = Field(default=300, description="Hounsfield Unit threshold for bone")
    decimate_ratio: float = Field(default=0.5, ge=0.1, le=1.0)


class DicomIngestResponse(BaseModel):
    case_id: str
    volume_shape: list[int]
    spacing_mm: list[float]
    fragment_count: int
    mesh_files: list[str]
    total_vertices: int
    total_faces: int


@router.post(
    "/ingest",
    response_model=DicomIngestResponse,
    dependencies=[Depends(verify_api_key)],
)
async def ingest_dicom(req: DicomIngestRequest) -> DicomIngestResponse:
    """Ingest a DICOM series: extract bone mesh and segment fragments.

    Pipeline: DICOM dir → numpy volume → VTK marching cubes → trimesh → STL files
    """
    dicom_path = Path(req.dicom_dir)
    if not dicom_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DICOM directory not found: {req.dicom_dir}",
        )

    try:
        # Step 1: Load DICOM volume
        volume, metadata = load_dicom_volume(dicom_path)

        # Step 2: Extract bone surface
        output_dir = config.MESH_CACHE_DIR / req.case_id
        output_dir.mkdir(parents=True, exist_ok=True)

        full_mesh_path = output_dir / "bone_full.stl"
        bone_mesh = extract_bone_mesh(
            volume,
            metadata["spacing"],
            hu_threshold=req.hu_threshold,
            output_path=full_mesh_path,
            decimate_ratio=req.decimate_ratio,
        )

        # Step 3: Segment into fragments
        fragments = segment_fragments(bone_mesh)

        mesh_files = [str(full_mesh_path)]
        total_verts = len(bone_mesh.vertices)
        total_faces = len(bone_mesh.faces)

        for i, frag in enumerate(fragments):
            frag_path = output_dir / f"fragment_{i:02d}.stl"
            frag.export(str(frag_path))
            mesh_files.append(str(frag_path))
            total_verts += len(frag.vertices)
            total_faces += len(frag.faces)

        return DicomIngestResponse(
            case_id=req.case_id,
            volume_shape=list(volume.shape),
            spacing_mm=metadata["spacing"],
            fragment_count=len(fragments),
            mesh_files=mesh_files,
            total_vertices=total_verts,
            total_faces=total_faces,
        )

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DICOM processing failed: {exc}")
