"""Autonomous Catalog-to-CAD Pipeline (Phase 9).

End-to-end agentic workflow:
1. Claude: web research to find manufacturer catalog/specs
2. Gemini: extract parametric dimensions from catalog images
3. Claude: generate OpenSCAD code from parametric spec
4. Render: 6-way orthographic views, stitched into grid
5. Gemini: QA validation against original catalog
6. Loop until APPROVED or 6-strike halt

No human intervention unless the 6-strike safety threshold is hit.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import sys, pathlib

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)
)
from shared.implant_schemas import (
    ImplantCADResult,
    ImplantQAState,
    ManufacturerAlias,
    ParametricImplantSpec,
    QAIteration,
    QAStatus,
)

logger = logging.getLogger("osteotwin.implant_cad")

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "implants"


# ---------------------------------------------------------------------------
# Gemini extraction prompt
# ---------------------------------------------------------------------------

GEMINI_EXTRACTION_PROMPT = """\
You are OsteoTwin's Implant Dimension Extractor.

Given manufacturer catalog images and product descriptions for an orthopedic implant,
extract ALL parametric dimensions into the JSON schema below.

## CRITICAL RULES:
1. **Manufacturer Alias**: Identify the manufacturer and output ONLY the 3-letter alias:
   - DePuy Synthes → SYN
   - Stryker → STK
   - Zimmer Biomet → ZIM
   - Acumed → ACM
   - Arthrex → ARX
   - Smith & Nephew → SMN
   - Medartis → MED
   - Unknown → GEN
2. **Do NOT include the full manufacturer name** anywhere in the JSON.
3. Extract dimensions in millimeters. Convert from inches if needed.
4. For plates: extract EVERY hole with its type, diameter, and position.
5. For screws: extract thread pitch, head dimensions, shaft diameter.
6. Include the body region this implant is designed for.

## Output JSON Schema:
```json
{
  "manufacturer_alias": "SYN",
  "implant_name": "LCP Volar Distal Radius Plate",
  "catalog_number": "02.111.005",
  "implant_type": "locking_plate",
  "length_mm": 68.0,
  "width_mm": 22.0,
  "thickness_mm": 2.4,
  "contour": "anatomic",
  "hole_count": 7,
  "holes": [
    {"index": 0, "hole_type": "combination", "diameter_mm": 3.5, "offset_x_mm": 0, "offset_y_mm": 0},
    ...
  ],
  "material": "Titanium",
  "body_region": "distal_radius",
  "side_specific": true
}
```

Only output the JSON. No commentary.
"""


# ---------------------------------------------------------------------------
# Gemini QA validation prompt
# ---------------------------------------------------------------------------

GEMINI_QA_PROMPT = """\
You are OsteoTwin's Implant QA Vision Critic.

Compare the rendered 3D model (6-way orthographic views) against the original
manufacturer catalog specifications.

## Evaluation Criteria (10-Point Checklist):
1. Overall silhouette matches catalog profile
2. Correct number of screw holes
3. Correct hole types (locking vs compression vs combination)
4. Accurate hole spacing and positions
5. Correct plate contour/curvature
6. Thickness is proportional to catalog specs
7. Width matches at all cross-sections
8. Length is correct end-to-end
9. Any anatomic pre-contouring matches the target bone surface
10. No phantom geometry or missing features

## Output Format:
If the model is geometrically accurate:
<status>APPROVED</status>
<assessment>Brief confirmation of accuracy.</assessment>

If there are errors:
<status>REJECTED</status>
<assessment>Description of errors found.</assessment>
<corrections>
  <item>Variable: hole_count, Current: 5, Expected: 7, Fix: Add 2 distal locking holes</item>
  <item>Variable: thickness_mm, Current: 3.0, Expected: 2.4, Fix: Reduce plate_thickness</item>
  ...
</corrections>
"""


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


async def run_implant_pipeline(
    implant_name: str,
    *,
    catalog_images: Optional[list[str]] = None,
    manual_spec: Optional[ParametricImplantSpec] = None,
    max_rejections: int = 6,
) -> ImplantCADResult:
    """Run the full autonomous Catalog-to-CAD pipeline.

    Steps:
        1. Extract dimensions (Gemini) or use provided spec
        2. Generate OpenSCAD code (Claude)
        3. Render 6-way views
        4. QA loop: Gemini validates, Claude corrects, max 6 strikes
        5. Export final STL/3MF or generate failure report

    Args:
        implant_name: Human-readable implant name (e.g., "DePuy Synthes 3.5mm LCP...")
        catalog_images: Optional paths to catalog images for Gemini extraction
        manual_spec: Optional pre-extracted spec (skips step 1)
        max_rejections: Maximum QA rejections before halting (default: 6)

    Returns:
        ImplantCADResult with either approved output or failure report.
    """
    logger.info("Starting implant CAD pipeline: %s", implant_name)

    # Step 1: Get parametric spec
    if manual_spec:
        spec = manual_spec
        logger.info("Using provided spec: %s", spec.file_prefix)
    else:
        spec = await _extract_dimensions(implant_name, catalog_images)
        logger.info("Extracted spec: %s (%d holes)", spec.file_prefix, spec.hole_count or 0)

    # Step 2-4: QA loop
    qa_state = ImplantQAState(implant_spec=spec)
    scad_code = await _generate_scad(spec)

    for iteration in range(1, max_rejections + 1):
        logger.info("QA iteration %d/%d for %s", iteration, max_rejections, spec.file_prefix)

        # Render 6-way orthographic views
        render_path = await _render_6way(scad_code, spec, iteration)

        # Gemini QA validation
        qa_result = await _validate_with_gemini(
            scad_code, render_path, catalog_images, spec
        )

        qa_iter = QAIteration(
            iteration=iteration,
            status=qa_result["status"],
            feedback=qa_result.get("assessment"),
            constraint_checklist=qa_result.get("corrections", []),
            scad_code_hash=hashlib.sha256(scad_code.encode()).hexdigest()[:16],
            render_path=str(render_path) if render_path else None,
        )
        qa_state.iterations.append(qa_iter)

        if qa_state.is_approved:
            logger.info("APPROVED on iteration %d: %s", iteration, spec.file_prefix)
            break

        if qa_state.is_halted:
            logger.warning(
                "6-STRIKE HALT for %s after %d rejections",
                spec.file_prefix, qa_state.rejection_count,
            )
            break

        # Auto-correct: Claude reads feedback and updates SCAD
        logger.info("REJECTED (iteration %d): applying corrections", iteration)
        scad_code = await _apply_corrections(scad_code, spec, qa_iter)

    # Step 5: Export or generate failure report
    stl_path = None
    threemf_path = None
    failure_report = None

    if qa_state.is_approved:
        stl_path, threemf_path = await _export_final(scad_code, spec)
    else:
        failure_report = _build_failure_report(qa_state, scad_code)

    return ImplantCADResult(
        spec=spec,
        scad_code=scad_code,
        stl_path=str(stl_path) if stl_path else None,
        threemf_path=str(threemf_path) if threemf_path else None,
        render_6way_path=(
            str(qa_state.iterations[-1].render_path)
            if qa_state.iterations
            else None
        ),
        qa_iterations=qa_state.current_iteration,
        approved=qa_state.is_approved,
        failure_report=failure_report,
    )


# ---------------------------------------------------------------------------
# Pipeline step stubs (to be wired to actual LLM calls)
# ---------------------------------------------------------------------------


async def _extract_dimensions(
    implant_name: str,
    catalog_images: Optional[list[str]],
) -> ParametricImplantSpec:
    """Step 1: Call Gemini to extract parametric dimensions from catalog.

    TODO: Wire to Gemini API with GEMINI_EXTRACTION_PROMPT + catalog images.
    """
    logger.info("Extracting dimensions for: %s", implant_name)

    # Placeholder — returns a generic spec to be replaced with actual Gemini call
    return ParametricImplantSpec(
        manufacturer_alias=ManufacturerAlias.GEN,
        implant_name=implant_name,
        implant_type="locking_plate",
        length_mm=68.0,
        width_mm=22.0,
        thickness_mm=2.4,
        body_region="unknown",
    )


async def _generate_scad(spec: ParametricImplantSpec) -> str:
    """Step 2: Generate OpenSCAD code from parametric spec.

    TODO: Wire to Claude API to generate procedural OpenSCAD.
    """
    logger.info("Generating SCAD for: %s", spec.file_prefix)

    # Placeholder SCAD
    holes_code = ""
    if spec.holes:
        for h in spec.holes:
            holes_code += (
                f"  translate([{h.offset_x_mm}, {h.offset_y_mm * h.index}, 0])\n"
                f"    cylinder(h={spec.thickness_mm + 1}, d={h.diameter_mm}, center=true, $fn=32);\n"
            )

    return f"""\
// Auto-generated by OsteoTwin Implant CAD Pipeline
// {spec.file_prefix}
// Generated: {datetime.utcnow().isoformat()}

module {spec.manufacturer_alias.value}_plate() {{
  difference() {{
    // Plate body
    cube([{spec.width_mm}, {spec.length_mm}, {spec.thickness_mm}], center=true);

    // Screw holes
{holes_code}  }}
}}

{spec.manufacturer_alias.value}_plate();
"""


async def _render_6way(
    scad_code: str,
    spec: ParametricImplantSpec,
    iteration: int,
) -> Optional[Path]:
    """Step 3: Render 6-way orthographic views and stitch into grid.

    TODO: Call OpenSCAD CLI to render, then stitch with PIL/Pillow.
    Returns path to stitched image or None if rendering fails.
    """
    out_dir = OUTPUT_DIR / spec.file_prefix
    out_dir.mkdir(parents=True, exist_ok=True)

    scad_path = out_dir / f"iter{iteration}.scad"
    scad_path.write_text(scad_code, encoding="utf-8")

    # TODO: subprocess call to openscad --render for 6 angles
    # For now, return the SCAD path as a placeholder
    logger.info("Render stub: saved SCAD to %s", scad_path)
    return scad_path


async def _validate_with_gemini(
    scad_code: str,
    render_path: Optional[Path],
    catalog_images: Optional[list[str]],
    spec: ParametricImplantSpec,
) -> dict[str, Any]:
    """Step 4: Send render + SCAD + catalog to Gemini for QA.

    TODO: Wire to Gemini API with GEMINI_QA_PROMPT.
    Returns dict with 'status' (APPROVED/REJECTED), 'assessment', 'corrections'.
    """
    logger.info("QA validation stub for: %s", spec.file_prefix)

    # Placeholder — auto-approve on first call
    return {
        "status": QAStatus.APPROVED,
        "assessment": "Stub: auto-approved (wire to Gemini for real validation)",
        "corrections": [],
    }


async def _apply_corrections(
    scad_code: str,
    spec: ParametricImplantSpec,
    qa_iter: QAIteration,
) -> str:
    """Step 4b: Claude reads Gemini feedback and updates SCAD code.

    TODO: Wire to Claude API with correction instructions.
    """
    logger.info(
        "Applying %d corrections for %s",
        len(qa_iter.constraint_checklist),
        spec.file_prefix,
    )

    # Placeholder — return code as-is
    return scad_code


async def _export_final(
    scad_code: str,
    spec: ParametricImplantSpec,
) -> tuple[Optional[Path], Optional[Path]]:
    """Step 5: Export approved model as STL and 3MF.

    TODO: Call OpenSCAD to export STL, then wrap in 3MF.
    """
    out_dir = OUTPUT_DIR / spec.file_prefix
    out_dir.mkdir(parents=True, exist_ok=True)

    stl_path = out_dir / f"{spec.file_prefix}.stl"
    threemf_path = out_dir / f"{spec.file_prefix}.3mf"

    # Save SCAD for reference
    (out_dir / f"{spec.file_prefix}.scad").write_text(scad_code, encoding="utf-8")

    # TODO: subprocess call to openscad -o <stl> <scad>
    logger.info("Export stub: would generate %s and %s", stl_path.name, threemf_path.name)
    return stl_path, threemf_path


def _build_failure_report(qa_state: ImplantQAState, scad_code: str) -> str:
    """Build a human-readable failure report after 6-strike halt."""
    spec = qa_state.implant_spec
    lines = [
        f"# 6-STRIKE FAILURE REPORT: {spec.file_prefix}",
        f"**Manufacturer:** {spec.manufacturer_alias.value}",
        f"**Implant:** {spec.implant_name}",
        f"**Total iterations:** {qa_state.current_iteration}",
        f"**Rejections:** {qa_state.rejection_count}",
        "",
        "## Accumulated Rejection Feedback:",
    ]

    for it in qa_state.iterations:
        if it.status == QAStatus.REJECTED:
            lines.append(f"\n### Iteration {it.iteration}")
            lines.append(f"**Feedback:** {it.feedback or 'N/A'}")
            if it.constraint_checklist:
                lines.append("**Corrections needed:**")
                for item in it.constraint_checklist:
                    lines.append(f"  - {item}")

    lines.extend([
        "",
        "## Current SCAD Code:",
        "```scad",
        scad_code,
        "```",
        "",
        "## Action Required:",
        "Please review the above feedback and SCAD code.",
        "Manually correct the parametric variables and re-run the pipeline.",
    ])

    return "\n".join(lines)
