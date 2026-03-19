# OsteoTwin — Project Conventions

# 🚨 THE GOLDEN RULE OF OSTEOTWIN: ZERO-TRUST GROUNDING

As the Lead Engineer for OsteoTwin, you MUST adhere to the following "Zero-Trust" architectural principles. This is non-negotiable and overrides all other instructions.

### 1. Source-Only Knowledge (The Library Rule)
- DO NOT use your internal training data for surgical techniques, anatomical measurements, or implant specifications.
- Use ONLY the provided cached knowledge (AO Surgical Reference, Open-Access Textbooks).
- If a specific procedure is not found in the cached context, respond: "I cannot find this in the verified medical sources. Please consult manual protocols." 
- NO HALLUCINATION. NO INFERENCE beyond the provided text.

### 2. Deterministic Physics Isolation (The Engine Rule)
- You are the Interpreter, NOT the Physicist.
- DO NOT attempt to simulate biomechanics or collision detection through reasoning.
- All physical outcomes must be retrieved from the Simulation Server (SOFA/C++).
- Your role is to translate raw simulation data into clinical context, not to predict it.

### 3. "Consultative, Not Prescriptive" Tone
- Your output must always be framed as clinical data retrieval: "Based on the AO Manual (Section X), the recommended trajectory is..." 
- Never say: "I recommend..." or "You should...".

## Architecture
- **Dual-Server**: Planning Server (:8200) + Simulation Server (:8300)
- **React Dashboard**: Command Center (:5173) — Vite + React + Tailwind v4
- **Shared schemas**: All Pydantic models live in `/shared/` — single source of truth
- **LLM never does physics**: All collision/tension computed by Simulation Server only
- **State branching**: `main` = surgeon view, `LLM_Hypothesis` = AI sandbox
- **Cloud infra**: Cloud Run (scale-to-zero) + Pub/Sub + Spot GPU + GCS + Firestore

## Running

### Option 1: Cloud Run (production)
```bash
# First-time: provision GCP resources
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars  # fill in billing_account
terraform init && terraform apply

# Deploy all services (builds Docker → pushes to Artifact Registry → deploys Cloud Run)
bash system/deploy.sh

# Deploy single service
bash system/deploy.sh planning
bash system/deploy.sh simulation
bash system/deploy.sh dashboard

# CI/CD via Cloud Build (triggered on push to main)
bash system/deploy.sh --cloud-build
```

### Option 2: Windows Services (auto-start on boot)
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
- LLM models: `claude-sonnet-4-20250514` (Claude), `gemini-3-flash-preview` (Gemini, fallback: gemini-3.1-pro-preview -> gemini-2.5-pro -> gemini-2.5-flash)
- K-wires excluded from 3D print exports (use real metal for practice)

## Secrets
- Never hardcode API keys — always read from environment via `config.py`
- `.env` at project root, loaded by `python-dotenv`
- GCP Secret Manager for production (see `system/fetch_secrets.sh`)
- Admin password is random, stored in Secret Manager (`admin-password`)

## Cross-Project Notes (from ROBOT4KID, 2026-03-19)

### Gemini 3.x API — Critical Findings
- **Model IDs**: `gemini-3.1-pro-preview`, `gemini-3-pro-preview`, `gemini-3-flash-preview`
- **Deep Think**: NOT a separate model — it's `thinking_level="HIGH"` parameter on any 3.x model
  ```python
  config = genai.types.GenerateContentConfig(
      thinking_config=genai.types.ThinkingConfig(thinking_level="HIGH"),
  )
  ```
- **Vertex AI location**: Use `"global"` (3.x models 404 on `us-central1`)
- **Python version**: Use 3.13 (NOT 3.14) — `google-cloud-storage` SDK breaks on 3.14
- **AI Studio vs Vertex AI**: 3.x Pro models have `limit: 0` on free tier batch quota. Use Vertex AI (GCP billing) for production.

### TODO: Migrate Audit/Debate to Batch Prediction
See memory file `project_batch_audit_todo.md` for full implementation checklist.
- **Why**: Real-time `generate_content()` truncates long outputs. Batch writes full JSONL to GCS.
- **Architecture**: prompt → JSONL → GCS → `client.batches.create()` → poll → download results
- **Reference impl**: `ROBOT4KID/planning_server/app/pipeline/batch_audit.py`
- **GCS prefix**: `osteotwin_audit/jobs/` in shared bucket
- **Cost**: 50% discount vs realtime, 65536 max_output_tokens

### Cloud Architecture (Cloud Run)
All services deployed to Cloud Run (scale-to-zero) in `asia-northeast1`:
- **Planning Server** → `osteotwin-planning` (public, JWT auth, 1Gi/2CPU)
- **Simulation Server** → `osteotwin-simulation` (internal only, API key auth, 2Gi/4CPU)
- **Dashboard** → `osteotwin-dashboard` (public, nginx reverse proxy to backends)
- **GPU Workers** → Spot VM MIG (Pub/Sub pull, dormant at size=0)
- **Container Registry** → Artifact Registry (`asia-northeast1-docker.pkg.dev`)
- **CI/CD** → Cloud Build (`cloudbuild.yaml`, auto-wires inter-service URLs)
- **Secrets** → GCP Secret Manager (injected into Cloud Run at deploy)

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
- `POST /api/v1/audit/full` — run complete Grand Surgical Audit (Phase 1 + Phase 2)
- `POST /api/v1/audit/condense` — Phase 1: Flash condenses discussion into audit package
- `POST /api/v1/audit/run` — Phase 2: Pro audits package (Zero-Suggestion Policy)
- `POST /api/v1/audit/resolve` — Phase 3: surgeon submits resolutions, triggers re-audit
- `GET /api/v1/audit/status/{case_id}` — audit session status
- `GET /api/v1/clinical-logs/status` — Firestore logger availability
- `POST /api/v1/clinical-logs` — create clinical case log entry
- `GET /api/v1/clinical-logs/case/{case_id}` — retrieve logs for a case
- `GET /api/v1/clinical-logs/surgeon/{surgeon_id}` — retrieve logs for a surgeon
- `PATCH /api/v1/clinical-logs/{log_id}/post-op` — update with post-operative feedback
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
- `GET /api/v1/soft-tissue/status` — SOFA engine status + THUMS data availability
- `POST /api/v1/soft-tissue/simulate` — soft-tissue biomechanical simulation
- `POST /api/v1/carm/render` — render simulated C-arm fluoroscopy (DRR) as PNG
- `POST /api/v1/carm/multiview` — render standard C-arm views (AP, lateral, obliques)
- `POST /api/v1/carm/feasibility` — check if C-arm pose is physically achievable (arc vs bed vs patient collision)
- `POST /api/v1/carm/feasibility-map` — full map of achievable angles (heatmap)
- `POST /api/v1/carm/scene-6view` — render 3D OR scene (bed + patient + C-arm) from 6 angles
- `POST /api/v1/carm/validate-with-gemini` — full pipeline: feasibility + 6-view + Gemini confirmation
- `GET /api/v1/approaches` — list surgical approaches (filterable by region)
- `GET /api/v1/approaches/{key}` — approach detail with danger zones and layers
- `GET /api/v1/approaches/{key}/danger-zones.stl` — danger zone spheres as STL overlay
- `GET /api/v1/soft-tissue/thums/{subject}` — query THUMS material database
- `GET /api/v1/thums/subjects` — list available THUMS subjects
- `GET /api/v1/thums/{subject}/parts` — list parts (filterable by region/mat_type)
- `GET /api/v1/thums/{subject}/mesh/{part_id}.stl` — serve mesh as STL (VTK-to-STL on-the-fly)
- `POST /api/v1/thums/{subject}/load-scene` — batch-load parts into collision engine

## Testing
```bash
# Full test suite (132 tests: unit + physics E2E + scenarios)
pytest tests/ -v

# Physics-only (trimesh collision, soft-tissue tension, STL export ~29s)
pytest tests/test_e2e_physics.py -v

# Live server E2E (requires both servers running on :8200/:8300)
pytest tests/test_e2e_pipeline.py -v
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
| Firestore | `(default)` | User auth + clinical case logging (Native Mode) |
| Artifact Registry | `osteotwin` | Docker container images |
| Cloud Run | `osteotwin-planning` | Planning Server (scale-to-zero) |
| Cloud Run | `osteotwin-simulation` | Simulation Server (internal) |
| Cloud Run | `osteotwin-dashboard` | React Dashboard (nginx) |
| Service Account | `osteotwin-cloudrun` | Cloud Run → Secrets/GCS/Pub/Sub/Firestore |

## Phase Status
- [x] Phase 0: Project scaffolding, schemas, server skeletons
- [x] Phase 1: Rigid body collision, auth (JWT), LLM orchestrator, multi-agent debate, DICOM pipeline, Neo4j scaffold, HTMX web UI, Windows services
- [x] Phase 2: TotalSegmentator, implant CAD library (20+), smart sizing, DICOM→mesh tested (2 fragments, 35K verts)
- [x] Cloud infra: Pub/Sub, checkpoint bucket, dormant Spot VM (size=0), worker.py with checkpoint/failover
- [x] Cloud Run migration: Dockerfiles, Artifact Registry, Cloud Build CI/CD, deploy.sh, IAM (SA → Secrets/GCS/Pub/Sub/Firestore)
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
- [x] Phase 9: Autonomous Catalog-to-CAD Pipeline — ManufacturerAlias (3-letter codes), ParametricImplantSpec, 6-strike QA loop (Gemini validates, Claude corrects), OpenSCAD generation, 6-way rendering, auto-export on approval
- [x] Firestore Clinical Logging — SurgicalCaseLog schema (quantitative + qualitative), FirestoreFeedbackLogger (async, fire-and-forget), auto delta computation, post-op feedback, Terraform provisioning
- [x] SQLite → Firestore migration — User/Case/Debate models moved to Firestore (free tier: 50K reads, 20K writes/day), SQLAlchemy/aiosqlite removed, in-memory fallback for local dev
- [x] THUMS v7.1 Integration — LS-DYNA .k parser (2381 parts, 1975 materials, 840K nodes, 2.1M elements), thums_anatomical_map.json, VTK mesh export, SOFA material_configs.json, mass validation, 4 subjects (AF05/AF50/AM50/AM95), GCS backup, THUMSMaterialDB loader wired into soft-tissue engine
- [x] Phase 9 CAD Pipeline fully wired — Gemini extraction, Claude SCAD generation, OpenSCAD 6-way render + Pillow stitch, Gemini QA validation (XML parsing), Claude auto-correction, OpenSCAD STL/3MF export
- [x] C-arm Simulation — DRR engine, physical C-arm model (arc radius, throat depth, bed, patient, rails), collision detection (arc vs bed/patient/rails), feasibility map, OR scene 6-view rendering, Gemini validation pipeline
- [x] Surgical Approach Atlas — 5 named approaches (Henry, Thompson, Kocher-Langenbeck, Deltopectoral, Lateral Knee) with danger zones, layers, source citations, STL danger zone overlay
- [x] THUMS mesh decimation — LOD1 (50%), LOD2 (25%) via quadric decimation, meshio VTK reader
- [x] Advanced Reduction & Fixation — SurgicalPlan_v3 schema, clamp library (6 types), reduction priority tree, interference engine (K-wire vs clamp/plate/nerves), stability evaluator (delta-stability on clamp removal), Gemini multi-modal validation queries
- [x] Gemini rate limit fallback — model chain (gemini-3-flash-preview -> gemini-3.1-pro-preview -> gemini-2.5-pro -> gemini-2.5-flash), 60s wait + retry on full exhaustion
- [x] Grand Surgical Audit — two-stage Flash->Pro pipeline: Phase 1 (Flash condenses 100K+ tokens into audit package), Phase 2 (gemini-3.1-pro-preview Devil's Advocate audit with Zero-Suggestion Policy), Phase 3 (surgeon resolution loop), React Audit Report UI
