"""Printer configuration admin endpoints.

Manages 3D printer profiles and color-to-extruder filament mappings
used by the export engine to produce multi-material 3MF / named STL output.

Storage: JSON file on disk (printer_configs.json) — lightweight, no DB needed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import sys, pathlib

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)
)
from shared.schemas import PrinterConfig, FilamentMapping, MaterialType

logger = logging.getLogger("osteotwin.printer")

router = APIRouter(prefix="/api/v1/admin/printer", tags=["printer-admin"])

# ---------------------------------------------------------------------------
# Storage — JSON file (simple, no DB dependency)
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PRINTER_FILE = DATA_DIR / "printer_configs.json"


def _load_configs() -> list[PrinterConfig]:
    if not PRINTER_FILE.exists():
        return []
    try:
        raw = json.loads(PRINTER_FILE.read_text(encoding="utf-8"))
        return [PrinterConfig.model_validate(c) for c in raw]
    except Exception:
        logger.warning("Failed to load printer configs, returning empty")
        return []


def _save_configs(configs: list[PrinterConfig]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PRINTER_FILE.write_text(
        json.dumps([c.model_dump(mode="json") for c in configs], indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PrinterConfig])
async def list_printers():
    """List all configured printer profiles."""
    return _load_configs()


@router.get("/{printer_id}", response_model=PrinterConfig)
async def get_printer(printer_id: str):
    """Get a single printer profile by ID."""
    for c in _load_configs():
        if c.printer_id == printer_id:
            return c
    raise HTTPException(status_code=404, detail=f"Printer '{printer_id}' not found")


@router.post("", response_model=PrinterConfig, status_code=201)
async def create_printer(config: PrinterConfig):
    """Create or update a printer profile.

    If a profile with the same printer_id exists, it is replaced.
    """
    configs = _load_configs()

    # Replace existing or append
    configs = [c for c in configs if c.printer_id != config.printer_id]

    # If this is marked default, clear default on others
    if config.is_default:
        for c in configs:
            c.is_default = False

    configs.append(config)
    _save_configs(configs)
    logger.info("Saved printer config: %s (%d extruders)", config.printer_name, config.num_extruders)
    return config


@router.delete("/{printer_id}")
async def delete_printer(printer_id: str):
    """Delete a printer profile."""
    configs = _load_configs()
    before = len(configs)
    configs = [c for c in configs if c.printer_id != printer_id]
    if len(configs) == before:
        raise HTTPException(status_code=404, detail=f"Printer '{printer_id}' not found")
    _save_configs(configs)
    return {"deleted": True, "printer_id": printer_id}


@router.get("/default", response_model=Optional[PrinterConfig])
async def get_default_printer():
    """Get the default printer profile (if any)."""
    for c in _load_configs():
        if c.is_default:
            return c
    return None


class MaterialsResponse(BaseModel):
    materials: list[str]

@router.get("/materials/list", response_model=MaterialsResponse)
async def list_materials():
    """List all available material types."""
    return MaterialsResponse(materials=[m.value for m in MaterialType])
