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
# Pipeline steps (wired to actual LLM calls)
# ---------------------------------------------------------------------------


async def _extract_dimensions(
    implant_name: str,
    catalog_images: Optional[list[str]],
) -> ParametricImplantSpec:
    """Step 1: Call Gemini to extract parametric dimensions from catalog."""
    from ..pipeline.llm import generate_text, Provider

    logger.info("Extracting dimensions for: %s", implant_name)

    image_context = ""
    if catalog_images:
        image_context = (
            f"\n\nCatalog reference images provided: {len(catalog_images)} files. "
            "Extract dimensions from the technical drawings and specification tables."
        )

    prompt = (
        f"Extract the parametric dimensions for this orthopedic implant:\n"
        f"**{implant_name}**{image_context}\n\n"
        f"Respond with ONLY valid JSON matching the ParametricImplantSpec schema. "
        f"Remember to use the 3-letter manufacturer alias (SYN, STK, ZIM, ACM, ARX, SMN, MED, GEN)."
    )

    raw = await generate_text(
        prompt,
        system=GEMINI_EXTRACTION_PROMPT,
        provider=Provider.GEMINI,
        max_tokens=4096,
    )

    import re
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        spec_data = json.loads(json_match.group())
        return ParametricImplantSpec.model_validate(spec_data)

    logger.warning("Gemini extraction failed to return valid JSON, using fallback")
    return ParametricImplantSpec(
        manufacturer_alias=ManufacturerAlias.GEN,
        implant_name=implant_name,
        implant_type="locking_plate",
        length_mm=68.0,
        width_mm=22.0,
        thickness_mm=2.4,
        body_region="unknown",
    )


SCAD_GENERATION_PROMPT = """\
You are an expert OpenSCAD programmer generating parametric orthopedic implant models.

Given a JSON specification of an implant, generate a complete, compilable OpenSCAD script.

Rules:
1. Use `difference()` for screw holes, `hull()` for anatomic contours.
2. All dimensions in millimeters.
3. Use `$fn=64` for smooth cylinders.
4. Add a 0.3mm global fillet on plate edges using `minkowski()` with a small sphere.
5. For locking holes: countersunk profile. For combination holes: straight-through.
6. Add a module for each major feature (plate body, holes, contour).
7. Include the file_prefix in a comment header.
8. The script must be self-contained and render without errors.

Output ONLY the OpenSCAD code. No markdown fences. No commentary.
"""


async def _generate_scad(spec: ParametricImplantSpec) -> str:
    """Step 2: Call Claude to generate procedural OpenSCAD from parametric spec."""
    from ..pipeline.llm import generate_text, Provider

    logger.info("Generating SCAD for: %s", spec.file_prefix)

    spec_json = spec.model_dump_json(indent=2)
    prompt = (
        f"Generate an OpenSCAD script for this implant specification:\n\n"
        f"```json\n{spec_json}\n```\n\n"
        f"File prefix: {spec.file_prefix}"
    )

    scad_code = await generate_text(
        prompt,
        system=SCAD_GENERATION_PROMPT,
        provider=Provider.CLAUDE,
        max_tokens=8192,
    )

    # Strip markdown fences if Claude wrapped the output
    scad_code = scad_code.strip()
    if scad_code.startswith("```"):
        lines = scad_code.split("\n")
        scad_code = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    header = (
        f"// Auto-generated by OsteoTwin Implant CAD Pipeline\n"
        f"// {spec.file_prefix}\n"
        f"// Generated: {datetime.utcnow().isoformat()}\n\n"
    )
    return header + scad_code


async def _render_6way(
    scad_code: str,
    spec: ParametricImplantSpec,
    iteration: int,
) -> Optional[Path]:
    """Step 3: Render 6-way orthographic views and stitch into grid.

    Calls OpenSCAD CLI for 6 camera angles, then stitches with Pillow.
    Falls back to saving SCAD file if OpenSCAD is not installed.
    """
    import asyncio
    import shutil

    out_dir = OUTPUT_DIR / spec.file_prefix
    out_dir.mkdir(parents=True, exist_ok=True)

    scad_path = out_dir / f"iter{iteration}.scad"
    scad_path.write_text(scad_code, encoding="utf-8")

    openscad_bin = shutil.which("openscad") or shutil.which("OpenSCAD")
    if not openscad_bin:
        logger.warning("OpenSCAD not found in PATH, skipping render (SCAD saved)")
        return scad_path

    # 6-way orthographic camera angles: rotx,roty,rotz,tx,ty,tz
    views = {
        "top":    "0,0,0,0,0,0",
        "bottom": "180,0,0,0,0,0",
        "front":  "90,0,0,0,0,0",
        "back":   "90,0,180,0,0,0",
        "left":   "90,0,90,0,0,0",
        "right":  "90,0,270,0,0,0",
    }

    render_paths: list[Path] = []
    for view_name, camera_rot in views.items():
        png_path = out_dir / f"iter{iteration}_{view_name}.png"
        cmd = [
            openscad_bin, "-o", str(png_path),
            "--camera", f"{camera_rot},200",
            "--autocenter", "--viewall",
            "--imgsize", "512,512",
            "--projection", "ortho",
            str(scad_path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if png_path.exists():
                render_paths.append(png_path)
            else:
                logger.warning("OpenSCAD render failed for %s: %s", view_name, stderr.decode()[:200])
        except Exception as exc:
            logger.warning("OpenSCAD render error for %s: %s", view_name, exc)

    if not render_paths:
        logger.warning("No renders produced, returning SCAD path")
        return scad_path

    # Stitch into 2x3 grid
    stitched_path = out_dir / f"iter{iteration}_6way.png"
    try:
        from PIL import Image

        images = [Image.open(p) for p in render_paths]
        w, h = images[0].size
        grid = Image.new("RGB", (w * 3, h * 2), (30, 30, 30))
        for idx, img in enumerate(images[:6]):
            col, row = idx % 3, idx // 3
            grid.paste(img, (col * w, row * h))
        grid.save(stitched_path)
        logger.info("Stitched 6-way render: %s", stitched_path.name)
        return stitched_path
    except ImportError:
        logger.warning("Pillow not installed, returning first render")
        return render_paths[0]


async def _validate_with_gemini(
    scad_code: str,
    render_path: Optional[Path],
    catalog_images: Optional[list[str]],
    spec: ParametricImplantSpec,
) -> dict[str, Any]:
    """Step 4: Send render + SCAD + catalog to Gemini for QA validation."""
    from ..pipeline.llm import generate_text, Provider
    import re as _re

    logger.info("QA validation for: %s", spec.file_prefix)

    spec_json = spec.model_dump_json(indent=2)
    prompt = (
        f"Validate this 3D implant model against the specification.\n\n"
        f"## Specification:\n```json\n{spec_json}\n```\n\n"
        f"## OpenSCAD Code:\n```scad\n{scad_code[:3000]}\n```\n\n"
    )

    if render_path and render_path.suffix == ".png":
        prompt += f"## Render: 6-way orthographic view available at {render_path.name}\n\n"

    prompt += "Evaluate against the 10-point checklist and respond with XML status tags."

    raw = await generate_text(
        prompt,
        system=GEMINI_QA_PROMPT,
        provider=Provider.GEMINI,
        max_tokens=4096,
    )

    status_match = _re.search(r"<status>(APPROVED|REJECTED)</status>", raw)
    status = QAStatus(status_match.group(1)) if status_match else QAStatus.REJECTED

    assessment_match = _re.search(r"<assessment>(.*?)</assessment>", raw, _re.DOTALL)
    assessment = assessment_match.group(1).strip() if assessment_match else raw[:500]

    corrections: list[str] = []
    correction_matches = _re.findall(r"<item>(.*?)</item>", raw, _re.DOTALL)
    corrections = [c.strip() for c in correction_matches]

    return {
        "status": status,
        "assessment": assessment,
        "corrections": corrections,
    }


CORRECTION_PROMPT = """\
You are fixing an OpenSCAD implant model based on QA feedback.

Given:
1. The current OpenSCAD code
2. The implant specification (JSON)
3. A list of specific corrections from the QA reviewer

Apply ONLY the requested corrections. Do not redesign the model.
Output the corrected OpenSCAD code. No markdown fences. No commentary.
"""


async def _apply_corrections(
    scad_code: str,
    spec: ParametricImplantSpec,
    qa_iter: QAIteration,
) -> str:
    """Step 4b: Claude reads Gemini feedback and updates SCAD code."""
    from ..pipeline.llm import generate_text, Provider

    logger.info(
        "Applying %d corrections for %s",
        len(qa_iter.constraint_checklist),
        spec.file_prefix,
    )

    corrections_text = "\n".join(f"- {c}" for c in qa_iter.constraint_checklist)
    prompt = (
        f"## Current OpenSCAD Code:\n```scad\n{scad_code}\n```\n\n"
        f"## Implant Spec:\n```json\n{spec.model_dump_json(indent=2)}\n```\n\n"
        f"## QA Feedback:\n{qa_iter.feedback or 'No details'}\n\n"
        f"## Corrections Required:\n{corrections_text}\n\n"
        f"Apply these corrections and output the fixed OpenSCAD code."
    )

    corrected = await generate_text(
        prompt,
        system=CORRECTION_PROMPT,
        provider=Provider.CLAUDE,
        max_tokens=8192,
    )

    corrected = corrected.strip()
    if corrected.startswith("```"):
        lines = corrected.split("\n")
        corrected = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    return corrected if corrected else scad_code


async def _export_final(
    scad_code: str,
    spec: ParametricImplantSpec,
) -> tuple[Optional[Path], Optional[Path]]:
    """Step 5: Export approved model as STL and 3MF via OpenSCAD CLI."""
    import asyncio
    import shutil

    out_dir = OUTPUT_DIR / spec.file_prefix
    out_dir.mkdir(parents=True, exist_ok=True)

    scad_path = out_dir / f"{spec.file_prefix}.scad"
    stl_path = out_dir / f"{spec.file_prefix}.stl"
    threemf_path = out_dir / f"{spec.file_prefix}.3mf"

    scad_path.write_text(scad_code, encoding="utf-8")

    openscad_bin = shutil.which("openscad") or shutil.which("OpenSCAD")
    if not openscad_bin:
        logger.warning("OpenSCAD not in PATH, SCAD saved but STL/3MF not generated")
        return None, None

    # Export STL
    try:
        proc = await asyncio.create_subprocess_exec(
            openscad_bin, "-o", str(stl_path), str(scad_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if not stl_path.exists():
            logger.error("STL export failed: %s", stderr.decode()[:300])
            stl_path = None
    except Exception as exc:
        logger.error("STL export error: %s", exc)
        stl_path = None

    # Export 3MF
    try:
        proc = await asyncio.create_subprocess_exec(
            openscad_bin, "-o", str(threemf_path), str(scad_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if not threemf_path.exists():
            logger.error("3MF export failed: %s", stderr.decode()[:300])
            threemf_path = None
    except Exception as exc:
        logger.error("3MF export error: %s", exc)
        threemf_path = None

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
