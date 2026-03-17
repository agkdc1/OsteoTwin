# OsteoTwin — Roadmap

> Patient-specific surgical rehearsal: from DICOM scan to 3D-printed model with AI-debated reduction plan.

---

## Completed

### Core Platform
- [x] Dual-server architecture (Planning :8200 + Simulation :8300)
- [x] JWT auth with admin approval flow
- [x] React Command Center (Vite + Tailwind v4 + Three.js/R3F)
- [x] Windows services (NSSM auto-start), daily 2 AM GCS backup
- [x] Terraform-managed GCP infra (Storage, Pub/Sub, Firestore, Spot VMs)

### Simulation Engine
- [x] Rigid-body collision detection (trimesh + FCL)
- [x] K-wire trajectory ray-casting with cortex penetration flags
- [x] Mesh-mesh boolean intersection (fragment-fragment, fragment-hardware)
- [x] DICOM-to-mesh pipeline (VTK marching cubes + TotalSegmentator)
- [x] Implant CAD library (20+ parametric items, smart sizing)
- [x] Soft-tissue engine: spring-mass fallback active, SOFA FEA scaffolded
- [x] THUMS v7.1 integration: 4 subjects parsed (2,381 parts, 840K nodes, 2.1M elements per subject), material properties extracted, SOFA material configs generated

### AI Pipeline
- [x] Zero-Trust Grounding enforced across all prompts (source-only, no training data, consultative tone)
- [x] 2-track pipeline: Gemini Librarian (1.88M-token knowledge cache) extracts surgical brief, Claude Surgeon reasons with simulation tools
- [x] Multi-Agent Debate (Claude vs Gemini, sourced claims, structured rounds)
- [x] Intraoperative Voice Assistant (Whisper STT + Edge/Google/OpenAI TTS, consultative mode)
- [x] Neo4j Knowledge Graph (anatomical rules, surgeon corrections)

### Spatial-Semantic Schema
- [x] LPS coordinate standard (DICOM native) across all agents
- [x] Clinical-term-to-math bridge (kinematics.py, side-aware L/R sign convention)
- [x] SurgicalAction as universal inter-agent message
- [x] Bi-directional 3D UI sync (Three.js drag -> LPS delta -> backend dispatch -> Claude context injection)

### 3D Print & Export
- [x] Multi-material 3MF export with per-object extruder metadata
- [x] Named-STL ZIP fallback with manifest
- [x] Printer admin UI (color-to-extruder mapping matrix)
- [x] K-wires excluded from prints (use real metal)
- [x] 0.3-0.5mm global fillet for print aesthetics

### Autonomous CAD Pipeline (Phase 9)
- [x] Manufacturer Alias System (3-letter codes: SYN, STK, ZIM, etc.)
- [x] Gemini dimension extraction from catalog descriptions
- [x] Claude OpenSCAD generation (minkowski fillets, countersunk holes)
- [x] 6-way orthographic rendering + Pillow grid stitch
- [x] Gemini QA validation (10-point checklist, XML APPROVED/REJECTED)
- [x] Claude auto-correction loop with 6-strike safety halt
- [x] OpenSCAD CLI STL/3MF export

### Clinical Logging
- [x] Firestore (Native Mode) for case lifecycle logging
- [x] Quantitative metrics: AI plan vs surgeon plan delta, time-to-decision
- [x] Qualitative metrics: intent mismatch logs, post-op deviation logs
- [x] Async fire-and-forget writer (non-blocking)

### Testing
- [x] 132 tests (unit + physics E2E + scenario), 0 failures
- [x] Real trimesh collision, spring-mass tension, STL export exercised (~29s)
- [x] 5 realistic surgical scenarios (distal radius, left humerus, print config, CAD QA, coordinate integrity)

---

## In Progress

### GPU Compute Activation
- [x] NVIDIA L4 per-region quota confirmed (1x, asia-northeast1)
- [x] NVIDIA T4 per-region quota confirmed (1x, asia-northeast1)
- [x] Terraform updated to g2-standard-8 + nvidia-l4
- [ ] **BLOCKER:** `GPUS_ALL_REGIONS` global quota = 0 (auto-declined twice). Paid account with credits. Retry quota request on 2026-03-21 (Friday).
- [ ] Scale MIG to 1 for first cloud simulation run (after global quota approved)
- [ ] Terraform-ize the full SOFA worker setup (bake into startup-script after initial test)

### SOFA FEA with Real THUMS Data
- [x] THUMS material properties parsed and mapped to SOFA force fields
- [x] THUMSMaterialDB auto-loads into soft-tissue engine by body region
- [ ] Install SOFA binaries on L4 GPU worker
- [ ] Run first real FEA simulation with THUMS knee joint (ACL/PCL/MCL tension under valgus load)
- [ ] Validate FEA results against THUMS manual mass table (2% tolerance)

---

## Next Up

### Full THUMS Mesh Conversion
- [x] Export all 2,381 parts per subject as VTK unstructured grids (1,197 solid meshes, 133MB for AM50)
- [x] Decimate high-density meshes: LOD1 (2.1M faces, 90%), LOD2 (1.1M faces, 95% reduction) via quadric decimation
- [x] THUMS mesh serving API (VTK-to-STL on-the-fly, region/mat_type filtering, batch scene loading)
- [x] Three.js viewer: THUMS Anatomy Browser panel (browse by region, click to load, material color-coding)

### Intraoperative C-arm Simulation
- [x] DRR engine: ray-cast Beer-Lambert attenuation through bone mesh volume
- [x] AP, Lateral, and arbitrary oblique projections (angle around Z-axis)
- [x] PNG output (bone=white on black, standard X-ray appearance)
- [x] Multi-view batch: AP + Lateral + 30/45/60 deg obliques in one call
- [x] API: POST /api/v1/carm/render (single view), POST /api/v1/carm/multiview
- [ ] Compare virtual C-arm with actual OR images (future)

### Surgical Approach Mapping
- [x] Approach Atlas: 5 named approaches with danger zones, layers, source citations
  - Henry (volar distal radius), Thompson (dorsal proximal radius)
  - Kocher-Langenbeck (posterior acetabulum), Deltopectoral (proximal humerus)
  - Lateral Parapatellar (distal femur)
- [x] Danger zone data: structure name, type, LPS position, safe distance, notes
- [x] API: GET /api/v1/approaches, GET /{key}/danger-zones.stl (3D overlay)
- [x] Layer-by-layer dissection descriptions (skin → bone for each approach)
- [ ] Patient-specific danger zone adjustment from CT segmentation (future)

---

## Future Vision

### Clinical Feedback Loop
- [ ] Post-op outcome correlation: did the simulation-predicted risks materialize?
- [ ] Surgeon correction persistence in Neo4j → improves future plans
- [ ] Multi-institution anonymized case aggregation

### Video-Based Validation
- [ ] Intra-operative video ingestion and landmark tracking
- [ ] Compare pre-op digital twin state with actual OR positions
- [ ] Continuous model refinement from real surgical data

### Advanced Biomechanics
- [ ] Continuous collision detection (CCD) for dynamic reduction sequences
- [ ] Muscle pull vector visualization during fragment manipulation
- [ ] Patient-specific tissue properties from MRI elastography
- [ ] Fracture propagation simulation (when does the bone break under load?)

---

## Hardware

| Environment | Spec | Status |
|-------------|------|--------|
| Local dev | RTX 3060 8GB, 16GB RAM, Windows 11 | Active |
| Cloud (L4) | g2-standard-8 + NVIDIA L4 24GB, Spot | Quota confirmed, dormant |
| Cloud (T4) | n1-standard-8 + NVIDIA T4 16GB, Spot | Quota confirmed, dormant |

Scale up with: `gcloud compute instance-groups managed resize osteotwin-sim-workers --size=1 --zone=asia-northeast1-a`
