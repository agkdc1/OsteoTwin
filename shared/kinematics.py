"""Kinematics utilities — clinical terms ↔ LPS math.

Converts anatomical movements (valgus, flexion, proximal, etc.) into
concrete LPS translation vectors and rotation matrices.

All functions are pure and deterministic — no LLM calls, no side effects.
"""

from __future__ import annotations

import math
from typing import Optional

from shared.schemas import (
    DIRECTION_LPS_MAP,
    ActionType,
    AnatomicalDirection,
    LPSRotation,
    LPSVector,
    SemanticMovement,
    SurgicalAction,
)
from shared.simulation_protocol import (
    RotationMatrix,
    SimActionRequest,
    TranslationVector,
)


# ---------------------------------------------------------------------------
# Core resolvers: clinical movement → LPS vector / rotation
# ---------------------------------------------------------------------------


def resolve_movement(movement: SemanticMovement) -> tuple[LPSVector, LPSRotation]:
    """Resolve a single SemanticMovement into LPS translation + rotation.

    Handles the left/right sign flip for medial/lateral directions:
    - Right side: medial = +X, lateral = -X
    - Left side:  medial = -X, lateral = +X

    Returns (translation_mm, rotation_deg) — one will be zero-valued.
    """
    axis, sign, is_rotation = DIRECTION_LPS_MAP[movement.direction]

    # Flip medial/lateral for left-side bones
    if movement.side == "L" and movement.direction in (
        AnatomicalDirection.MEDIAL,
        AnatomicalDirection.LATERAL,
    ):
        sign = -sign

    # Flip varus/valgus for left-side bones (mirror plane)
    if movement.side == "L" and movement.direction in (
        AnatomicalDirection.VARUS,
        AnatomicalDirection.VALGUS,
    ):
        sign = -sign

    # Flip internal/external rotation for left-side bones
    if movement.side == "L" and movement.direction in (
        AnatomicalDirection.INTERNAL_ROTATION,
        AnatomicalDirection.EXTERNAL_ROTATION,
    ):
        sign = -sign

    value = sign * movement.magnitude

    translation = LPSVector()
    rotation = LPSRotation()

    if is_rotation:
        if axis == "x":
            rotation.x_deg = value
        elif axis == "y":
            rotation.y_deg = value
        else:
            rotation.z_deg = value
    else:
        if axis == "x":
            translation.x = value
        elif axis == "y":
            translation.y = value
        else:
            translation.z = value

    return translation, rotation


def resolve_movements(
    movements: list[SemanticMovement],
) -> tuple[LPSVector, LPSRotation]:
    """Resolve a list of SemanticMovements into net translation + rotation.

    Translations are summed. Rotations are summed (small-angle approximation,
    valid for typical surgical corrections < 30°).
    """
    net_t = LPSVector()
    net_r = LPSRotation()

    for m in movements:
        t, r = resolve_movement(m)
        net_t.x += t.x
        net_t.y += t.y
        net_t.z += t.z
        net_r.x_deg += r.x_deg
        net_r.y_deg += r.y_deg
        net_r.z_deg += r.z_deg

    return net_t, net_r


# ---------------------------------------------------------------------------
# Euler angles → 3×3 rotation matrix
# ---------------------------------------------------------------------------


def euler_to_rotation_matrix(
    x_deg: float = 0.0,
    y_deg: float = 0.0,
    z_deg: float = 0.0,
) -> RotationMatrix:
    """Convert extrinsic XYZ Euler angles (degrees) to a 3×3 rotation matrix.

    Rotation order: R = Rz · Ry · Rx  (extrinsic XYZ = intrinsic ZYX).
    """
    ax = math.radians(x_deg)
    ay = math.radians(y_deg)
    az = math.radians(z_deg)

    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)

    return RotationMatrix(
        r00=cy * cz,
        r01=sx * sy * cz - cx * sz,
        r02=cx * sy * cz + sx * sz,
        r10=cy * sz,
        r11=sx * sy * sz + cx * cz,
        r12=cx * sy * sz - sx * cz,
        r20=-sy,
        r21=sx * cy,
        r22=cx * cy,
    )


def rotation_matrix_to_euler(rm: RotationMatrix) -> LPSRotation:
    """Extract extrinsic XYZ Euler angles from a 3×3 rotation matrix.

    Assumes no gimbal lock (|r20| < 1).
    """
    if abs(rm.r20) < 1.0 - 1e-6:
        y = math.asin(-rm.r20)
        x = math.atan2(rm.r21, rm.r22)
        z = math.atan2(rm.r10, rm.r00)
    else:
        # Gimbal lock
        y = math.copysign(math.pi / 2, -rm.r20)
        x = math.atan2(-rm.r12, rm.r11)
        z = 0.0

    return LPSRotation(
        x_deg=math.degrees(x),
        y_deg=math.degrees(y),
        z_deg=math.degrees(z),
    )


# ---------------------------------------------------------------------------
# Convenience: named clinical rotations → rotation matrix
# ---------------------------------------------------------------------------


def valgus_to_rotation_matrix(bone_side: str, degrees: float) -> RotationMatrix:
    """Convert valgus angulation to a rotation matrix.

    Valgus = rotation around the A-P (Y) axis.
    Sign depends on side: right leg valgus is -Y rotation.
    """
    m = SemanticMovement(
        direction=AnatomicalDirection.VALGUS,
        magnitude=degrees,
        side=bone_side,
    )
    _, rot = resolve_movement(m)
    return euler_to_rotation_matrix(rot.x_deg, rot.y_deg, rot.z_deg)


def varus_to_rotation_matrix(bone_side: str, degrees: float) -> RotationMatrix:
    """Convert varus angulation to a rotation matrix."""
    m = SemanticMovement(
        direction=AnatomicalDirection.VARUS,
        magnitude=degrees,
        side=bone_side,
    )
    _, rot = resolve_movement(m)
    return euler_to_rotation_matrix(rot.x_deg, rot.y_deg, rot.z_deg)


def flexion_to_rotation_matrix(bone_side: str, degrees: float) -> RotationMatrix:
    """Convert flexion to a rotation matrix (rotation around L-R / X axis)."""
    m = SemanticMovement(
        direction=AnatomicalDirection.FLEXION,
        magnitude=degrees,
        side=bone_side,
    )
    _, rot = resolve_movement(m)
    return euler_to_rotation_matrix(rot.x_deg, rot.y_deg, rot.z_deg)


def internal_rotation_to_matrix(bone_side: str, degrees: float) -> RotationMatrix:
    """Convert internal rotation to a rotation matrix (around S-I / Z axis)."""
    m = SemanticMovement(
        direction=AnatomicalDirection.INTERNAL_ROTATION,
        magnitude=degrees,
        side=bone_side,
    )
    _, rot = resolve_movement(m)
    return euler_to_rotation_matrix(rot.x_deg, rot.y_deg, rot.z_deg)


# ---------------------------------------------------------------------------
# SurgicalAction → SimActionRequest bridge
# ---------------------------------------------------------------------------


def surgical_action_to_sim_request(
    action: SurgicalAction,
    case_id: Optional[str] = None,
) -> SimActionRequest:
    """Convert a SurgicalAction into a SimActionRequest for the Simulation Server.

    If the action has unresolved semantic movements, resolves them first
    and populates translation_mm / rotation_deg on the action.
    """
    # Auto-resolve if movements present but translation/rotation are zero
    if action.movements and _is_zero(action.translation_mm) and _is_zero_rot(action.rotation_deg):
        t, r = resolve_movements(action.movements)
        action.translation_mm = t
        action.rotation_deg = r

    rotation = euler_to_rotation_matrix(
        action.rotation_deg.x_deg,
        action.rotation_deg.y_deg,
        action.rotation_deg.z_deg,
    )

    req = SimActionRequest(
        case_id=case_id or action.case_id or "",
        branch=action.branch,
        fragment_id=action.target.fragment_id,
        translation=TranslationVector(
            x=action.translation_mm.x,
            y=action.translation_mm.y,
            z=action.translation_mm.z,
        ),
        rotation=rotation,
    )

    # Hardware passthrough
    if action.hardware_id:
        req.place_hardware = action.hardware_id
    if action.hardware_position:
        req.hardware_position = TranslationVector(
            x=action.hardware_position.x,
            y=action.hardware_position.y,
            z=action.hardware_position.z,
        )
    if action.hardware_orientation:
        rm = euler_to_rotation_matrix(
            action.hardware_orientation.x_deg,
            action.hardware_orientation.y_deg,
            action.hardware_orientation.z_deg,
        )
        req.hardware_orientation = rm

    return req


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_zero(v: LPSVector) -> bool:
    return v.x == 0.0 and v.y == 0.0 and v.z == 0.0


def _is_zero_rot(r: LPSRotation) -> bool:
    return r.x_deg == 0.0 and r.y_deg == 0.0 and r.z_deg == 0.0
