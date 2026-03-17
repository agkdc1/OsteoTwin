# OsteoTwin

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![GCP: Powered](https://img.shields.io/badge/GCP-Cloud_Native-blue?logo=google-cloud)
![AI: Multi-Agent](https://img.shields.io/badge/AI-Claude_%26_Gemini-orange)
![Field: Orthopaedics](https://img.shields.io/badge/Field-Orthopaedic_Surgery-red)

### The Digital Twin Your Surgeon Wishes Existed the Night Before Surgery

> *"What if I could shatter every bone in the simulation a hundred times, so that when I hold the real scalpel, my hands already know the way?"*

---

OsteoTwin is an open-source **patient-specific surgical planning simulator** that gives orthopedic surgeons a deterministic, physics-grounded rehearsal environment. It features AI agents that debate reduction strategies, a 3D engine that validates every millimeter, and high-fidelity 3D-printable outputs for tactile practice.

This is not a black-box AI. The LLM **never predicts physics.** Every collision and tension vector comes from a deterministic simulation engine. The AI's role is strictly to translate between the surgeon's natural language and the engine's math, grounded in verified medical literature.

## The Problem We Solve

Complex fracture reduction is one of the most spatially demanding tasks in surgery. Even with 3D-reconstructed CT scans, surgeons often face:

* **Invisible Soft Tissue Tension:** Traditional navigation systems are blind to the pull of tendons and muscles during bone movement.
* **Hidden Hardware Collisions:** Temporary fixation often blocks the trajectory of final locking plates—a discovery usually made too late in the OR.
* **Cognitive Overload:** There is no "sparring partner" to challenge a surgeon's reduction strategy under stress.
* **Visual Occlusion:** In the OR, ceiling cameras are often blocked by heads or shadows. OsteoTwin's voice-synced twin provides a "shadow-less" view.

## What Makes This Different

### Zero-Trust AI Architecture

We do not trust LLM internal weights for medical safety. We enforce a **Zero-Trust Grounding** protocol:

1. **Source-Only Knowledge** — All clinical claims must come from the cached knowledge base (AO Surgery Reference, OpenStax Anatomy, StatPearls) with explicit citations.
2. **Deterministic Physics Isolation** — The LLM is the *interpreter*, not the *physicist*. All spatial calculations are computed by deterministic engines (Trimesh/SOFA).
3. **Consultative, Not Prescriptive** — The system retrieves data (e.g., *"Based on AO Manual..."*) but never "recommends" a path. The surgeon holds final authority.
4. **Verifiable Audit Trail** — Every plan mismatch or surgeon correction is logged to **GCP Firestore** with natural language rationale for retrospective peer review.

### Multi-Agent Surgical Council

Two AI agents (Claude and Gemini) independently analyze the case and cross-validate strategies. To bypass token limits and noise, **Gemini (Librarian)** distills 1.88M tokens into a high-density 20K-token brief, which **Claude (Surgeon)** then uses for precise reasoning.

### Aesthetic & Tactile Fidelity

* **Bi-Directional Digital Twin:** Manipulate fragments via 3D drag-and-drop; the system auto-syncs LPS coordinates and dispatches to the physics engine.
* **Refinement Layer:** Our CAD pipeline applies a **0.3mm-0.5mm global fillet** to all models. This ensures professional "light-catching" aesthetics and smoother, stronger 3D prints.
* **Physical Twin (3D Print):** Exports multi-material 3MF files. Surgeons print models to rehearse with real K-wires and screws.

## Core Pipeline

```
  DICOM CT Scan
       |
       v
  [TotalSegmentator] ──> Bone Mesh Extraction (VTK marching cubes)
       |
       v
  [Simulation Server] ──> Deterministic Physics
  │  Collision detection (Trimesh) & Soft-tissue (SOFA)
  │  Aesthetic Refinement (Automatic Fillets/Chamfers)
       |
       v
  [Multi-Agent Orchestrator]
  │  Librarian (Gemini) extracts brief -> Surgeon (Claude) reasons
  │  Multi-Agent Debate: Cross-validation of reduction plans
       |
       v
  [React Command Center]
  │  3D Viewer (R3F) + Voice Assistant (Whisper/TTS)
  │  Audit Logger (Firestore: quantitative + qualitative logs)
       |
       v
  [3D Print Export] ──> 3MF with extruder metadata
```

## Architecture

```
                      React Command Center (:5173)
                               |
               +---------------+---------------+
               |                               |
   +-----------v-----------+   +---------------v-----------+
   |  Planning Server :8200|   |  Simulation Server :8300  |
   |  ---------------------|   |  ------------------------ |
   |  Zero-Trust LLM Agent | J |  Mesh Processing (VTK)    |
   |  Multi-Agent Debate   | S |  Collision (Trimesh)      |
   |  Knowledge Cache      | O |  Aesthetic CAD Refinement |
   |  Firestore Logger     | N |  3MF/STL Export           |
   +-----------+-----------+   +---------------------------+
               |
   +-----------v-----------+
   |  Neo4j Knowledge Graph |   Firestore (clinical_case_logs)
   |  (Anatomical Rules)    |   GCS (DICOM, backups)
   +------------------------+
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Planning :8200 + Simulation :8300) |
| Frontend | React 19 + Tailwind v4 + Three.js/R3F |
| 3D/Physics | VTK, Trimesh, SOFA Framework |
| AI | Anthropic Claude 3.5 Sonnet, Google Gemini 1.5 Pro |
| Data | GCP Firestore, GCS, Pub/Sub, Neo4j |
| IaC | Terraform |
| License | MIT |

## Quick Start

```bash
# 1. Setup environment
git clone https://github.com/agkdc1/OsteoTwin.git
cd OsteoTwin && python -m venv .venv && source .venv/bin/activate
pip install -r planning_server/requirements.txt
pip install -r simulation_server/requirements.txt

# 2. Run servers
python -m planning_server.app.main     # Port 8200
python -m simulation_server.app.main   # Port 8300

# 3. Dashboard
cd dashboard && npm install && npm run dev   # Port 5173
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

**Disclaimer:** OsteoTwin is a research framework only. It does not provide medical advice. Plans cannot replace the judgment of a licensed professional.
