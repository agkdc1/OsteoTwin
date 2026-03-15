AI-Driven Orthopedic Reduction & Surgical Planning Simulator

"What if I could completely clear the fog in my mind before stepping into the operating room?"

OsteoTwin is an open-source pre-operative planning and simulation framework born from the cognitive overload and inherent uncertainties faced by surgeons during complex fracture reductions. By bridging biomechanical 3D simulation with a Multi-Agent LLM architecture, OsteoTwin analyzes patient-specific anatomy to formulate, debate, and refine the optimal surgical reduction scenario.

## Why We Built This

Even with 3D-reconstructed CT scans, the actual reduction of a complex fracture often relies heavily on the surgeon's "spatial imagination." Unless you are a highly seasoned veteran, plans can easily fall apart in the OR due to several critical variables:

**Dynamic Soft Tissue Tension:** Traditional navigation systems fail to account for the pulling forces of muscles and tendons that shift when bone fragments are moved.

**Unforeseen Hardware Collisions:** A K-wire perfectly placed for temporary fixation might end up blocking the trajectory of the final locking plate.

**The Isolation of the OR:** It is rare to have a "perfect sparring partner" to fiercely debate variables and validate surgical plans the night before the operation.

OsteoTwin simulates these exact variables beforehand. Even if the actual surgery deviates from the plan, a surgeon who has pre-simulated all potential pitfalls enters the OR with a clear, confident mind.

## Core Pipeline

From ingesting DICOM data to outputting a comprehensive surgical plan, OsteoTwin operates through the following pipeline:

### 1. Radiological Description & Classification
The LLM analyzes the fracture geometry based on the provided data, generating a detailed anatomical description. Through a feedback loop with the surgeon, it refines the context by applying international standard classifications (AO Foundation, Rockwood, Weber, etc.).

### 2. Virtual OR Setup & C-arm Simulation
Configures the patient's positioning and the C-arm insertion angles. Simulates and predicts the exact fluoroscopic images that will be seen on the C-arm monitor at those specific angles within the 3D viewer.

### 3. Anatomical Approach Mapping
When a specific surgical approach (e.g., the Henry approach) is selected, the system maps the trajectory, highlighting visible structures and critical "danger zones" (nerves, vessels) directly on the 3D mesh.

### 4. Biomechanical Reduction Simulation
- Calculates the expected tension vectors of attached muscles and tendons when a bone fragment is manipulated.
- Allows the virtual placement of K-wires and reduction forceps to detect physical collisions between implants.
- The LLM intervenes with real-time insights: "Elevating this fragment will be hindered by the tension of the supraspinatus. A targeted release is recommended."

### 5. Multi-Agent Debate (The Surgical Council)
Two or more AI agents (Claude and Gemini) engage in a structured debate based on the simulation data. Through cross-validation, the "Council" outputs Plan A, alternative Plans B and C, and a final operative document detailing anticipated difficulties and precautions for each step.

### 6. Physical Twin (3D Printing Integration)
Exports an STL file where bone fragments and key soft-tissue footprints are color-coded. Enables surgeons to 3D print the model and perform tactile practice with actual K-wires and screws the night before surgery. K-wires are excluded from STL exports — use real metal for practice.

### 7. Intraoperative Voice Assistant
A hands-free consultative voice agent that operates in the OR. The surgeon asks questions ("Osteo, check the K-wire trajectory") and receives concise, spoken clinical feedback based on the pre-operative plan and real-time simulation results. The agent NEVER gives commands — it only provides information when asked.

## Architecture

```
                         React Command Center (:5173)
                                  |
              +-------------------+-------------------+
              |                                       |
  +-----------v-----------+          +----------------v-----------+
  |  Planning Server :8200|          |  Simulation Server :8300   |
  |  ---------------------|          |  ------------------------- |
  |  Auth (JWT)           |          |  DICOM -> Mesh (VTK)       |
  |  LLM Orchestrator     |   JSON   |  Collision (Trimesh)       |
  |   +- Claude (Primary) |<-------->|  Soft-Tissue (SOFA/Spring) |
  |   +- Gemini (2nd)     |          |  Branch State Manager      |
  |  Multi-Agent Debate   |          |  Implant Library (20+)     |
  |  Voice Assistant      |          |  STL Export (3D Print)     |
  |  Knowledge Graph      |          |  TotalSegmentator          |
  +-----------+-----------+          +----------------------------+
              |
  +-----------v-----------+
  |  Neo4j Graph DB       |
  |  (Anatomical Rules,   |
  |   Surgeon Corrections)|
  +------------------------+
```

**Strict Rule:** The LLM NEVER predicts physics. All collision detection, tension estimation, and spatial calculations are computed exclusively by the Simulation Server via deterministic engines (Trimesh/VTK/SOFA). The LLM acts as an intelligent translator between natural language and structured simulation requests.

**State Branching:** The surgeon's view is on `Branch: Main`. The LLM runs background simulations on `Branch: LLM_Hypothesis` — changes are only promoted to Main when the surgeon explicitly approves.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (dual-server: Planning :8200 + Simulation :8300) |
| Frontend | React + Tailwind v4 + Lucide (Command Center :5173) |
| 3D/Physics | VTK, Trimesh, SOFA Framework (spring-mass fallback) |
| AI Orchestration | Anthropic SDK (Claude), Google GenAI (Gemini) |
| Segmentation | TotalSegmentator (automated CT bone extraction) |
| Knowledge Graph | Neo4j (anatomical rules, surgeon corrections) |
| Medical Imaging | pydicom, VTK marching cubes |
| Voice | Whisper (STT, planned), Google/OpenAI TTS (planned) |
| Infrastructure | GCP (Secret Manager, Cloud Storage, Pub/Sub, Spot VMs) |
| IaC | Terraform |
| Services | NSSM (Windows auto-start), Task Scheduler (daily backup) |

### Project Structure

```
OsteoTwin/
+-- planning_server/        # Port 8200: Auth, LLM orchestration, voice, web UI
|   +-- app/
|       +-- auth/            # JWT authentication + admin approval
|       +-- pipeline/        # LLM orchestration (Claude tool-use + Gemini)
|       +-- voice/           # Intraoperative Voice Assistant
|       +-- graph_db/        # Neo4j anatomical rule engine
|       +-- simulation_client/ # HTTP client -> Simulation Server
|       +-- web_ui/          # HTMX web interface
|       +-- main.py
+-- simulation_server/       # Port 8300: Deterministic physics engine
|   +-- app/
|       +-- mesh_processor/  # DICOM -> 3D mesh, implants, STL export
|       +-- collision/       # Trimesh rigid-body collision
|       +-- soft_tissue/     # SOFA FEA + spring-mass fallback
|       +-- main.py
|   +-- worker.py            # Pub/Sub worker (checkpoint/failover on Spot VMs)
+-- dashboard/               # React Command Center (:5173)
|   +-- src/
|       +-- components/      # Overview, Cases, Infrastructure, Settings
+-- shared/                  # Pydantic schemas (single source of truth)
|   +-- schemas/             # FractureCase, ReductionSimulation, AgentDebate
|   +-- simulation_protocol.py   # SimActionRequest / SimActionResponse
|   +-- collision_protocol.py    # CollisionCheckRequest / CollisionCheckResponse
|   +-- soft_tissue_protocol.py  # SoftTissueSimRequest / SoftTissueSimResponse
+-- infra/terraform/         # GCP project (Secret Manager, Storage, Pub/Sub, Spot VMs)
+-- system/                  # Windows services, backup/restore, DICOM cache
+-- tests/                   # E2E integration tests
```

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/agkdc1/OsteoTwin.git
cd OsteoTwin
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r planning_server/requirements.txt
pip install -r simulation_server/requirements.txt

# 2. Configure secrets
cp .env.example .env
# Fill in API keys (or run: bash system/setup_gcp.sh)

# 3. Run servers
python -m planning_server.app.main    # Port 8200
python -m simulation_server.app.main  # Port 8300

# 4. Dashboard (optional)
cd dashboard && npm install && npm run dev  # Port 5173

# 5. Install as Windows services (optional, requires admin)
# Run as Admin: .\system\services.ps1 install && .\system\services.ps1 start
```

## Phase Status

- [x] **Phase 0:** Project scaffolding, shared Pydantic schemas, server skeletons
- [x] **Phase 1:** Rigid body collision, JWT auth, LLM orchestrator (Claude tool-use), multi-agent debate (Claude vs Gemini), DICOM pipeline, Neo4j scaffold, HTMX web UI, Windows services
- [x] **Phase 2:** TotalSegmentator, implant CAD library (20+ items), smart sizing, DICOM-to-mesh tested (2 fragments, 35K verts)
- [x] **Cloud Infra:** Pub/Sub queue, checkpoint bucket, dormant Spot VM (size=0), worker.py with checkpoint/failover
- [x] **Phase 3:** STL export for 3D printing (color-coded fragments + plates, K-wires excluded)
- [x] **Phase 4:** E2E integration test (8/8 passed), live Claude tool-use verified
- [x] **React Dashboard:** Command Center (Vite + React + Tailwind v4 + Lucide)
- [x] **Phase 5:** SOFA soft-tissue scaffolding (spring-mass fallback active, full SOFA pending GPU quota)
- [x] **Phase 6:** Intraoperative Voice Assistant (consultative mode, text-in/text-out)
- [x] **Knowledge Cache:** 44 open access sources with Anthropic prompt caching (AO Surgery Reference all 25 body regions + spine, OpenStax Anatomy, StatPearls, WFNS Spine, ~769K tokens total, 95% cost reduction)
- [x] **Backup:** Daily 2 AM backup to GCS, 14-day hot + Coldline cold storage (never pruned)
- [ ] **Phase 7:** Full SOFA FEA with GPU (blocked: GCP GPU quota, retry after 2026-03-17)

## Contributing

This project is an experiment that blurs the line between medicine and engineering. We welcome 3D graphics engineers, AI researchers, and, most importantly, surgeons who understand the reality of the OR. You don't need to know how to code to contribute — clinical feedback and surgical ideas are invaluable.

**Disclaimer:** OsteoTwin is a simulation framework intended strictly for educational and research purposes. The plans and simulation results provided by this software cannot, under any circumstances, replace the clinical judgment of a licensed medical professional.
