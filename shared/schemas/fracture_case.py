"""Core schema for fracture case data ingested from DICOM."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AOClassification(BaseModel):
    """AO/OTA fracture classification (e.g., 23-A2.1 = distal radius)."""

    bone_segment: str = Field(
        ..., description="Bone & segment code, e.g. '23' for radius/ulna distal"
    )
    fracture_type: str = Field(
        ..., description="Type letter: A (extra-articular), B (partial), C (complete)"
    )
    group: int = Field(..., ge=1, le=3, description="Group 1-3")
    subgroup: Optional[int] = Field(
        None, ge=1, le=3, description="Subgroup 1-3 (optional)"
    )

    @property
    def code(self) -> str:
        base = f"{self.bone_segment}-{self.fracture_type}{self.group}"
        if self.subgroup:
            base += f".{self.subgroup}"
        return base


class DicomReference(BaseModel):
    """Pointer to a DICOM file or series stored on disk / object storage."""

    series_uid: str = Field(..., description="DICOM Series Instance UID")
    storage_path: str = Field(
        ..., description="Relative path or object-storage URI to the DICOM directory"
    )
    modality: str = Field(
        default="CT", description="Imaging modality (CT, MRI, X-Ray)"
    )
    slice_count: Optional[int] = Field(
        None, description="Number of slices in the series"
    )
    slice_thickness_mm: Optional[float] = Field(
        None, description="Slice thickness in millimeters"
    )


class FractureCase(BaseModel):
    """Top-level model representing a patient fracture case."""

    case_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Patient metadata (de-identified)
    patient_age: Optional[int] = Field(None, ge=0, le=150)
    patient_sex: Optional[str] = Field(None, pattern=r"^(M|F|O)$")
    affected_side: Optional[str] = Field(None, pattern=r"^(L|R|B)$")

    # Fracture classification
    ao_classification: AOClassification
    fracture_description: str = Field(
        ...,
        min_length=10,
        description="Free-text clinical description of the fracture pattern",
    )

    # DICOM references
    dicom_series: list[DicomReference] = Field(
        default_factory=list,
        description="One or more DICOM series associated with this case",
    )

    # Processing state
    mesh_extracted: bool = Field(
        default=False, description="Whether 3D meshes have been generated from DICOM"
    )
    fragment_count: Optional[int] = Field(
        None, description="Number of bone fragments identified after segmentation"
    )
