/**
 * Coordinate Mapper: Three.js (Y-up) ↔ LPS/DICOM (Z-up)
 *
 * Three.js uses a RIGHT-HANDED Y-UP system:
 *   X+ = Right,  Y+ = Up,    Z+ = Toward camera (anterior)
 *
 * LPS (DICOM) uses a RIGHT-HANDED Z-UP system:
 *   X+ = Left,   Y+ = Posterior,  Z+ = Superior
 *
 * Conversion:
 *   LPS.x = -THREE.x   (Three +X is Right, LPS +X is Left)
 *   LPS.y = -THREE.z   (Three +Z is Anterior, LPS +Y is Posterior)
 *   LPS.z =  THREE.y   (Three +Y is Up, LPS +Z is Superior)
 *
 * Inverse (LPS → Three.js):
 *   THREE.x = -LPS.x
 *   THREE.y =  LPS.z
 *   THREE.z = -LPS.y
 */

// --- Types matching backend shared/schemas ---

export interface LPSVector {
  x: number; // Left(+) / Right(-)
  y: number; // Posterior(+) / Anterior(-)
  z: number; // Superior(+) / Inferior(-)
}

export interface LPSRotation {
  x_deg: number; // around L-R axis (flexion/extension)
  y_deg: number; // around A-P axis (varus/valgus)
  z_deg: number; // around S-I axis (int/ext rotation)
}

export interface ThreePosition {
  x: number;
  y: number;
  z: number;
}

export interface ThreeEuler {
  x: number; // radians
  y: number;
  z: number;
  order: string; // typically 'XYZ'
}

// --- Position conversion ---

export function threeToLPS(pos: ThreePosition): LPSVector {
  return {
    x: -pos.x,
    y: -pos.z,
    z: pos.y,
  };
}

export function lpsToThree(lps: LPSVector): ThreePosition {
  return {
    x: -lps.x,
    y: lps.z,
    z: -lps.y,
  };
}

// --- Delta calculation ---

export function computeTranslationDelta(
  prevThree: ThreePosition,
  currThree: ThreePosition,
): LPSVector {
  const delta: ThreePosition = {
    x: currThree.x - prevThree.x,
    y: currThree.y - prevThree.y,
    z: currThree.z - prevThree.z,
  };
  return threeToLPS(delta);
}

/**
 * Compute rotation delta in LPS Euler degrees.
 *
 * Three.js Euler angles (radians, XYZ order) are converted to LPS
 * Euler angles (degrees) using the same axis remapping as positions.
 *
 * For small rotations (typical surgical corrections < 30°), Euler
 * subtraction is a valid approximation.
 */
export function computeRotationDelta(
  prevEuler: ThreeEuler,
  currEuler: ThreeEuler,
): LPSRotation {
  const RAD2DEG = 180 / Math.PI;

  // Delta in Three.js space (radians)
  const dx = currEuler.x - prevEuler.x;
  const dy = currEuler.y - prevEuler.y;
  const dz = currEuler.z - prevEuler.z;

  // Remap axes: same convention as position
  // LPS rot_x (around L-R) ← Three rot_x but sign-flipped
  // LPS rot_y (around A-P) ← Three rot_z but sign-flipped
  // LPS rot_z (around S-I) ← Three rot_y
  return {
    x_deg: -dx * RAD2DEG,
    y_deg: -dz * RAD2DEG,
    z_deg: dy * RAD2DEG,
  };
}

// --- SurgicalAction builder ---

export interface FragmentRef {
  fragment_id: string;
  color_code: string;
  volume_mm3: number;
}

export interface SurgicalActionPayload {
  action_type: string;
  target: FragmentRef;
  clinical_intent: string;
  translation_mm: LPSVector;
  rotation_deg: LPSRotation;
  case_id: string;
  branch: string;
  source_agent: string;
}

/**
 * Build a SurgicalAction JSON payload from a Three.js drag delta.
 *
 * Call this in the TransformControls `mouseUp` handler after computing
 * the position/rotation delta.
 */
export function buildDragAction(
  fragment: FragmentRef,
  translationDelta: LPSVector,
  rotationDelta: LPSRotation,
  caseId: string,
): SurgicalActionPayload {
  const hasTrans = Math.abs(translationDelta.x) > 0.01
    || Math.abs(translationDelta.y) > 0.01
    || Math.abs(translationDelta.z) > 0.01;
  const hasRot = Math.abs(rotationDelta.x_deg) > 0.1
    || Math.abs(rotationDelta.y_deg) > 0.1
    || Math.abs(rotationDelta.z_deg) > 0.1;

  let actionType = 'translate';
  if (hasTrans && hasRot) actionType = 'translate_and_rotate';
  else if (hasRot) actionType = 'rotate';

  const parts: string[] = [];
  if (hasTrans) {
    parts.push(`translated [${translationDelta.x.toFixed(1)}, ${translationDelta.y.toFixed(1)}, ${translationDelta.z.toFixed(1)}]mm`);
  }
  if (hasRot) {
    parts.push(`rotated [${rotationDelta.x_deg.toFixed(1)}, ${rotationDelta.y_deg.toFixed(1)}, ${rotationDelta.z_deg.toFixed(1)}]°`);
  }
  const intent = `Manual UI adjustment by Surgeon: ${fragment.fragment_id} ${parts.join(' and ')}`;

  return {
    action_type: actionType,
    target: fragment,
    clinical_intent: intent,
    translation_mm: translationDelta,
    rotation_deg: rotationDelta,
    case_id: caseId,
    branch: 'LLM_Hypothesis',
    source_agent: 'surgeon',
  };
}
