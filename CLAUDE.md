# OsteoTwin — Project Conventions

## Architecture
- **Dual-Server**: Planning Server (:8200) + Simulation Server (:8300)
- **React Dashboard**: Command Center (:5173) — Vite + React + Tailwind v4
- **Shared schemas**: All Pydantic models live in `/shared/` — single source of truth
- **LLM never does physics**: All collision/tension computed by Simulation Server only
- **State branching**: `main` = surgeon view, `LLM_Hypothesis` = AI sandbox
- **Cloud infra**: GCP Pub/Sub queue + Spot GPU workers (dormant at size=0)

## Running

### Option 1: Windows Services (auto-start on boot)
```powershell
# Run as Administrator
.\system\services.ps1 install   # one-time setup
.\system\services.ps1 start     # start both servers
.\system\services.ps1 status    # check status
.\system\services.ps1 logs      # view log files
.\system\services.ps1 restart   # restart after code changes

# Daily backup (scheduled task)
.\system\daily_backup.ps1 install   # daily 2 AM backup to GCS
.\system\daily_backup.ps1 status    # check last run
.\system\daily_backup.ps1 run       # manual trigger
```

### Option 2: Manual (development)
```bash
# From project root with venv activated:
python -m planning_server.app.main    # Port 8200
python -m simulation_server.app.main  # Port 8300

# React dashboard:
cd dashboard && npm run dev           # Port 5173
```

### Port Map (co-exists with ROBOT4KID on same machine)
| Service | Port | Project |
|---------|------|---------|
| ROBOT4KID Planning | 8000 | NL2Bot |
| ROBOT4KID Simulation | 8100 | NL2Bot |
| OsteoTwin Planning | 8200 | OsteoTwin |
| OsteoTwin Simulation | 8300 | OsteoTwin |
| OsteoTwin Dashboard | 5173 | OsteoTwin |

## Setup

### First-time setup
```bash
# 1. Create venv and install deps
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r planning_server/requirements.txt
pip install -r simulation_server/requirements.txt

# 2. GCP project + secrets (copies API keys from ROBOT4KID)
bash system/setup_gcp.sh
# or manually: cp .env.example .env && fill in values

# 3. Dashboard
cd dashboard && npm install && cd ..

# 4. Install as Windows services (optional)
# Run as Admin: .\system\services.ps1 install
```

### Backup & Restore
```bash
# Backup (DB, cases, mesh cache → GCS)
bash system/backup.sh [tag]
# Daily automated: runs at 2 AM via Windows Task Scheduler
# Storage tiering: 14 days hot (Standard), then Coldline (never deleted)

# Restore
bash system/restore.sh --list       # list available backups
bash system/restore.sh <tag>        # restore a backup

# DICOM files (stored in encrypted GCS bucket, cached locally)
bash system/dicom_cache.sh push <case_id> <dicom_dir>  # upload
bash system/dicom_cache.sh pull <case_id>               # download
bash system/dicom_cache.sh evict [case_id]              # free local disk
bash system/dicom_cache.sh status                       # show cache usage

# Secrets from GCP Secret Manager
bash system/fetch_secrets.sh [project_id]
```

## Spatial-Semantic Interoperability Standard

All inter-agent communication (Claude ↔ Gemini ↔ Simulation Server ↔ Dashboard) uses a common schema defined in `/shared/schemas.py` with math utilities in `/shared/kinematics.py`.

### LPS Coordinate System (DICOM Standard)
| Axis | Positive (+) | Negative (-) |
|------|-------------|--------------|
| X | Left | Right |
| Y | Posterior | Anterior |
| Z | Superior (proximal) | Inferior (distal) |

### Key Models
- **`FragmentIdentity`** — identifies a bone fragment by ID, color, and volume
- **`SemanticMovement`** — a clinical movement (e.g., "distal 2mm", "valgus 3°") with side (L/R)
- **`SurgicalAction`** — the universal message for any surgical move (clinical terms + resolved LPS math)
- **`ValidationFeedback`** / **`CorrectionSuggestion`** — Gemini's structured validation response

### Pipeline Flow
1. Surgeon (voice/text) → Claude parses intent → `SurgicalAction` with `movements[]`
2. `kinematics.resolve_movements()` auto-converts clinical terms to LPS vectors (side-aware sign flip)
3. `kinematics.surgical_action_to_sim_request()` bridges `SurgicalAction` → `SimActionRequest`
4. Orchestrator dispatches to Simulation Server; deterministic results returned
5. For visual validation: Claude passes `SurgicalAction` JSON to Gemini with rendered image
6. Gemini returns `CorrectionSuggestion` using exact `fragment_id` + LPS vectors

### Side-Aware Sign Convention
Left/right sign flips are handled automatically in `/shared/kinematics.py`:
- Right side: medial = +X, lateral = -X
- Left side: medial = -X, lateral = +X (mirrored)
- Same mirroring applies to varus/valgus and internal/external rotation

## Code Style
- Python 3.11+, Pydantic v2, async/await throughout
- `from __future__ import annotations` in every module
- Type hints on all public functions
- Schemas use `Field(...)` with descriptions
- LLM models: `claude-sonnet-4-20250514` (Claude), `gemini-2.5-flash` (Gemini)
- K-wires excluded from 3D print exports (use real metal for practice)

## Secrets
- Never hardcode API keys — always read from environment via `config.py`
- `.env` at project root, loaded by `python-dotenv`
- GCP Secret Manager for production (see `system/fetch_secrets.sh`)
- Admin password is random, stored in Secret Manager (`admin-password`)

## Key Endpoints

### Planning Server (:8200)
- `GET /health` — health check
- `POST /auth/login` — JWT auth
- `POST /auth/register` — user registration (pending admin approval)
- `GET /admin/users/pending` — list pending users
- `POST /admin/users/{id}/approve` — approve user
- `POST /api/v1/pipeline/query` — surgical query (Claude + simulation tools)
- `POST /api/v1/pipeline/debate` — multi-agent debate (Claude vs Gemini)
- `POST /api/v1/pipeline/simulate/async` — async simulation via Pub/Sub (HTTP 202)
- `POST /api/v1/knowledge/corrections` — store surgeon correction in Neo4j
- `GET /api/v1/knowledge/rules` — retrieve anatomical rules
- `GET /api/v1/knowledge/status` — Neo4j connection status
- `POST /api/v1/voice/query` — intraoperative voice query (text-in/text-out)
- `POST /api/v1/voice/reset` — reset voice session
- `GET /api/v1/voice/sessions` — list active voice sessions
- `GET /api/v1/knowledge-cache/status` — cache stats and source availability
- `POST /api/v1/knowledge-cache/download` — download reference texts (background)
- `POST /api/v1/knowledge-cache/backup` — backup cache to GCS
- `POST /api/v1/knowledge-cache/restore` — restore cache from GCS
- `POST /api/v1/knowledge-cache/assemble` — preview assembled cache block
- `GET /api/v1/admin/printer` — list printer profiles
- `POST /api/v1/admin/printer` — create/update printer profile
- `DELETE /api/v1/admin/printer/{id}` — delete printer profile
- `POST /api/v1/simulation/sync-ui-action` — receive manual 3D viewer drag → SurgicalAction
- `GET /stl-proxy/{path}` — serve STL files for Three.js viewer
- `GET /`, `/viewer`, `/debate` — HTMX web UI pages

### Simulation Server (:8300)
- `GET /health` — health check
- `POST /api/v1/simulate/action` — fragment movement (deterministic)
- `POST /api/v1/simulate/collision` — K-wire trajectory check (ray casting)
- `POST /api/v1/simulate/intersection` — mesh-mesh collision check
- `POST /api/v1/meshes` — load mesh into collision engine
- `GET /api/v1/meshes` — list loaded meshes
- `POST /api/v1/branches/promote` — promote LLM_Hypothesis to main
- `GET /api/v1/branches` — list branches
- `POST /api/v1/dicom/ingest` — DICOM → mesh extraction pipeline
- `POST /api/v1/segment/auto` — TotalSegmentator automated segmentation
- `GET /api/v1/implants/catalog` — list implant library
- `POST /api/v1/implants/generate` — generate implant mesh
- `GET /api/v1/implants/suggest` — smart implant sizing
- `POST /api/v1/export/stl` — 3D print STL export
- `GET /api/v1/export/stl/{case_id}` — list/download exported STLs
- `GET /api/v1/soft-tissue/status` — SOFA engine status
- `POST /api/v1/soft-tissue/simulate` — soft-tissue biomechanical simulation

## Testing
```bash
# E2E pipeline test (requires both servers running)
python tests/test_e2e_pipeline.py

# With pytest
pytest tests/ -v
```

## GCP Resources (project: osteotwin-37f03c)
| Resource | Name | Purpose |
|----------|------|---------|
| Data bucket | `osteotwin-37f03c-data` | Backups, worker code |
| DICOM bucket | `osteotwin-37f03c-dicom` | Encrypted DICOM storage |
| Checkpoint bucket | `osteotwin-37f03c-checkpoints` | Simulation checkpoints |
| Pub/Sub topic | `simulation-tasks-topic` | Async task queue |
| Pub/Sub sub | `simulation-worker-sub` | Worker pull subscription |
| Spot MIG | `osteotwin-sim-workers` | GPU workers (size=0) |

## Phase Status
- [x] Phase 0: Project scaffolding, schemas, server skeletons
- [x] Phase 1: Rigid body collision, auth (JWT), LLM orchestrator, multi-agent debate, DICOM pipeline, Neo4j scaffold, HTMX web UI, Windows services
- [x] Phase 2: TotalSegmentator, implant CAD library (20+), smart sizing, DICOM→mesh tested (2 fragments, 35K verts)
- [x] Cloud infra: Pub/Sub, checkpoint bucket, dormant Spot VM (size=0), worker.py with checkpoint/failover
- [x] Phase 3: STL export for 3D printing (color-coded fragments + plates, K-wires excluded)
- [x] Phase 4: E2E integration test (8/8 passed), live Claude tool-use verified
- [x] React Command Center dashboard (Vite + React + Tailwind v4 + Lucide)
- [x] Phase 5: SOFA soft-tissue scaffolding (spring-mass fallback active, full SOFA pending GPU quota, retry after 2026-03-17)
- [x] Phase 6: Intraoperative Voice Assistant (consultative mode, text-in/text-out, session persistence)
- [x] Knowledge Cache: 1.88M tokens (AO Surgery Reference 25 regions + CMF, OpenStax, StatPearls, WFNS), 2-track pipeline (Gemini Librarian → Claude Surgeon), heartbeat, GCS backup
- [x] STT/TTS voice pipeline (Whisper local/API + Edge TTS/Google TTS/OpenAI TTS)
- [x] React Dashboard: 3D Viewer (Three.js/R3F), Voice Console, live API wiring
- [x] Neo4j Docker Compose ready (docker-compose.neo4j.yml)
- [x] Daily backup scheduled task (2 AM → GCS)
- [x] Spatial-Semantic Schema: LPS coordinate standard, FragmentIdentity, SurgicalAction, kinematics bridge, orchestrator enforcement
- [x] Phase 7: Physical Print Export — PrinterConfig/FilamentMapping schemas, printer admin API + React UI, 3MF export engine (multi-material with extruder metadata), named-STL ZIP fallback
- [x] Phase 8: Bi-directional 3D UI Sync — coordinateMapper.ts (Three.js Y-up ↔ LPS Z-up), TransformControls on fragments, drag→SurgicalAction dispatch, sync-ui-action endpoint, Claude context injection
