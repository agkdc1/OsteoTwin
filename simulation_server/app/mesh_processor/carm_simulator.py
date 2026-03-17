"""C-arm Physical Simulator — collision detection and feasibility analysis.

Models the C-arm as a semicircular arc and checks whether a given
orbital/angular pose is physically achievable without colliding with
the OR bed, rails, or patient body.

The arc is discretized into sample points along its curve.
For each pose, these points are transformed into world space and
checked against the bed bounding box and patient bounding ellipsoid.

Also generates 3D trimesh scenes of the OR setup (bed, patient, C-arm)
for 6-view rendering and Gemini validation.
"""

from __future__ import annotations

import io
import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np
import trimesh

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))
from shared.carm_schemas import (
    CARM_SPECS,
    CarmModel,
    CarmPose,
    CarmSpec,
    CollisionType,
    FeasibilityResult,
    CarmFeasibilityMap,
    ORBedSpec,
    PatientModel,
    PatientPosition,
)

logger = logging.getLogger("osteotwin.carm_sim")

# Number of sample points along the C-arm arc for collision checking
ARC_SAMPLES = 36


# ---------------------------------------------------------------------------
# Arc geometry: generate sample points along the C-arm curve
# ---------------------------------------------------------------------------

def _arc_points_local(spec: CarmSpec, n_samples: int = ARC_SAMPLES) -> np.ndarray:
    """Generate points along the C-arm arc in local coordinates.

    The arc is a semicircle in the XY plane centered at origin.
    At angle 0 (AP): source is at Y+, detector at Y-.
    Arc spans from source side to detector side.

    Returns: (n_samples, 3) array of points in local frame.
    """
    # Arc spans ~180 degrees (source to detector)
    angles = np.linspace(-math.pi / 2, math.pi / 2, n_samples)
    r = spec.arc_radius_mm

    points = np.zeros((n_samples, 3))
    points[:, 0] = 0  # arc is in YZ plane locally
    points[:, 1] = r * np.cos(angles)  # Y: anterior-posterior
    points[:, 2] = 0  # initially flat, rotation adds Z component

    # Also add the source and detector positions
    source = np.array([[0, spec.source_to_isocenter_mm, 0]])
    detector = np.array([[0, -spec.detector_to_isocenter_mm, 0]])

    return np.vstack([points, source, detector])


def _transform_arc(
    points: np.ndarray,
    pose: CarmPose,
) -> np.ndarray:
    """Transform arc points from local frame to world (LPS) frame.

    Applies orbital rotation (around Z) and angular tilt (around X),
    then translates to isocenter.
    """
    orb = math.radians(pose.orbital_deg)
    ang = math.radians(pose.angular_deg)

    # Rotation around Z (orbital)
    Rz = np.array([
        [math.cos(orb), -math.sin(orb), 0],
        [math.sin(orb), math.cos(orb), 0],
        [0, 0, 1],
    ])

    # Rotation around X (angular tilt)
    Rx = np.array([
        [1, 0, 0],
        [0, math.cos(ang), -math.sin(ang)],
        [0, math.sin(ang), math.cos(ang)],
    ])

    R = Rz @ Rx
    iso = np.array(pose.isocenter_lps)

    return (R @ points.T).T + iso


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------

def _check_bed_collision(
    world_points: np.ndarray,
    bed: ORBedSpec,
) -> tuple[bool, float]:
    """Check if any arc points collide with the OR bed bounding box.

    Returns (collides, min_clearance_mm).
    """
    bed_center = np.array(bed.bed_center_lps)

    # Bed top surface is at bed_center.y + mattress_thickness/2
    bed_top_y = bed_center[1] + bed.mattress_thickness_mm / 2
    bed_bottom_y = bed_center[1] - bed.mattress_thickness_mm / 2 - 50  # bed frame below

    min_clearance = float("inf")
    collides = False

    for pt in world_points:
        # Check if point is within bed footprint (X and Z)
        in_x = abs(pt[0] - bed_center[0]) < (bed.half_width + bed.rail_width_mm)
        in_z = abs(pt[2] - bed_center[2]) < bed.half_length

        if in_x and in_z:
            # Check Y clearance (point must be above bed surface or well below)
            clearance_top = pt[1] - bed_top_y
            clearance_bottom = bed_bottom_y - pt[1]

            if clearance_top < 0 and clearance_bottom < 0:
                # Point is inside the bed volume
                collides = True
                min_clearance = min(min_clearance, max(clearance_top, clearance_bottom))
            else:
                min_clearance = min(min_clearance, abs(clearance_top))

        # Check rails
        if in_z and bed.rail_height_mm > 0:
            rail_inner = bed.half_width
            rail_outer = bed.half_width + bed.rail_width_mm
            rail_top = bed_top_y + bed.rail_height_mm

            for side in [1, -1]:  # left and right rails
                rail_x = bed_center[0] + side * (rail_inner + rail_outer) / 2
                if abs(pt[0] - rail_x) < bed.rail_width_mm / 2:
                    if bed_top_y < pt[1] < rail_top:
                        collides = True
                        min_clearance = 0

    return collides, min_clearance if min_clearance != float("inf") else None


def _check_patient_collision(
    world_points: np.ndarray,
    patient: PatientModel,
    bed: ORBedSpec,
) -> tuple[bool, float]:
    """Check if arc points collide with the patient bounding ellipsoid."""
    bed_center = np.array(bed.bed_center_lps)
    bed_top_y = bed_center[1] + bed.mattress_thickness_mm / 2

    # Patient ellipsoid center (on top of bed)
    px = bed_center[0] + patient.offset_x_mm
    py = bed_top_y + patient.body_depth_mm / 2  # center of body above bed
    pz = bed_center[2] + patient.offset_z_mm

    # Ellipsoid semi-axes
    ax = patient.body_width_mm / 2
    ay = patient.body_depth_mm / 2
    az = patient.body_length_mm / 2

    min_clearance = float("inf")
    collides = False

    for pt in world_points:
        # Normalized distance to ellipsoid
        dx = (pt[0] - px) / ax if ax > 0 else 0
        dy = (pt[1] - py) / ay if ay > 0 else 0
        dz = (pt[2] - pz) / az if az > 0 else 0
        dist_normalized = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)

        if dist_normalized < 1.0:
            collides = True
            min_clearance = 0
        else:
            # Approximate real-space clearance
            clearance = (dist_normalized - 1.0) * min(ax, ay, az)
            min_clearance = min(min_clearance, clearance)

    return collides, min_clearance if min_clearance != float("inf") else None


def check_feasibility(
    carm: CarmSpec,
    pose: CarmPose,
    bed: ORBedSpec,
    patient: PatientModel,
) -> FeasibilityResult:
    """Check if a C-arm pose is physically achievable."""
    collisions = []
    notes = []

    # Check orbital range
    if pose.orbital_deg < carm.orbital_range_deg[0] or pose.orbital_deg > carm.orbital_range_deg[1]:
        collisions.append(CollisionType.OUT_OF_RANGE)
        notes.append(f"Orbital {pose.orbital_deg} deg outside range {carm.orbital_range_deg}")

    # Check angular range
    if pose.angular_deg < carm.angular_range_deg[0] or pose.angular_deg > carm.angular_range_deg[1]:
        collisions.append(CollisionType.OUT_OF_RANGE)
        notes.append(f"Angular {pose.angular_deg} deg outside range {carm.angular_range_deg}")

    # Generate arc points and transform
    local_pts = _arc_points_local(carm)
    world_pts = _transform_arc(local_pts, pose)

    # Check bed collision
    bed_collides, bed_clearance = _check_bed_collision(world_pts, bed)
    if bed_collides:
        collisions.append(CollisionType.ARC_BED)
        notes.append("C-arm arc collides with OR bed")

    # Check patient collision
    patient_collides, patient_clearance = _check_patient_collision(world_pts, patient, bed)
    if patient_collides:
        collisions.append(CollisionType.ARC_PATIENT)
        notes.append("C-arm arc collides with patient body")

    min_clearance = None
    clearances = [c for c in [bed_clearance, patient_clearance] if c is not None]
    if clearances:
        min_clearance = min(clearances)

    return FeasibilityResult(
        feasible=len(collisions) == 0,
        orbital_deg=pose.orbital_deg,
        angular_deg=pose.angular_deg,
        collisions=collisions,
        min_clearance_mm=round(min_clearance, 1) if min_clearance is not None else None,
        notes=notes,
        beam_direction=pose.source_direction,
    )


def compute_feasibility_map(
    carm: CarmSpec,
    bed: ORBedSpec,
    patient: PatientModel,
    isocenter_lps: tuple[float, float, float] = (0, 0, 0),
    orbital_step: float = 5.0,
    angular_step: float = 5.0,
) -> CarmFeasibilityMap:
    """Compute full feasibility map across all orbital/angular combinations."""
    orb_min, orb_max = carm.orbital_range_deg
    ang_min, ang_max = carm.angular_range_deg

    results = []
    feasible_count = 0
    blocked_count = 0

    orb = orb_min
    while orb <= orb_max:
        ang = ang_min
        while ang <= ang_max:
            pose = CarmPose(orbital_deg=orb, angular_deg=ang, isocenter_lps=isocenter_lps)
            result = check_feasibility(carm, pose, bed, patient)
            results.append(result)
            if result.feasible:
                feasible_count += 1
            else:
                blocked_count += 1
            ang += angular_step
        orb += orbital_step

    total = feasible_count + blocked_count

    return CarmFeasibilityMap(
        carm_model=carm.name,
        bed_type=bed.name,
        patient_position=patient.position.value,
        orbital_range_tested=(orb_min, orb_max),
        angular_range_tested=(ang_min, ang_max),
        step_deg=orbital_step,
        total_poses_tested=total,
        feasible_poses=feasible_count,
        blocked_poses=blocked_count,
        feasibility_pct=round(feasible_count / max(total, 1) * 100, 1),
        results=results,
    )


# ---------------------------------------------------------------------------
# 3D Scene Generation (for rendering and Gemini validation)
# ---------------------------------------------------------------------------

def generate_or_scene(
    carm: CarmSpec,
    pose: CarmPose,
    bed: ORBedSpec,
    patient: PatientModel,
) -> trimesh.Scene:
    """Generate a 3D trimesh Scene of the OR setup.

    Includes: bed (gray), patient (skin tone), C-arm arc (blue),
    X-ray source (red cone), detector (green rectangle).
    """
    scene = trimesh.Scene()
    bed_center = np.array(bed.bed_center_lps)
    bed_top_y = bed_center[1] + bed.mattress_thickness_mm / 2

    # --- Bed ---
    bed_mesh = trimesh.creation.box(
        extents=[bed.width_mm, bed.mattress_thickness_mm, bed.length_mm]
    )
    bed_mesh.apply_translation([bed_center[0], bed_center[1], bed_center[2]])
    bed_mesh.visual.face_colors = [180, 180, 190, 200]
    scene.add_geometry(bed_mesh, node_name="bed")

    # Bed rails
    if bed.rail_height_mm > 0:
        for side in [1, -1]:
            rail = trimesh.creation.box(
                extents=[bed.rail_width_mm, bed.rail_height_mm, bed.length_mm * 0.6]
            )
            rail.apply_translation([
                bed_center[0] + side * (bed.half_width + bed.rail_width_mm / 2),
                bed_top_y + bed.rail_height_mm / 2,
                bed_center[2],
            ])
            rail.visual.face_colors = [150, 150, 160, 200]
            scene.add_geometry(rail, node_name=f"rail_{'L' if side > 0 else 'R'}")

    # --- Patient (ellipsoid approximation) ---
    patient_sphere = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    patient_sphere.apply_scale([
        patient.body_width_mm / 2,
        patient.body_depth_mm / 2,
        patient.body_length_mm / 2,
    ])
    patient_sphere.apply_translation([
        bed_center[0] + patient.offset_x_mm,
        bed_top_y + patient.body_depth_mm / 2,
        bed_center[2] + patient.offset_z_mm,
    ])
    patient_sphere.visual.face_colors = [220, 185, 155, 180]  # skin tone
    scene.add_geometry(patient_sphere, node_name="patient")

    # --- C-arm arc ---
    # Generate arc as a tube following the semicircular path
    arc_angles = np.linspace(-math.pi * 0.45, math.pi * 0.45, 60)
    arc_path = np.zeros((60, 3))
    arc_path[:, 1] = carm.arc_radius_mm * np.cos(arc_angles)
    arc_path[:, 0] = 0
    arc_path[:, 2] = 0  # flat initially, rotation handles orientation

    # Transform arc to world pose
    orb = math.radians(pose.orbital_deg)
    ang = math.radians(pose.angular_deg)
    Rz = np.array([
        [math.cos(orb), -math.sin(orb), 0],
        [math.sin(orb), math.cos(orb), 0],
        [0, 0, 1],
    ])
    Rx = np.array([
        [1, 0, 0],
        [0, math.cos(ang), -math.sin(ang)],
        [0, math.sin(ang), math.cos(ang)],
    ])
    R = Rz @ Rx
    iso = np.array(pose.isocenter_lps)

    world_arc = (R @ arc_path.T).T + iso

    # Create tube along arc path
    try:
        arc_tube = trimesh.creation.sweep_section(
            trimesh.path.entities.Line(
                points=list(range(len(world_arc)))
            ).discrete(world_arc),
            section=trimesh.creation.annulus(r_min=0, r_max=carm.arc_thickness_mm / 2, height=0.1),
        )
    except Exception:
        # Fallback: use individual spheres along arc
        arc_parts = []
        for pt in world_arc[::3]:
            s = trimesh.creation.icosphere(subdivisions=1, radius=carm.arc_thickness_mm / 2)
            s.apply_translation(pt)
            arc_parts.append(s)
        if arc_parts:
            arc_tube = trimesh.util.concatenate(arc_parts)
        else:
            arc_tube = trimesh.creation.icosphere(radius=10)

    arc_tube.visual.face_colors = [60, 120, 200, 200]  # blue
    scene.add_geometry(arc_tube, node_name="carm_arc")

    # --- X-ray source (red sphere at source position) ---
    source_local = np.array([0, carm.source_to_isocenter_mm, 0])
    source_world = R @ source_local + iso
    source_mesh = trimesh.creation.icosphere(subdivisions=2, radius=30)
    source_mesh.apply_translation(source_world)
    source_mesh.visual.face_colors = [220, 60, 60, 220]  # red
    scene.add_geometry(source_mesh, node_name="xray_source")

    # --- Detector (green box at detector position) ---
    det_local = np.array([0, -carm.detector_to_isocenter_mm, 0])
    det_world = R @ det_local + iso
    det_mesh = trimesh.creation.box(extents=[
        carm.detector_size_mm[0], 20, carm.detector_size_mm[1]
    ])
    det_mesh.apply_translation(det_world)
    det_mesh.visual.face_colors = [60, 200, 60, 220]  # green
    scene.add_geometry(det_mesh, node_name="detector")

    return scene


def render_or_scene_6view(
    scene: trimesh.Scene,
    output_dir: Path,
    prefix: str = "or_scene",
    image_size: tuple[int, int] = (512, 512),
) -> Optional[Path]:
    """Render the OR scene from 6 orthographic views and stitch into 2x3 grid.

    Returns path to stitched image, or None if rendering fails.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed, cannot render 6-view")
        return None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 6 camera angles: (rotation_matrix, name)
    views = [
        ("top", [0, 0, 1], [0, 1, 0]),       # looking down
        ("bottom", [0, 0, -1], [0, 1, 0]),    # looking up
        ("front", [0, -1, 0], [0, 0, 1]),     # anterior view
        ("back", [0, 1, 0], [0, 0, 1]),       # posterior view
        ("left", [1, 0, 0], [0, 0, 1]),       # left lateral
        ("right", [-1, 0, 0], [0, 0, 1]),     # right lateral
    ]

    render_paths = []
    for view_name, direction, up in views:
        try:
            # Use trimesh scene rendering
            png_data = scene.save_image(resolution=image_size, visible=True)
            if png_data:
                view_path = output_dir / f"{prefix}_{view_name}.png"
                with open(view_path, "wb") as f:
                    f.write(png_data)
                render_paths.append(view_path)
        except Exception as exc:
            logger.debug("Scene render failed for %s: %s", view_name, exc)

    if not render_paths:
        # Fallback: export scene as GLB for manual viewing
        glb_path = output_dir / f"{prefix}.glb"
        scene.export(str(glb_path))
        logger.info("Exported OR scene as GLB: %s", glb_path)
        return glb_path

    # Stitch into 2x3 grid
    stitched_path = output_dir / f"{prefix}_6view.png"
    images = [Image.open(p) for p in render_paths[:6]]
    w, h = images[0].size
    grid = Image.new("RGB", (w * 3, h * 2), (30, 30, 30))
    labels = ["Top", "Bottom", "Front", "Back", "Left", "Right"]
    for idx, img in enumerate(images):
        col, row = idx % 3, idx // 3
        grid.paste(img, (col * w, row * h))

    grid.save(stitched_path)
    logger.info("OR scene 6-view stitched: %s", stitched_path)
    return stitched_path
