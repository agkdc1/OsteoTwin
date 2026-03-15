"""Registry of open access orthopedic reference sources.

Each source is tagged by body region and topic so the cache loader can
assemble the right reference set based on the AO code or surgical context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SourceType(str, Enum):
    pdf = "pdf"
    html = "html"
    api = "api"


class BodyRegion(str, Enum):
    general = "general"
    upper_extremity = "upper_extremity"
    lower_extremity = "lower_extremity"
    spine = "spine"
    pelvis = "pelvis"
    hand_wrist = "hand_wrist"
    foot_ankle = "foot_ankle"
    shoulder = "shoulder"
    hip = "hip"
    knee = "knee"
    elbow = "elbow"
    pediatric = "pediatric"


class Topic(str, Enum):
    anatomy = "anatomy"
    classification = "classification"
    surgical_approach = "surgical_approach"
    surgical_technique = "surgical_technique"
    fracture_management = "fracture_management"
    arthroplasty = "arthroplasty"
    sports_medicine = "sports_medicine"
    spine_surgery = "spine_surgery"
    implants = "implants"
    pitfalls = "pitfalls"
    soft_tissue = "soft_tissue"
    biomechanics = "biomechanics"
    deformity = "deformity"
    pediatric = "pediatric"
    nerves_vessels = "nerves_vessels"


@dataclass
class ReferenceSource:
    """A single open access reference source."""

    id: str
    name: str
    url: str
    source_type: SourceType
    license: str
    regions: list[BodyRegion] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)
    description: str = ""
    estimated_tokens: int = 0
    # For HTML sources: CSS selectors or extraction hints
    extract_selector: Optional[str] = None
    # For APIs: endpoint pattern
    api_pattern: Optional[str] = None
    # Sub-URLs for multi-page sources
    sub_urls: list[str] = field(default_factory=list)
    # Priority (lower = more important, loaded first)
    priority: int = 5


# =============================================================================
# Source Registry
# =============================================================================

SOURCES: list[ReferenceSource] = [
    # -------------------------------------------------------------------------
    # Tier 1: Always-loaded core references
    # -------------------------------------------------------------------------
    ReferenceSource(
        id="ao_classification_2018",
        name="AO/OTA Fracture Classification Compendium 2018",
        url="https://classification.aoeducation.org/files/download/AOOTA_Classification_2018_Compendium.pdf",
        source_type=SourceType.pdf,
        license="Free for research/education (AO Foundation)",
        regions=[r for r in BodyRegion],  # All regions
        topics=[Topic.classification, Topic.fracture_management],
        description="Complete AO/OTA fracture classification system with 5-element alphanumeric codes and illustrations",
        estimated_tokens=30000,
        priority=1,
    ),
    ReferenceSource(
        id="openstax_anatomy_skeletal",
        name="OpenStax Anatomy & Physiology 2e — Skeletal System",
        url="https://openstax.org/books/anatomy-and-physiology-2e/pages/6-1-the-functions-of-the-skeletal-system",
        source_type=SourceType.html,
        license="CC-BY 4.0",
        regions=[BodyRegion.general],
        topics=[Topic.anatomy, Topic.biomechanics],
        description="Chapters 6-8: Bone tissue, axial skeleton, appendicular skeleton",
        estimated_tokens=25000,
        priority=1,
        sub_urls=[
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/6-1-the-functions-of-the-skeletal-system",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/6-3-bone-structure",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/6-6-exercise-nutrition-hormones-and-bone-tissue",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/7-introduction",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/7-2-the-vertebral-column",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/7-3-the-thoracic-cage",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/8-1-the-pectoral-girdle",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/8-2-bones-of-the-upper-limb",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/8-3-the-pelvic-girdle-and-pelvis",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/8-4-bones-of-the-lower-limb",
        ],
    ),
    ReferenceSource(
        id="openstax_anatomy_joints",
        name="OpenStax Anatomy & Physiology 2e — Joints",
        url="https://openstax.org/books/anatomy-and-physiology-2e/pages/9-introduction",
        source_type=SourceType.html,
        license="CC-BY 4.0",
        regions=[BodyRegion.general],
        topics=[Topic.anatomy, Topic.biomechanics],
        description="Chapter 9: Classification of joints, synovial joints, movements",
        estimated_tokens=15000,
        priority=1,
        sub_urls=[
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/9-1-classification-of-joints",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/9-4-synovial-joints",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/9-5-types-of-body-movements",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/9-6-anatomy-of-selected-synovial-joints",
        ],
    ),
    ReferenceSource(
        id="openstax_anatomy_muscles",
        name="OpenStax Anatomy & Physiology 2e — Muscular System",
        url="https://openstax.org/books/anatomy-and-physiology-2e/pages/10-2-skeletal-muscle",
        source_type=SourceType.html,
        license="CC-BY 4.0",
        regions=[BodyRegion.general],
        topics=[Topic.anatomy, Topic.soft_tissue],
        description="Chapters 10-11: Muscle tissue, naming, actions, attachments",
        estimated_tokens=30000,
        priority=1,
        sub_urls=[
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/10-2-skeletal-muscle",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/11-1-interactions-of-skeletal-muscles-their-fascicle-arrangement-and-their-lever-systems",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/11-2-naming-skeletal-muscles",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/11-3-axial-muscles-of-the-head-neck-and-back",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/11-4-axial-muscles-of-the-abdominal-wall-and-thorax",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/11-5-muscles-of-the-pectoral-girdle-and-upper-limbs",
            "https://openstax.org/books/anatomy-and-physiology-2e/pages/11-6-appendicular-muscles-of-the-pelvic-girdle-and-lower-limbs",
        ],
    ),

    # -------------------------------------------------------------------------
    # Tier 2: StatPearls — body region specific (NCBI Bookshelf, public domain)
    # -------------------------------------------------------------------------

    # -- Spine --
    ReferenceSource(
        id="statpearls_spine_anatomy",
        name="StatPearls — Spine Anatomy Collection",
        url="https://www.ncbi.nlm.nih.gov/books/NBK525969/",
        source_type=SourceType.html,
        license="CC-BY 4.0 (StatPearls/NCBI)",
        regions=[BodyRegion.spine],
        topics=[Topic.anatomy, Topic.spine_surgery, Topic.nerves_vessels],
        description="Vertebral column, cervical/thoracic/lumbar anatomy, spinal cord, Adamkiewicz artery",
        estimated_tokens=20000,
        priority=2,
        sub_urls=[
            "https://www.ncbi.nlm.nih.gov/books/NBK525969/",   # Vertebral column
            "https://www.ncbi.nlm.nih.gov/books/NBK539734/",   # Cervical vertebrae
            "https://www.ncbi.nlm.nih.gov/books/NBK459153/",   # Thoracic vertebrae
            "https://www.ncbi.nlm.nih.gov/books/NBK557616/",   # Lumbar spine
            "https://www.ncbi.nlm.nih.gov/books/NBK526133/",   # Neuroanatomy spine
            "https://www.ncbi.nlm.nih.gov/books/NBK532971/",   # Artery of Adamkiewicz
        ],
    ),
    ReferenceSource(
        id="statpearls_spine_surgery",
        name="StatPearls — Spine Surgery Procedures",
        url="https://www.ncbi.nlm.nih.gov/books/NBK542274/",
        source_type=SourceType.html,
        license="CC-BY 4.0 (StatPearls/NCBI)",
        regions=[BodyRegion.spine],
        topics=[Topic.spine_surgery, Topic.surgical_technique, Topic.pitfalls],
        description="Laminectomy, spinal osteotomy, disc herniation management, fusion techniques",
        estimated_tokens=15000,
        priority=2,
        sub_urls=[
            "https://www.ncbi.nlm.nih.gov/books/NBK542274/",   # Laminectomy
            "https://www.ncbi.nlm.nih.gov/books/NBK499872/",   # Spinal osteotomy
        ],
    ),

    # -- Hip --
    ReferenceSource(
        id="statpearls_hip",
        name="StatPearls — Hip Surgery & Anatomy",
        url="https://www.ncbi.nlm.nih.gov/books/NBK507864/",
        source_type=SourceType.html,
        license="CC-BY 4.0 (StatPearls/NCBI)",
        regions=[BodyRegion.hip, BodyRegion.pelvis],
        topics=[Topic.arthroplasty, Topic.fracture_management, Topic.anatomy],
        description="THA techniques, femoral neck fractures, hip anatomy, AVN",
        estimated_tokens=20000,
        priority=2,
        sub_urls=[
            "https://www.ncbi.nlm.nih.gov/books/NBK507864/",   # THA techniques
            "https://www.ncbi.nlm.nih.gov/books/NBK538236/",   # Femoral neck fracture surgery
            "https://www.ncbi.nlm.nih.gov/books/NBK557514/",   # Hip fracture overview
            "https://www.ncbi.nlm.nih.gov/books/NBK537007/",   # Avascular necrosis
            "https://www.ncbi.nlm.nih.gov/books/NBK430734/",   # Pelvic fracture
        ],
    ),

    # -- Knee --
    ReferenceSource(
        id="statpearls_knee",
        name="StatPearls — Knee Surgery & Anatomy",
        url="https://www.ncbi.nlm.nih.gov/books/NBK538176/",
        source_type=SourceType.html,
        license="CC-BY 4.0 (StatPearls/NCBI)",
        regions=[BodyRegion.knee],
        topics=[Topic.sports_medicine, Topic.fracture_management, Topic.arthroplasty],
        description="ACL injury, meniscus, knee arthroplasty, tibial plateau fractures",
        estimated_tokens=15000,
        priority=2,
        sub_urls=[
            "https://www.ncbi.nlm.nih.gov/books/NBK538176/",   # Septic arthritis
            "https://www.ncbi.nlm.nih.gov/books/NBK542324/",   # Ankle fracture
        ],
    ),

    # -- Shoulder --
    ReferenceSource(
        id="statpearls_shoulder",
        name="StatPearls — Shoulder Anatomy & Surgery",
        url="https://www.ncbi.nlm.nih.gov/books/NBK507841/",
        source_type=SourceType.html,
        license="CC-BY 4.0 (StatPearls/NCBI)",
        regions=[BodyRegion.shoulder, BodyRegion.upper_extremity],
        topics=[Topic.anatomy, Topic.sports_medicine, Topic.surgical_approach],
        description="Arm structure, rotator cuff, shoulder anatomy, surgical approaches",
        estimated_tokens=10000,
        priority=2,
        sub_urls=[
            "https://www.ncbi.nlm.nih.gov/books/NBK507841/",   # Arm structure
        ],
    ),

    # -- Wrist / Hand / Forearm --
    ReferenceSource(
        id="statpearls_wrist_hand",
        name="StatPearls — Wrist & Hand Fractures",
        url="https://www.ncbi.nlm.nih.gov/books/NBK553071/",
        source_type=SourceType.html,
        license="CC-BY 4.0 (StatPearls/NCBI)",
        regions=[BodyRegion.hand_wrist, BodyRegion.upper_extremity],
        topics=[Topic.fracture_management, Topic.anatomy],
        description="Colles fracture, distal radius/ulna, scaphoid",
        estimated_tokens=10000,
        priority=2,
        sub_urls=[
            "https://www.ncbi.nlm.nih.gov/books/NBK553071/",   # Colles fracture
            "https://www.ncbi.nlm.nih.gov/sites/books/NBK580565/",  # Distal ulnar
        ],
    ),

    # -- General orthopedic --
    ReferenceSource(
        id="statpearls_ortho_general",
        name="StatPearls — General Orthopedic Topics",
        url="https://www.ncbi.nlm.nih.gov/books/NBK560505/",
        source_type=SourceType.html,
        license="CC-BY 4.0 (StatPearls/NCBI)",
        regions=[BodyRegion.general],
        topics=[Topic.implants, Topic.fracture_management, Topic.biomechanics],
        description="Implant materials, open fracture management, fracture healing",
        estimated_tokens=15000,
        priority=2,
        sub_urls=[
            "https://www.ncbi.nlm.nih.gov/books/NBK560505/",   # Implant materials
            "https://www.ncbi.nlm.nih.gov/books/NBK448083/",   # Open fracture management
            "https://www.ncbi.nlm.nih.gov/books/NBK519029/",   # Heterotopic ossification
        ],
    ),

    # -------------------------------------------------------------------------
    # Tier 2b: AO Surgery Reference — the gold standard for surgical technique
    # (surgeryreference.aofoundation.org, free open access)
    # -------------------------------------------------------------------------

    # -- Upper Extremity --
    ReferenceSource(
        id="aosr_clavicle",
        name="AO Surgery Reference - Clavicle Fractures",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/clavicle-fractures",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.shoulder],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Clavicle fracture classification, approaches, fixation techniques, pitfalls",
        estimated_tokens=8000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/clavicle-fractures",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/clavicle-fractures/approach/all-approaches",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/clavicle-fractures/further-reading/all-further-reading",
        ],
    ),
    ReferenceSource(
        id="aosr_scapula",
        name="AO Surgery Reference - Scapula Fractures",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/scapula",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.shoulder],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Scapula fracture management and surgical approaches",
        estimated_tokens=6000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_proximal_humerus",
        name="AO Surgery Reference - Proximal Humerus",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-humerus",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.shoulder, BodyRegion.upper_extremity],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Proximal humerus fracture classification, approaches, fixation, pitfalls",
        estimated_tokens=10000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-humerus",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-humerus/approach/all-approaches",
        ],
    ),
    ReferenceSource(
        id="aosr_humeral_shaft",
        name="AO Surgery Reference - Humeral Shaft",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/humeral-shaft",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.upper_extremity],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Humeral shaft fracture management, radial nerve considerations",
        estimated_tokens=8000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_distal_humerus",
        name="AO Surgery Reference - Distal Humerus",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-humerus",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.elbow],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Distal humerus fracture classification, olecranon osteotomy, fixation techniques",
        estimated_tokens=10000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-humerus",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-humerus/approach/all-approaches",
        ],
    ),
    ReferenceSource(
        id="aosr_proximal_forearm",
        name="AO Surgery Reference - Proximal Forearm",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-forearm",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.elbow, BodyRegion.upper_extremity],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Olecranon, radial head, Monteggia fracture management",
        estimated_tokens=8000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_forearm_shaft",
        name="AO Surgery Reference - Forearm Shaft",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/forearm-shaft",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.upper_extremity],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Both-bone forearm fractures, plate fixation, IM nailing",
        estimated_tokens=6000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_distal_forearm",
        name="AO Surgery Reference - Distal Forearm",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-forearm",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.hand_wrist],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Distal radius fracture classification (Colles, Smith, Barton), volar plating, K-wire fixation",
        estimated_tokens=12000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-forearm",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-forearm/approach/all-approaches",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-forearm/preparation/all-preparation",
        ],
    ),
    ReferenceSource(
        id="aosr_hand",
        name="AO Surgery Reference - Hand (Carpals, Metacarpals, Phalanges)",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/carpal-bones",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.hand_wrist],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Scaphoid, metacarpal, phalangeal fractures and fixation",
        estimated_tokens=15000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/carpal-bones",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/metacarpals",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/hand-proximal-phalanges",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/hand-middle-phalanges",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/hand-distal-phalanges",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/thumb",
        ],
    ),

    # -- Lower Extremity --
    ReferenceSource(
        id="aosr_pelvic_ring",
        name="AO Surgery Reference - Pelvic Ring",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/pelvic-ring",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.pelvis],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Pelvic ring injuries, Tile classification, external fixation, ORIF",
        estimated_tokens=10000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_acetabulum",
        name="AO Surgery Reference - Acetabulum",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/acetabulum",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.pelvis, BodyRegion.hip],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Acetabular fracture classification (Judet-Letournel), surgical approaches, fixation",
        estimated_tokens=10000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_proximal_femur",
        name="AO Surgery Reference - Proximal Femur",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-femur",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.hip],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Femoral neck, intertrochanteric, subtrochanteric fractures, DHS, IM nailing, arthroplasty",
        estimated_tokens=12000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-femur",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-femur/approach/all-approaches",
        ],
    ),
    ReferenceSource(
        id="aosr_femoral_shaft",
        name="AO Surgery Reference - Femoral Shaft",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/femoral-shaft",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.lower_extremity],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Femoral shaft fracture, IM nailing, plate fixation",
        estimated_tokens=8000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_distal_femur",
        name="AO Surgery Reference - Distal Femur",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-femur",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.knee],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Distal femur fracture, retrograde nailing, condylar plating",
        estimated_tokens=8000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_patella",
        name="AO Surgery Reference - Patella",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/patella",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.knee],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Patella fracture, tension band wiring, screw fixation",
        estimated_tokens=6000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_proximal_tibia",
        name="AO Surgery Reference - Proximal Tibia",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-tibia",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.knee],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Tibial plateau fracture (Schatzker), ORIF, external fixation",
        estimated_tokens=10000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-tibia",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/proximal-tibia/approach/all-approaches",
        ],
    ),
    ReferenceSource(
        id="aosr_tibial_shaft",
        name="AO Surgery Reference - Tibial Shaft",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/tibial-shaft",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.lower_extremity],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Tibial shaft fracture, IM nailing, plate fixation, external fixation",
        estimated_tokens=8000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_distal_tibia_malleoli",
        name="AO Surgery Reference - Distal Tibia & Malleoli",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-tibia",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.foot_ankle],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.surgical_approach, Topic.classification],
        description="Pilon fracture, malleolar fractures (Weber), syndesmosis, ankle ORIF",
        estimated_tokens=12000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/distal-tibia",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/malleoli",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/malleoli/approach/all-approaches",
        ],
    ),
    ReferenceSource(
        id="aosr_foot",
        name="AO Surgery Reference - Foot (Talus, Calcaneus, Midfoot, Metatarsals)",
        url="https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/talus",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.foot_ankle],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification],
        description="Talus, calcaneus, Lisfranc, metatarsal fracture management",
        estimated_tokens=15000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/talus",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/calcaneous",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/midfoot",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/metatarsals",
            "https://surgeryreference.aofoundation.org/orthopedic-trauma/adult-trauma/foot-phalanges",
        ],
    ),

    # -- Spine (AO Surgery Reference) --
    ReferenceSource(
        id="aosr_spine_cervical",
        name="AO Surgery Reference - Spine: Occipitocervical & Subaxial Cervical",
        url="https://surgeryreference.aofoundation.org/spine/trauma/occipitocervical",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.spine],
        topics=[Topic.spine_surgery, Topic.surgical_technique, Topic.classification, Topic.surgical_approach],
        description="Cervical spine trauma: occipitocervical, subaxial injuries, surgical approaches",
        estimated_tokens=12000,
        priority=2,
        sub_urls=[
            "https://surgeryreference.aofoundation.org/spine/trauma/occipitocervical",
            "https://surgeryreference.aofoundation.org/spine/trauma/subaxial-cervical",
        ],
    ),
    ReferenceSource(
        id="aosr_spine_thoracolumbar",
        name="AO Surgery Reference - Spine: Thoracolumbar",
        url="https://surgeryreference.aofoundation.org/spine/trauma/thoracolumbar",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.spine],
        topics=[Topic.spine_surgery, Topic.surgical_technique, Topic.classification, Topic.surgical_approach],
        description="Thoracolumbar spine trauma, burst fractures, pedicle screw fixation, decompression",
        estimated_tokens=10000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_spine_sacrum",
        name="AO Surgery Reference - Spine: Sacropelvic",
        url="https://surgeryreference.aofoundation.org/spine/trauma/sacrum",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.spine, BodyRegion.pelvis],
        topics=[Topic.spine_surgery, Topic.surgical_technique, Topic.classification],
        description="Sacral fractures, sacropelvic fixation",
        estimated_tokens=6000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_spine_degenerative",
        name="AO Surgery Reference - Spine: Degenerative",
        url="https://surgeryreference.aofoundation.org/spine/degenerative",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.spine],
        topics=[Topic.spine_surgery, Topic.surgical_technique, Topic.pitfalls],
        description="Degenerative spine: stenosis, spondylolisthesis, disc disease, decompression, fusion",
        estimated_tokens=10000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_spine_deformities",
        name="AO Surgery Reference - Spine: Deformities",
        url="https://surgeryreference.aofoundation.org/spine/deformities",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.spine],
        topics=[Topic.spine_surgery, Topic.deformity, Topic.surgical_technique],
        description="Spinal deformity: scoliosis, kyphosis, osteotomy, correction techniques",
        estimated_tokens=8000,
        priority=2,
    ),
    ReferenceSource(
        id="aosr_spine_tumors",
        name="AO Surgery Reference - Spine: Tumors",
        url="https://surgeryreference.aofoundation.org/spine/tumors",
        source_type=SourceType.html,
        license="AO Foundation (free open access)",
        regions=[BodyRegion.spine],
        topics=[Topic.spine_surgery, Topic.surgical_technique],
        description="Spinal tumor management, en bloc resection, stabilization",
        estimated_tokens=6000,
        priority=2,
    ),

    # -- AO Nonoperative Handbook (PDF) --
    ReferenceSource(
        id="ao_nonoperative_handbook",
        name="AO Handbook - Nonoperative Fracture Treatment",
        url="https://online.ao-alliance.org/images/PDF/ao-alliance-handbook-nonoperative-fracture-treatment-complete.pdf",
        source_type=SourceType.pdf,
        license="AO Alliance (free open access)",
        regions=[BodyRegion.general, BodyRegion.upper_extremity, BodyRegion.lower_extremity],
        topics=[Topic.fracture_management, Topic.classification, Topic.pitfalls],
        description="Complete guide to nonoperative fracture management: casting, splinting, reduction techniques",
        estimated_tokens=40000,
        priority=2,
    ),

    # -------------------------------------------------------------------------
    # Tier 3: Comprehensive PDFs (loaded selectively)
    # -------------------------------------------------------------------------
    ReferenceSource(
        id="wfns_lumbar_disc",
        name="WFNS Textbook — Surgical Management of Lumbar Disc Herniation",
        url="https://www.suffolkandessexspine.co.uk/wp-content/uploads/2024/08/Textbook-of-Surgical-Management-of-Lumbar-Disc-Herniation.pdf",
        source_type=SourceType.pdf,
        license="WFNS Spine Committee (educational)",
        regions=[BodyRegion.spine],
        topics=[Topic.spine_surgery, Topic.surgical_technique, Topic.pitfalls],
        description="Comprehensive lumbar disc herniation surgical management",
        estimated_tokens=40000,
        priority=3,
    ),
    ReferenceSource(
        id="utoledo_trauma_review",
        name="U. Toledo Orthopaedic Trauma Review",
        url="https://www.utoledo.edu/med/depts/ortho/pdfs/Orthopaedic%20Trauma%20Review%20for%20Medical%20Students%20with%20watermark%20all.pdf",
        source_type=SourceType.pdf,
        license="Educational (University of Toledo)",
        regions=[BodyRegion.general, BodyRegion.upper_extremity, BodyRegion.lower_extremity],
        topics=[Topic.fracture_management, Topic.classification, Topic.surgical_approach],
        description="Bone healing, fracture classification, open fractures, comprehensive trauma review",
        estimated_tokens=30000,
        priority=3,
    ),
    ReferenceSource(
        id="clinical_anatomy_upper_ext",
        name="Clinical Anatomy of the Upper Extremity",
        url="https://anatomiaomului.usmf.md/sites/default/files/inline-files/0957d3b7_upper_extremity.pdf",
        source_type=SourceType.pdf,
        license="Educational",
        regions=[BodyRegion.upper_extremity, BodyRegion.shoulder, BodyRegion.elbow, BodyRegion.hand_wrist],
        topics=[Topic.anatomy, Topic.nerves_vessels, Topic.surgical_approach],
        description="Detailed upper extremity anatomy: nerves, muscles, danger zones for surgical approaches",
        estimated_tokens=25000,
        priority=3,
    ),
    ReferenceSource(
        id="ortho_lecture_notes",
        name="Orthopaedics & Fractures Lecture Notes (5th Year)",
        url="https://doctor2020.jumedicine.com/wp-content/uploads/sites/12/2024/07/ORTHOPAEDICS-AND-TRAUMA-LECTURES.pdf",
        source_type=SourceType.pdf,
        license="Educational",
        regions=[BodyRegion.general, BodyRegion.upper_extremity, BodyRegion.lower_extremity, BodyRegion.spine],
        topics=[Topic.fracture_management, Topic.surgical_technique, Topic.classification, Topic.deformity],
        description="Comprehensive orthopedic lecture notes covering all body regions",
        estimated_tokens=35000,
        priority=3,
    ),
    ReferenceSource(
        id="fracture_healing_fixation_2024",
        name="Principles of Fracture Healing and Fixation (PMC 2024)",
        url="https://pmc.ncbi.nlm.nih.gov/articles/PMC11665253/",
        source_type=SourceType.html,
        license="CC-BY 4.0",
        regions=[BodyRegion.general],
        topics=[Topic.fracture_management, Topic.implants, Topic.biomechanics],
        description="Fixation plates (compression, locking, buttress, bridge), healing biology, 2024 review",
        estimated_tokens=10000,
        priority=3,
    ),
    ReferenceSource(
        id="global_help_pediatric",
        name="Textbook of Pediatric Orthopaedics (Global HELP)",
        url="https://global-help.org/products/textbook_of_pediatric_orthopaedics/",
        source_type=SourceType.pdf,
        license="Free (Global HELP / Elsevier reprint)",
        regions=[BodyRegion.pediatric, BodyRegion.general],
        topics=[Topic.pediatric, Topic.deformity, Topic.fracture_management],
        description="Complete pediatric orthopaedics: congenital deformities, fractures, growth plate injuries",
        estimated_tokens=50000,
        priority=4,
    ),

    # -------------------------------------------------------------------------
    # Tier 4: Online databases (scraped selectively by topic)
    # -------------------------------------------------------------------------
    ReferenceSource(
        id="wheeless_online",
        name="Wheeless' Textbook of Orthopaedics",
        url="https://www.wheelessonline.com/",
        source_type=SourceType.html,
        license="Free online (Duke University / Data Trace)",
        regions=[r for r in BodyRegion],
        topics=[t for t in Topic],
        description="11,000 pages covering all orthopedic topics. Scrape selectively by region.",
        estimated_tokens=100000,
        priority=4,
        sub_urls=[
            "https://www.wheelessonline.com/trauma-fractures/trauma-and-fractures-menu/",
        ],
    ),
]


def get_sources_for_region(region: BodyRegion) -> list[ReferenceSource]:
    """Get all sources relevant to a body region, sorted by priority."""
    matches = [
        s for s in SOURCES
        if region in s.regions or BodyRegion.general in s.regions
    ]
    return sorted(matches, key=lambda s: s.priority)


def get_sources_for_topic(topic: Topic) -> list[ReferenceSource]:
    """Get all sources relevant to a topic, sorted by priority."""
    matches = [s for s in SOURCES if topic in s.topics]
    return sorted(matches, key=lambda s: s.priority)


def get_sources_by_priority(max_priority: int = 3) -> list[ReferenceSource]:
    """Get all sources up to a given priority level."""
    return sorted(
        [s for s in SOURCES if s.priority <= max_priority],
        key=lambda s: s.priority,
    )


# Map AO bone codes to body regions
AO_REGION_MAP: dict[str, BodyRegion] = {
    "1": BodyRegion.shoulder,       # Humerus proximal
    "11": BodyRegion.shoulder,
    "12": BodyRegion.upper_extremity,  # Humerus shaft
    "13": BodyRegion.elbow,         # Humerus distal
    "2": BodyRegion.upper_extremity,  # Radius/Ulna
    "21": BodyRegion.elbow,         # Proximal forearm
    "22": BodyRegion.upper_extremity,  # Forearm shaft
    "23": BodyRegion.hand_wrist,    # Distal radius
    "3": BodyRegion.lower_extremity,  # Femur
    "31": BodyRegion.hip,           # Proximal femur
    "32": BodyRegion.lower_extremity,  # Femur shaft
    "33": BodyRegion.knee,          # Distal femur
    "4": BodyRegion.lower_extremity,  # Tibia
    "41": BodyRegion.knee,          # Proximal tibia
    "42": BodyRegion.lower_extremity,  # Tibia shaft
    "43": BodyRegion.foot_ankle,    # Distal tibia
    "44": BodyRegion.foot_ankle,    # Malleolar
    "5": BodyRegion.spine,          # Spine
    "6": BodyRegion.pelvis,         # Pelvis
    "7": BodyRegion.hand_wrist,     # Hand
    "8": BodyRegion.foot_ankle,     # Foot
    "9": BodyRegion.pediatric,      # Pediatric (special)
}


def region_from_ao_code(ao_code: str) -> BodyRegion:
    """Map an AO classification code to a body region."""
    # Try progressively shorter prefixes
    for length in [2, 1]:
        prefix = ao_code[:length]
        if prefix in AO_REGION_MAP:
            return AO_REGION_MAP[prefix]
    return BodyRegion.general
