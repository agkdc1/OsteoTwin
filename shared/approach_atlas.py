"""Surgical Approach Atlas — maps named approaches to anatomical structures.

Each approach defines:
- Target bone/region
- Interval (safe corridor between structures)
- Danger zones (nerves, vessels at risk)
- Landmark positions (approximate, in LPS relative to bone centroid)

This is the structured data that gets overlaid on the 3D mesh
when a surgeon selects an approach.

Source: AO Surgery Reference, Campbell's Operative Orthopaedics.
All positions are approximate and should be refined per patient CT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DangerLevel(str, Enum):
    CRITICAL = "critical"   # nerve/vessel directly in path
    WARNING = "warning"     # within 10mm of approach
    MONITOR = "monitor"     # in operative field but not directly threatened


@dataclass
class DangerZone:
    """A structure at risk during a surgical approach."""
    name: str
    structure_type: str  # "nerve", "artery", "vein", "tendon"
    danger_level: DangerLevel
    # Approximate position relative to bone centroid (LPS mm)
    position_lps: tuple[float, float, float]
    # Safe distance threshold (mm)
    safe_distance_mm: float = 5.0
    note: str = ""


@dataclass
class SurgicalApproach:
    """A named surgical approach with danger zones and landmarks."""
    name: str
    target_region: str
    description: str
    interval: str  # safe corridor description
    patient_position: str
    incision: str
    danger_zones: list[DangerZone] = field(default_factory=list)
    # Layer-by-layer structures encountered
    layers: list[str] = field(default_factory=list)
    source: str = ""  # citation


# ---------------------------------------------------------------------------
# Atlas: Upper Extremity Approaches
# ---------------------------------------------------------------------------

HENRY_APPROACH = SurgicalApproach(
    name="Henry Approach (Volar)",
    target_region="distal_radius",
    description="Volar approach to the distal radius for ORIF of distal radius fractures",
    interval="Between brachioradialis (radial) and flexor carpi radialis (ulnar)",
    patient_position="Supine, arm on hand table, forearm supinated",
    incision="Longitudinal incision along the FCR tendon, 8-10cm",
    danger_zones=[
        DangerZone("Radial artery", "artery", DangerLevel.CRITICAL,
                   (-8.0, -5.0, -15.0), 3.0,
                   "Lies between brachioradialis and FCR; retract radially with BR"),
        DangerZone("Palmar cutaneous branch of median nerve", "nerve", DangerLevel.WARNING,
                   (0.0, -8.0, -20.0), 5.0,
                   "Emerges from FCR sheath 5cm proximal to wrist crease"),
        DangerZone("Flexor pollicis longus", "tendon", DangerLevel.MONITOR,
                   (-3.0, -3.0, -10.0), 8.0,
                   "Deep to pronator quadratus, retract ulnarly"),
        DangerZone("Median nerve", "nerve", DangerLevel.WARNING,
                   (3.0, -6.0, -5.0), 10.0,
                   "Deep and ulnar to FCR, protected by PQ"),
    ],
    layers=[
        "Skin and subcutaneous tissue",
        "Deep fascia (antebrachial fascia)",
        "Interval: brachioradialis (radial) / FCR (ulnar)",
        "Flexor pollicis longus (retract ulnarly)",
        "Pronator quadratus (elevate from radial border)",
        "Distal radius (volar surface exposed)",
    ],
    source="AO Surgery Reference: Distal Radius, Volar Approach",
)

THOMPSON_APPROACH = SurgicalApproach(
    name="Thompson Approach (Dorsal)",
    target_region="proximal_radius",
    description="Dorsal approach to the proximal radius for radial head/neck fractures",
    interval="Between ECRB (radial) and EDC (ulnar)",
    patient_position="Supine, arm across chest or prone forearm",
    incision="Longitudinal from lateral epicondyle distally, 6-8cm",
    danger_zones=[
        DangerZone("Posterior interosseous nerve (PIN)", "nerve", DangerLevel.CRITICAL,
                   (-10.0, 5.0, 5.0), 3.0,
                   "Crosses the proximal radius within the supinator; keep forearm pronated"),
        DangerZone("Radial nerve (superficial branch)", "nerve", DangerLevel.WARNING,
                   (-12.0, -2.0, 10.0), 5.0,
                   "Runs under brachioradialis proximally"),
    ],
    layers=[
        "Skin and subcutaneous tissue",
        "Deep fascia",
        "Interval: ECRB (radial) / EDC (ulnar)",
        "Supinator muscle (PIN runs within)",
        "Proximal radius periosteum",
    ],
    source="AO Surgery Reference: Proximal Radius, Dorsal Approach",
)

KOCHER_LANGENBECK = SurgicalApproach(
    name="Kocher-Langenbeck Approach",
    target_region="posterior_acetabulum",
    description="Posterior approach to the acetabulum for posterior wall/column fractures",
    interval="Split of gluteus maximus, between short external rotators",
    patient_position="Lateral decubitus, affected side up",
    incision="Curved incision from PSIS to greater trochanter, then along femoral shaft",
    danger_zones=[
        DangerZone("Sciatic nerve", "nerve", DangerLevel.CRITICAL,
                   (5.0, 15.0, -20.0), 5.0,
                   "Courses deep to piriformis; identify and protect throughout"),
        DangerZone("Superior gluteal artery", "artery", DangerLevel.CRITICAL,
                   (0.0, 10.0, 10.0), 5.0,
                   "Exits above piriformis through greater sciatic notch"),
        DangerZone("Inferior gluteal artery", "artery", DangerLevel.WARNING,
                   (0.0, 12.0, -5.0), 5.0,
                   "Exits below piriformis"),
        DangerZone("Medial femoral circumflex artery", "artery", DangerLevel.WARNING,
                   (8.0, 5.0, -15.0), 8.0,
                   "Blood supply to femoral head; protect during retraction"),
    ],
    layers=[
        "Skin and subcutaneous tissue",
        "Gluteus maximus (split along fibers)",
        "Short external rotators (piriformis, obturator internus, gemelli)",
        "Posterior hip capsule",
        "Posterior wall/column of acetabulum",
    ],
    source="AO Surgery Reference: Acetabulum, Kocher-Langenbeck Approach",
)

DELTOPECTORAL = SurgicalApproach(
    name="Deltopectoral Approach",
    target_region="proximal_humerus",
    description="Anterior approach to the proximal humerus for fracture fixation",
    interval="Between deltoid (axillary nerve) and pectoralis major (medial/lateral pectoral nerves)",
    patient_position="Beach chair position, arm draped free",
    incision="Coracoid to deltoid insertion, following deltopectoral groove",
    danger_zones=[
        DangerZone("Cephalic vein", "vein", DangerLevel.MONITOR,
                   (-5.0, -8.0, 15.0), 5.0,
                   "Runs in the deltopectoral groove; retract laterally with deltoid"),
        DangerZone("Axillary nerve", "nerve", DangerLevel.CRITICAL,
                   (-15.0, 0.0, -5.0), 5.0,
                   "Courses around surgical neck of humerus ~5-7cm below acromion"),
        DangerZone("Anterior circumflex humeral artery", "artery", DangerLevel.WARNING,
                   (-10.0, -5.0, 0.0), 5.0,
                   "Runs along inferior border of subscapularis with axillary nerve"),
        DangerZone("Musculocutaneous nerve", "nerve", DangerLevel.WARNING,
                   (0.0, -3.0, 5.0), 8.0,
                   "Penetrates coracobrachialis ~5-8cm below coracoid"),
    ],
    layers=[
        "Skin and subcutaneous tissue",
        "Deltopectoral groove (cephalic vein landmark)",
        "Deltoid (retract laterally) / Pectoralis major (retract medially)",
        "Subscapularis and anterior capsule",
        "Proximal humerus",
    ],
    source="AO Surgery Reference: Proximal Humerus, Deltopectoral Approach",
)

LATERAL_KNEE = SurgicalApproach(
    name="Lateral Parapatellar Approach",
    target_region="distal_femur",
    description="Lateral approach to the distal femur for supracondylar/intercondylar fractures",
    interval="Lateral to patella and patellar tendon",
    patient_position="Supine, knee flexed 30-60 degrees over bolster",
    incision="Lateral midline from 10cm above patella to tibial tubercle",
    danger_zones=[
        DangerZone("Common peroneal nerve", "nerve", DangerLevel.CRITICAL,
                   (-15.0, 10.0, -40.0), 5.0,
                   "Wraps around fibular neck; at risk with distal extension"),
        DangerZone("Lateral superior genicular artery", "artery", DangerLevel.WARNING,
                   (-12.0, 0.0, -5.0), 5.0,
                   "Runs above lateral femoral condyle"),
        DangerZone("Lateral inferior genicular artery", "artery", DangerLevel.MONITOR,
                   (-12.0, 0.0, -20.0), 8.0,
                   "Below joint line, at risk during lateral meniscus retraction"),
    ],
    layers=[
        "Skin and subcutaneous tissue",
        "Iliotibial band / lateral retinaculum",
        "Vastus lateralis (elevate from intermuscular septum)",
        "Periosteum of lateral distal femur",
    ],
    source="AO Surgery Reference: Distal Femur, Lateral Approach",
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

APPROACH_ATLAS: dict[str, SurgicalApproach] = {
    "henry_volar": HENRY_APPROACH,
    "thompson_dorsal": THOMPSON_APPROACH,
    "kocher_langenbeck": KOCHER_LANGENBECK,
    "deltopectoral": DELTOPECTORAL,
    "lateral_knee": LATERAL_KNEE,
}


def get_approaches_for_region(region: str) -> list[SurgicalApproach]:
    """Get all approaches that target a given body region."""
    return [a for a in APPROACH_ATLAS.values() if region in a.target_region]


def get_approach(name: str) -> SurgicalApproach | None:
    """Lookup an approach by registry key."""
    return APPROACH_ATLAS.get(name)
