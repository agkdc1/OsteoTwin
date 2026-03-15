AI-Driven Orthopedic Reduction & Surgical Planning Simulator

"What if I could completely clear the fog in my mind before stepping into the operating room?"

OsteoTwin is an open-source pre-operative planning and simulation framework born from the cognitive overload and inherent uncertainties faced by surgeons during complex fracture reductions. By bridging biomechanical 3D simulation with a Multi-Agent LLM architecture, OsteoTwin analyzes patient-specific anatomy to formulate, debate, and refine the optimal surgical reduction scenario.

💡 Why We Built This
Even with 3D-reconstructed CT scans, the actual reduction of a complex fracture often relies heavily on the surgeon's "spatial imagination." Unless you are a highly seasoned veteran, plans can easily fall apart in the OR due to several critical variables:

Dynamic Soft Tissue Tension: Traditional navigation systems fail to account for the pulling forces of muscles and tendons that shift when bone fragments are moved.

Unforeseen Hardware Collisions: A K-wire perfectly placed for temporary fixation might end up blocking the trajectory of the final locking plate.

The Isolation of the OR: It is rare to have a "perfect sparring partner" to fiercely debate variables and validate surgical plans the night before the operation.

OsteoTwin simulates these exact variables beforehand. Even if the actual surgery deviates from the plan, a surgeon who has pre-simulated all potential pitfalls enters the OR with a clear, confident mind.

🚀 Core Pipeline
From ingesting DICOM data to outputting a comprehensive surgical plan, OsteoTwin operates through the following pipeline:

1. Radiological Description & Classification
The LLM analyzes the fracture geometry based on the provided data, generating a detailed anatomical description.

Through a feedback loop with the surgeon, it refines the context by applying international standard classifications (AO Foundation, Rockwood, Weber, etc.).

2. Virtual OR Setup & C-arm Simulation
Configures the patient's positioning and the C-arm insertion angles.

Simulates and predicts the exact fluoroscopic images that will be seen on the C-arm monitor at those specific angles within the 3D viewer.

3. Anatomical Approach Mapping
When a specific surgical approach (e.g., the Henry approach) is selected, the system maps the trajectory, highlighting visible structures and critical "danger zones" (nerves, vessels) directly on the 3D mesh.

4. Biomechanical Reduction Simulation
Calculates the expected tension vectors of attached muscles and tendons when a bone fragment is manipulated.

Allows the virtual placement of K-wires and reduction forceps to detect physical collisions between implants.

The LLM intervenes with real-time insights: "Elevating this fragment will be hindered by the tension of the supraspinatus. A targeted release is recommended."

5. Multi-Agent Debate (The Surgical Council)
Two or more AI agents (e.g., Claude and Gemini Pro) engage in a debate based on the simulation data.

Through cross-validation, the "Council" outputs Plan A, alternative Plans B and C, and a final operative document detailing anticipated difficulties and precautions for each step.

6. Physical Twin (3D Printing Integration)
Exports an STL file where bone fragments and key soft-tissue footprints are color-coded.

Enables surgeons to 3D print the model and perform tactile practice with actual K-wires and screws the night before surgery.

🏗️ Architecture
OsteoTwin adopts a scalable, modular microservice architecture with strict separation between AI reasoning, deterministic physics, and persistent knowledge.

```
┌──────────────────────────────────────────────────────────────────┐
│  User (Surgeon)                                                  │
│  HTMX + Alpine.js / Three.js UI                                 │
└────────────────┬─────────────────────────────────────────────────┘
                 │
    ┌────────────▼────────────┐       ┌──────────────────────────┐
    │  Planning Server :8200  │       │   Neo4j Graph DB         │
    │  ─────────────────────  │◄─────►│   (Anatomical Rule       │
    │  Auth (JWT)             │       │    Engine / Feedback)     │
    │  Project CRUD           │       └──────────────────────────┘
    │  LLM Orchestrator       │
    │   ├─ Claude (Primary)   │
    │   └─ Gemini (Secondary) │
    │  Multi-Agent Debate     │
    └────────────┬────────────┘
                 │ SimActionRequest / SimActionResponse (JSON)
    ┌────────────▼────────────┐
    │  Simulation Server :8300│
    │  ─────────────────────  │
    │  DICOM → Mesh (VTK)     │
    │  Collision (Trimesh)    │
    │  Branch State Manager   │
    │  STL Export (3D Print)  │
    │  [Future: SOFA soft-    │
    │   tissue biomechanics]  │
    └─────────────────────────┘
```

**Strict Rule:** The LLM NEVER predicts physics. All collision detection, tension estimation, and spatial calculations are computed exclusively by the Simulation Server via deterministic engines (Trimesh/VTK). The LLM acts as an intelligent translator between natural language and `SimActionRequest`/`SimActionResponse`.

**State Branching:** The surgeon's view is on `Branch: Main`. The LLM runs background simulations on `Branch: LLM_Hypothesis` — changes are only promoted to Main when the surgeon explicitly approves.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Planning Server + Simulation Server) |
| 3D/Physics | VTK, Trimesh, SOFA Framework (future) |
| AI Orchestration | LangChain, Anthropic SDK, Google GenAI |
| Knowledge Graph | Neo4j (anatomical rules, surgeon corrections) |
| Frontend | HTMX + Alpine.js, Three.js |
| Medical Imaging | pydicom |
| Infrastructure | GCP (Secret Manager, Cloud Storage), Terraform |

### Project Structure

```
OsteoTwin/
├── planning_server/        # Port 8200: Auth, LLM orchestration, web UI
│   └── app/
│       ├── auth/            # JWT authentication
│       ├── pipeline/        # LLM orchestration (Claude + Gemini)
│       ├── graph_db/        # Neo4j anatomical rule engine
│       ├── simulation_client/ # HTTP client → Simulation Server
│       └── main.py
├── simulation_server/      # Port 8300: Deterministic physics engine
│   └── app/
│       ├── mesh_processor/  # DICOM → 3D mesh via VTK
│       ├── collision/       # Trimesh rigid-body collision
│       ├── viewer/          # Three.js 3D viewer
│       └── main.py
├── shared/                 # Pydantic schemas (single source of truth)
│   ├── schemas/             # FractureCase, ReductionSimulation, AgentDebate
│   └── simulation_protocol.py  # SimActionRequest / SimActionResponse
├── infra/terraform/        # GCP project setup (Secret Manager, Storage)
├── system/                 # Deployment scripts
└── config/                 # Hardware/implant specifications
```

🤝 Roadmap & Future Vision
OsteoTwin aims to become a continuously evolving, self-correcting loop.

[ ] Automated DICOM-to-3D Mesh pipeline (via MONAI integration)

[ ] 3D CAD library for standard orthopedic implants (Plates, Screws)

[ ] Multi-Agent debate prompt engineering and routing modules

[ ] [Long-term] A vision system that feeds actual recorded surgical videos back into the system to self-correct the AI's anatomical recognition and tension predictions.

👨‍⚕️ Contributing
This project is an experiment that blurs the line between medicine and engineering. We welcome 3D graphics engineers, AI researchers, and, most importantly, surgeons who understand the reality of the OR. You don't need to know how to code to contribute—clinical feedback and surgical ideas are invaluable.

Disclaimer: OsteoTwin is a simulation framework intended strictly for educational and research purposes. The plans and simulation results provided by this software cannot, under any circumstances, replace the clinical judgment of a licensed medical professional.