# OsteoTwin — Master Roadmap

> From lightweight rigid-body collision detection on a homelab GPU to full soft-tissue biomechanical simulation on a high-end workstation.

Each phase is gated by **hardware requirements** and **technical prerequisites**. Do not attempt a later phase until the hardware and dependencies of all prior phases are satisfied.

---

## Phase 1: Static Planning & Rigid Body Physics (Current)

**Status:** In Progress

### Hardware
| Component | Spec |
|-----------|------|
| GPU | NVIDIA RTX 3060 (8 GB VRAM) |
| RAM | 16 GB DDR4 |
| CPU | Current desktop CPU |
| Storage | Local SSD |

### Technology
- **Backend:** FastAPI dual-server (Planning :8000, Simulation :8100)
- **3D Physics:** `trimesh` — rigid-body collision detection (mesh-mesh intersection, ray casting)
- **Medical Imaging:** `pydicom` for DICOM parsing, `vtk` for mesh extraction
- **AI Orchestration:** LangChain + Anthropic SDK + Google GenAI — Multi-Agent JSON Tool Use
- **Knowledge Graph:** Neo4j for anatomical rules and surgeon feedback loop

### Features
- [x] Project scaffolding, shared Pydantic schemas, server skeletons
- [ ] Load static bone meshes (STL/OBJ) into the Simulation Server
- [ ] **K-wire trajectory checking:** Given origin + direction, detect intersection with bone/plate meshes
- [ ] **Basic fragment reduction:** Translate/rotate bone fragments, detect inter-fragment collisions
- [ ] **Implant collision detection:** Check if placed hardware (K-wire, plate) collides with other hardware or anatomical boundaries
- [ ] LLM Tool Use integration — Claude bound to `POST /api/v1/simulate/action` and `POST /api/v1/simulate/collision`
- [ ] Neo4j anatomical rule engine — store/retrieve surgeon corrections
- [ ] Multi-Agent Debate (Claude vs Gemini) with simulation validation

### Constraints
- No FEA or soft-tissue dynamics — RAM cannot handle it
- All physics is rigid-body only (boolean intersection, distance queries)
- Meshes are pre-processed static STLs, not dynamically deformed

---

## Phase 2: Automated Segmentation & Implants Library

**Status:** Not Started

### Prerequisites
- Phase 1 fully operational
- Sufficient storage for large DICOM datasets and trained segmentation models

### Hardware
| Component | Spec |
|-----------|------|
| GPU | RTX 3060 8 GB (sufficient for inference-only segmentation) |
| RAM | 32 GB recommended (16 GB minimum with swap) |

### Technology
- **Segmentation:** `MONAI` or `TotalSegmentator` for automated CT → bone mesh extraction
- **Implant CAD Library:** Parametric 3D models of standard orthopedic hardware
  - Locking plates (LCP 3.5mm, 2.4mm — various hole counts)
  - Cortical & cancellous screws (various diameters/lengths)
  - K-wires (1.0mm, 1.2mm, 1.6mm, 2.0mm)
  - Intramedullary nails
  - External fixator pins

### Features
- [x] Automated DICOM-to-mesh pipeline (upload CT → segmented bone fragments in minutes)
- [x] Searchable implant library with manufacturer-accurate 3D models
- [x] Smart implant sizing — recommend plate/screw dimensions based on bone geometry
- [ ] Pre-contoured plate fitting simulation

### Goal
Seamless pipeline from raw CT scans to fully manipulatable 3D environments with an accurate implant library, eliminating manual mesh preparation.

---

## Cloud Infrastructure (Provisioned, Dormant)

**Status:** Infrastructure provisioned via Terraform. **Zero compute cost** — all instances at `target_size = 0`.

### Why Provision Now?
The Pub/Sub queue, checkpoint bucket, and Spot VM template are provisioned early so the architecture is cloud-ready from day one. When Phase 3 requires heavy FEA processing that exceeds our local RTX 3060, we simply set `target_size = 1` in Terraform and the cloud workers activate automatically.

### Provisioned Resources (No Cost at Size 0)

| Resource | Name | Purpose | Cost Now |
|----------|------|---------|----------|
| Pub/Sub Topic | `simulation-tasks-topic` | Async task queue | Free tier |
| Pub/Sub Sub | `simulation-worker-sub` | Worker pull subscription | Free tier |
| GCS Bucket | `osteotwin-*-checkpoints` | Simulation state checkpoints | Free (empty) |
| Instance Template | `osteotwin-sim-worker-*` | Spot GPU VM (T4) template | $0 (template only) |
| MIG | `osteotwin-sim-workers` | Managed instance group | **$0 (target_size=0)** |

### Activation (Phase 3)
```bash
# When ready for cloud compute, just change target_size:
cd infra/terraform
# Edit main.tf: target_size = 1
terraform apply
```

### Worker Architecture
- **Checkpoint/Failover:** Worker saves intermediate state to GCS every N steps. On Spot preemption (SIGTERM), saves final checkpoint and exits cleanly. Next worker resumes from the checkpoint.
- **ACK-on-Complete:** Pub/Sub messages are only ACK'd after 100% completion and result upload. Failed tasks are automatically retried via NACK + dead letter.
- **Local Mode:** Same `worker.py` runs locally without Pub/Sub for Phase 1-2 development.

---

## Phase 5: Soft-Tissue Biomechanics — SOFA Integration

**Status:** Scaffolding Complete — Spring-mass fallback active

### What's Built
- [x] `shared/soft_tissue_protocol.py` — Full Pydantic schema for tissue definitions, tension results, vascular proximity
- [x] `simulation_server/app/soft_tissue/engine.py` — Dual-mode engine (SOFA FEA + spring-mass fallback)
- [x] `simulation_server/app/soft_tissue/router.py` — API endpoints (`/api/v1/soft-tissue/simulate`, `/status`)
- [x] Spring-mass model verified: correctly computes tension, strain, risk levels
- [x] SOFA scene generator (auto-generates `.py` scenes for `runSofa` batch mode)
- [ ] Install SOFA binaries + SofaPython3 (conda or binary — waiting for GPU quota)
- [ ] Real FEA simulation with tetrahedral meshes

### How It Works Now (Without SOFA)
The spring-mass model treats each soft tissue as a spring connecting two attachment points on bone fragments. When fragments move, tissue tension is computed as `F = k * max(0, current_length - rest_length)`. This gives clinically useful feedback (tension thresholds, risk levels) without GPU.

### How It Will Work (With SOFA)
When SOFA is installed, the engine automatically detects `SofaPython3`, generates a SOFA scene with proper FEA solvers (EulerImplicit + CG), and runs it in subprocess batch mode. Results are parsed from output files.

### Prerequisites for Full SOFA
- GPU quota approved (retry after 2026-03-17)
- Install: `conda install sofa-python3 -c sofa-framework -c conda-forge`
- Or: Download SOFA v25.12+ binaries from sofa-framework.org

---

## Phase 6: Intraoperative Voice Assistant

**Status:** Complete (text-in/text-out prototype)

### Architecture
```
Surgeon speaks → [STT] → Text → VoiceAgentOrchestrator → Claude (tool-use) → Simulation Server → Clinical Response → [TTS] → Surgeon hears
```

### What's Built
- [x] `planning_server/app/voice/prompts.py` — Consultative system prompt (non-prescriptive guardrails)
- [x] `planning_server/app/voice/orchestrator.py` — Full orchestrator with tool-use loop (simulate_action, check_collision, check_soft_tissue)
- [x] `planning_server/app/voice/router.py` — `POST /api/v1/voice/query` (text-in/text-out)
- [x] Session persistence per case (conversation context maintained)
- [x] Surgical plan injection into system prompt
- [ ] STT integration (Whisper)
- [ ] TTS integration (Google/OpenAI TTS)
- [ ] Wake word detection ("Osteo, ...")

### Consultative Guardrails
The voice agent NEVER gives commands. It phrases everything as observations:
- "The simulation indicates..." NOT "Do X now"
- "Based on the plan, the K-wire entry point is at..." NOT "Insert the K-wire here"
- Flags safety concerns as observations, not directives

---

## Phase 7: Soft-Tissue Biomechanics & FEA (The Ultimate Goal)

**Status:** Not Started — Blocked by hardware upgrade

### Prerequisites
- Phase 2 fully operational
- **Hardware upgrade completed** (see below)

### Hardware Upgrade Required
| Component | Minimum Spec | Recommended Spec |
|-----------|-------------|-----------------|
| CPU | Intel Core i9-14900K / AMD Ryzen 9 7950X | Threadripper PRO |
| RAM | **64 GB DDR5** | **128 GB DDR5** |
| GPU | NVIDIA RTX 4080 (16 GB) | **RTX 4090 (24 GB)** |
| Storage | 2 TB NVMe SSD | 4 TB NVMe RAID |

**Alternative:** On-demand cloud GPU via RunPod, Lambda Labs, or AWS (p4d.24xlarge) for burst FEA workloads while keeping the local homelab for development.

### Technology
- **Soft-Tissue Engine:** `SOFA Framework` (Simulation Open Framework Architecture)
  - Position-Based Dynamics (PBD) for real-time deformation
  - Finite Element Analysis (FEA) for accurate tissue stress/strain
- **Muscle/Tendon Modeling:** Attach muscle origin/insertion points to bone meshes, calculate tension vectors during fragment manipulation
- **Advanced Collision:** Continuous collision detection (CCD) for dynamic scenarios

### Features
- [ ] Real-time soft-tissue tension calculation during fragment reduction
  - "Moving this distal fragment 5mm laterally increases supraspinatus tension to 45N (threshold: 30N)"
- [ ] Dynamic fracture reduction feedback — see soft tissue deform as bones are repositioned
- [ ] Muscle/tendon pull vector visualization on the 3D viewer
- [ ] Periosteal stripping estimation based on fragment displacement
- [ ] Vascular proximity warnings (e.g., brachial artery displacement during humeral fracture reduction)

### Goal
A fully biomechanical digital twin where the surgeon can feel (visually) how soft tissues respond to every manipulation, producing surgical plans that account for the dynamic reality of the OR.

---

## Phase 4: Clinical Feedback Loop & Self-Correction (Vision)

**Status:** Long-term research

### Concept
Feed actual recorded surgical videos back into the system to self-correct the AI's anatomical recognition and tension predictions. Compare pre-op simulation predictions with intra-op reality.

### Features (Aspirational)
- [ ] Intra-operative video ingestion and landmark tracking
- [ ] Post-op outcome correlation (did the simulation-predicted risk materialize?)
- [ ] Continuous model refinement via surgeon feedback stored in the Knowledge Graph
- [ ] Multi-institution federated learning for anonymized case data

---

## Hardware Upgrade Decision Matrix

| Phase | RAM | GPU VRAM | Can Run on Current Homelab? |
|-------|-----|----------|---------------------------|
| Phase 1 (Rigid Body) | 16 GB | 8 GB | **Yes** |
| Phase 2 (Segmentation) | 32 GB | 8 GB | Marginal (inference OK, training NO) |
| Phase 3 (FEA/Soft Tissue) | 64-128 GB | 16-24 GB | **No — upgrade required** |
| Phase 4 (Video/ML) | 128 GB | 24 GB+ | **No — cloud recommended** |
