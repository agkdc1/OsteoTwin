"""End-to-end integration test: DICOM → mesh → collision → debate → STL export.

Tests the complete OsteoTwin pipeline against the running services.
Requires both servers running on :8200 and :8300.

Usage:
    python -m pytest tests/test_e2e_pipeline.py -v
    # or directly:
    python tests/test_e2e_pipeline.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

# Load .env
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PLAN_URL = "http://localhost:8200"
SIM_URL = "http://localhost:8300"

# Read API keys from .env
_env = {}
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            _env[k.strip()] = v.strip()

SIM_KEY = _env.get("SIM_API_KEY", "")
ADMIN_PASS = _env.get("ADMIN_PASSWORD", "")

SIM_HEADERS = {"X-API-Key": SIM_KEY}
DICOM_DIR = str(Path(__file__).resolve().parent.parent / "sample_data" / "ct_wrist")
CASE_ID = "e2e_test_001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_auth_token() -> str:
    """Login as admin and return access token."""
    resp = httpx.post(
        f"{PLAN_URL}/auth/login",
        json={"username": "admin", "password": ADMIN_PASS},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests (ordered by pipeline stage)
# ---------------------------------------------------------------------------


class TestE2EPipeline:
    """Full pipeline integration test."""

    @pytest.fixture(autouse=True, scope="class")
    def setup(self):
        """Verify both servers are running."""
        try:
            r1 = httpx.get(f"{PLAN_URL}/health", timeout=5)
            r2 = httpx.get(f"{SIM_URL}/health", timeout=5)
            assert r1.status_code == 200
            assert r2.status_code == 200
        except httpx.ConnectError:
            pytest.skip("Servers not running on :8200/:8300")

    # Stage 1: Auth
    def test_01_admin_login(self):
        token = get_auth_token()
        assert token
        assert len(token) > 50

    # Stage 2: DICOM Ingestion
    def test_02_dicom_ingest(self):
        resp = httpx.post(
            f"{SIM_URL}/api/v1/dicom/ingest",
            json={
                "case_id": CASE_ID,
                "dicom_dir": DICOM_DIR,
                "hu_threshold": 300,
                "decimate_ratio": 0.5,
            },
            headers=SIM_HEADERS,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["case_id"] == CASE_ID
        assert data["fragment_count"] >= 1
        assert len(data["mesh_files"]) >= 2
        print(f"  Fragments: {data['fragment_count']}, Vertices: {data['total_vertices']}")

    # Stage 3: Load fragments into collision engine
    def test_03_load_fragments(self):
        # Load fragment_00
        resp = httpx.post(
            f"{SIM_URL}/api/v1/meshes",
            params={
                "mesh_id": "frag_00",
                "file_path": f"C:/Users/ahnch/Documents/OsteoTwin/simulation_server/mesh_cache/{CASE_ID}/fragment_00.stl",
                "label": "radius_distal",
                "mesh_type": "bone",
                "branch": "main",
            },
            headers=SIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        assert resp.json()["loaded"]

        # Load fragment_01
        resp = httpx.post(
            f"{SIM_URL}/api/v1/meshes",
            params={
                "mesh_id": "frag_01",
                "file_path": f"C:/Users/ahnch/Documents/OsteoTwin/simulation_server/mesh_cache/{CASE_ID}/fragment_01.stl",
                "label": "ulna",
                "mesh_type": "bone",
                "branch": "main",
            },
            headers=SIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        assert resp.json()["loaded"]

    # Stage 4: Generate and place implant
    def test_04_generate_implant(self):
        resp = httpx.post(
            f"{SIM_URL}/api/v1/implants/generate",
            params={"implant_id": "lcp_3.5_6hole", "branch": "main"},
            headers=SIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["generated"]
        print(f"  Generated: {data['name']}, {data['vertex_count']} verts")

    # Stage 5: K-wire collision check
    def test_05_kwire_collision(self):
        resp = httpx.post(
            f"{SIM_URL}/api/v1/simulate/collision",
            json={
                "case_id": CASE_ID,
                "branch": "main",
                "ray_origin": {"x": -50, "y": 0, "z": 0},
                "ray_direction": {"x": 1, "y": 0, "z": 0},
                "label": "k_wire_test",
            },
            headers=SIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["success"]
        print(f"  Hits: {data['total_hits']}, Summary: {data['engine_summary']}")

    # Stage 6: Implant suggestion
    def test_06_implant_suggestion(self):
        resp = httpx.get(
            f"{SIM_URL}/api/v1/implants/suggest",
            params={
                "bone_region": "distal_radius",
                "fragment_count": 2,
                "max_bone_width_mm": 18,
            },
            headers=SIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        assert len(data["suggestions"]) >= 2
        print(f"  Suggested: {[s['name'] for s in data['suggestions']]}")

    # Stage 7: STL export
    def test_07_stl_export(self):
        resp = httpx.post(
            f"{SIM_URL}/api/v1/export/stl",
            json={
                "case_id": CASE_ID,
                "fragment_stl_paths": [
                    f"C:/Users/ahnch/Documents/OsteoTwin/simulation_server/mesh_cache/{CASE_ID}/fragment_00.stl",
                    f"C:/Users/ahnch/Documents/OsteoTwin/simulation_server/mesh_cache/{CASE_ID}/fragment_01.stl",
                ],
                "fragment_labels": ["radius_distal", "ulna"],
                "hardware_ids": ["lcp_3.5_6hole", "k_wire_1.6mm"],
                "scale_factor": 1.0,
            },
            headers=SIM_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["component_count"] >= 3  # 2 fragments + plate (K-wires excluded)
        assert len(data["files"]) >= 4  # 3+ components + 1 merged
        print(f"  Exported: {data['component_count']} components, "
              f"{data['total_volume_cm3']} cm³, "
              f"est. ${data['print_estimate']['cost_usd']}")

    # Stage 8: List exported files
    def test_08_list_exports(self):
        resp = httpx.get(
            f"{SIM_URL}/api/v1/export/stl/{CASE_ID}",
            headers=SIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        assert len(data["files"]) >= 5
        total_kb = sum(f["size_kb"] for f in data["files"])
        print(f"  Files: {len(data['files'])}, Total: {total_kb:.0f} KB")


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("OsteoTwin End-to-End Pipeline Test")
    print("=" * 60)

    # Check servers
    try:
        r1 = httpx.get(f"{PLAN_URL}/health", timeout=5)
        r2 = httpx.get(f"{SIM_URL}/health", timeout=5)
        assert r1.status_code == 200 and r2.status_code == 200
    except Exception:
        print("ERROR: Servers not running on :8200/:8300")
        sys.exit(1)

    test = TestE2EPipeline()

    stages = [
        ("1. Admin Login", test.test_01_admin_login),
        ("2. DICOM Ingest", test.test_02_dicom_ingest),
        ("3. Load Fragments", test.test_03_load_fragments),
        ("4. Generate Implant", test.test_04_generate_implant),
        ("5. K-wire Collision", test.test_05_kwire_collision),
        ("6. Implant Suggestion", test.test_06_implant_suggestion),
        ("7. STL Export", test.test_07_stl_export),
        ("8. List Exports", test.test_08_list_exports),
    ]

    passed = 0
    for name, func in stages:
        try:
            print(f"\n[{name}]")
            func()
            print(f"  PASSED")
            passed += 1
        except Exception as exc:
            print(f"  FAILED: {exc}")

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{len(stages)} passed")
    print("=" * 60)
