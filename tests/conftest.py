"""Shared pytest fixtures for OsteoTwin test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def thums_output_dir(project_root: Path) -> Path:
    d = project_root / "fea" / "thums_output" / "AM50"
    if not d.exists():
        pytest.skip("THUMS parsed output not available (run thums_parser.py AM50 first)")
    return d
