"""AO Surgery Reference Scraper — Playwright-based JS-rendered content extraction.

The AO Surgery Reference (surgeryreference.aofoundation.org) is a Single Page
Application that loads content via JavaScript. Standard HTTP requests only get
the shell HTML. This scraper uses Playwright (headless Chromium) to render the
pages and extract the full surgical technique content.

Usage:
    python -m planning_server.app.knowledge_cache.ao_scraper [--region all|spine|upper|lower]
    python -m planning_server.app.knowledge_cache.ao_scraper --backup-gcs

The scraped content is saved to planning_server/knowledge_data/ and backed up
to GCS. These files are git-ignored.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("osteotwin.ao_scraper")

# Local cache directory
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Base URL
BASE_URL = "https://surgeryreference.aofoundation.org"

# ---------------------------------------------------------------------------
# Complete AO Surgery Reference URL map
# ---------------------------------------------------------------------------

AO_PAGES: dict[str, list[dict]] = {
    "upper_extremity": [
        {"id": "aosr_clavicle", "label": "Clavicle Fractures", "paths": [
            "/orthopedic-trauma/adult-trauma/clavicle-fractures",
            "/orthopedic-trauma/adult-trauma/clavicle-fractures/approach/all-approaches",
            "/orthopedic-trauma/adult-trauma/clavicle-fractures/further-reading/all-further-reading",
        ]},
        {"id": "aosr_scapula", "label": "Scapula", "paths": [
            "/orthopedic-trauma/adult-trauma/scapula",
        ]},
        {"id": "aosr_proximal_humerus", "label": "Proximal Humerus", "paths": [
            "/orthopedic-trauma/adult-trauma/proximal-humerus",
            "/orthopedic-trauma/adult-trauma/proximal-humerus/approach/all-approaches",
        ]},
        {"id": "aosr_humeral_shaft", "label": "Humeral Shaft", "paths": [
            "/orthopedic-trauma/adult-trauma/humeral-shaft",
        ]},
        {"id": "aosr_distal_humerus", "label": "Distal Humerus", "paths": [
            "/orthopedic-trauma/adult-trauma/distal-humerus",
            "/orthopedic-trauma/adult-trauma/distal-humerus/approach/all-approaches",
        ]},
        {"id": "aosr_proximal_forearm", "label": "Proximal Forearm", "paths": [
            "/orthopedic-trauma/adult-trauma/proximal-forearm",
        ]},
        {"id": "aosr_forearm_shaft", "label": "Forearm Shaft", "paths": [
            "/orthopedic-trauma/adult-trauma/forearm-shaft",
        ]},
        {"id": "aosr_distal_forearm", "label": "Distal Forearm", "paths": [
            "/orthopedic-trauma/adult-trauma/distal-forearm",
            "/orthopedic-trauma/adult-trauma/distal-forearm/approach/all-approaches",
            "/orthopedic-trauma/adult-trauma/distal-forearm/preparation/all-preparation",
            "/orthopedic-trauma/adult-trauma/distal-forearm/further-reading/all-further-reading",
        ]},
        {"id": "aosr_hand", "label": "Hand (Carpals, Metacarpals, Phalanges)", "paths": [
            "/orthopedic-trauma/adult-trauma/carpal-bones",
            "/orthopedic-trauma/adult-trauma/metacarpals",
            "/orthopedic-trauma/adult-trauma/hand-proximal-phalanges",
            "/orthopedic-trauma/adult-trauma/thumb",
        ]},
    ],
    "lower_extremity": [
        {"id": "aosr_pelvic_ring", "label": "Pelvic Ring", "paths": [
            "/orthopedic-trauma/adult-trauma/pelvic-ring",
        ]},
        {"id": "aosr_acetabulum", "label": "Acetabulum", "paths": [
            "/orthopedic-trauma/adult-trauma/acetabulum",
        ]},
        {"id": "aosr_proximal_femur", "label": "Proximal Femur", "paths": [
            "/orthopedic-trauma/adult-trauma/proximal-femur",
            "/orthopedic-trauma/adult-trauma/proximal-femur/approach/all-approaches",
        ]},
        {"id": "aosr_femoral_shaft", "label": "Femoral Shaft", "paths": [
            "/orthopedic-trauma/adult-trauma/femoral-shaft",
        ]},
        {"id": "aosr_distal_femur", "label": "Distal Femur", "paths": [
            "/orthopedic-trauma/adult-trauma/distal-femur",
        ]},
        {"id": "aosr_patella", "label": "Patella", "paths": [
            "/orthopedic-trauma/adult-trauma/patella",
        ]},
        {"id": "aosr_proximal_tibia", "label": "Proximal Tibia", "paths": [
            "/orthopedic-trauma/adult-trauma/proximal-tibia",
            "/orthopedic-trauma/adult-trauma/proximal-tibia/approach/all-approaches",
        ]},
        {"id": "aosr_tibial_shaft", "label": "Tibial Shaft", "paths": [
            "/orthopedic-trauma/adult-trauma/tibial-shaft",
        ]},
        {"id": "aosr_distal_tibia_malleoli", "label": "Distal Tibia & Malleoli", "paths": [
            "/orthopedic-trauma/adult-trauma/distal-tibia",
            "/orthopedic-trauma/adult-trauma/malleoli",
            "/orthopedic-trauma/adult-trauma/malleoli/approach/all-approaches",
        ]},
        {"id": "aosr_foot", "label": "Foot", "paths": [
            "/orthopedic-trauma/adult-trauma/talus",
            "/orthopedic-trauma/adult-trauma/calcaneous",
            "/orthopedic-trauma/adult-trauma/midfoot",
            "/orthopedic-trauma/adult-trauma/metatarsals",
        ]},
    ],
    "spine": [
        {"id": "aosr_spine_cervical", "label": "Spine: Cervical", "paths": [
            "/spine/trauma/occipitocervical",
            "/spine/trauma/subaxial-cervical",
        ]},
        {"id": "aosr_spine_thoracolumbar", "label": "Spine: Thoracolumbar", "paths": [
            "/spine/trauma/thoracolumbar",
        ]},
        {"id": "aosr_spine_sacrum", "label": "Spine: Sacropelvic", "paths": [
            "/spine/trauma/sacrum",
        ]},
        {"id": "aosr_spine_degenerative", "label": "Spine: Degenerative", "paths": [
            "/spine/degenerative",
        ]},
        {"id": "aosr_spine_deformities", "label": "Spine: Deformities", "paths": [
            "/spine/deformities",
        ]},
        {"id": "aosr_spine_tumors", "label": "Spine: Tumors", "paths": [
            "/spine/tumors",
        ]},
    ],
}


async def scrape_ao_page(page, url: str) -> str:
    """Navigate to a URL, wait for JS rendering, and extract text content.

    For AO Surgery Reference SPA pages, we:
    1. Load the page and wait for network idle
    2. Click all "Learn more" / expandable sections
    3. Extract the full rendered text from the body
    """
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)  # Wait for SPA rendering

        # Try to expand all collapsible sections
        try:
            # Click "Open subtypes", "Learn more", accordion headers, etc.
            expandables = await page.query_selector_all(
                'button, [class*="expand"], [class*="toggle"], '
                '[class*="accordion"], a[class*="more"], [class*="collaps"]'
            )
            for btn in expandables[:30]:  # Limit to avoid infinite loops
                try:
                    if await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.3)
                except Exception:
                    pass
        except Exception:
            pass

        await asyncio.sleep(2)  # Wait for expanded content to render

        # Extract body text
        content = await page.inner_text("body")
        return content.strip()

    except Exception as exc:
        logger.warning("Failed to scrape %s: %s", url, exc)
        return ""


async def scrape_region(
    region: str,
    headless: bool = True,
) -> dict[str, int]:
    """Scrape all AO Surgery Reference pages for a body region.

    Args:
        region: "upper_extremity", "lower_extremity", "spine", or "all"
        headless: Run browser in headless mode

    Returns:
        Dict of {source_id: token_count}
    """
    from playwright.async_api import async_playwright

    if region == "all":
        regions = list(AO_PAGES.keys())
    else:
        regions = [region]

    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) OsteoTwin/1.0 (Research; Open Access)",
        )
        page = await context.new_page()

        for reg in regions:
            if reg not in AO_PAGES:
                logger.warning("Unknown region: %s", reg)
                continue

            for entry in AO_PAGES[reg]:
                source_id = entry["id"]
                label = entry["label"]
                paths = entry["paths"]

                logger.info("Scraping %s (%s)...", label, source_id)
                all_text = []

                for path in paths:
                    url = f"{BASE_URL}{path}"
                    text = await scrape_ao_page(page, url)
                    if text and len(text) > 100:
                        all_text.append(f"--- {path} ---\n{text}")
                    # Be polite
                    await asyncio.sleep(1)

                if all_text:
                    full_text = (
                        f"=== AO Surgery Reference - {label} ===\n"
                        f"Source: {BASE_URL}{paths[0]}\n"
                        f"License: AO Foundation (free open access)\n"
                        f"{'=' * 60}\n\n"
                        + "\n\n".join(all_text)
                    )

                    # Clean text
                    full_text = _clean_ao_text(full_text)

                    # Save
                    out_path = CACHE_DIR / f"{source_id}.txt"
                    out_path.write_text(full_text, encoding="utf-8")

                    # Save metadata
                    meta = (
                        f"source_id: {source_id}\n"
                        f"name: AO Surgery Reference - {label}\n"
                        f"url: {BASE_URL}{paths[0]}\n"
                        f"license: AO Foundation (free open access)\n"
                        f"downloaded: {time.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
                        f"scraper: playwright\n"
                        f"pages_scraped: {len(paths)}\n"
                        f"size_bytes: {len(full_text.encode('utf-8'))}\n"
                        f"estimated_tokens: {len(full_text) // 4}\n"
                    )
                    (CACHE_DIR / f"{source_id}.meta").write_text(meta, encoding="utf-8")

                    tokens = len(full_text) // 4
                    results[source_id] = tokens
                    logger.info("  %s: %d chars (~%d tokens)", source_id, len(full_text), tokens)
                else:
                    results[source_id] = 0
                    logger.warning("  %s: no content extracted", source_id)

        await browser.close()

    return results


def _clean_ao_text(text: str) -> str:
    """Clean extracted AO Surgery Reference text."""
    # Remove cookie banners, nav items
    text = re.sub(r"(Accept All|Reject All|Cookie|Privacy Policy).*?\n", "", text)
    # Collapse whitespace
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r" {3,}", " ", text)
    # Remove very short lines (navigation artifacts)
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if len(s) < 3 and s not in ("", "-", "*", "|"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def backup_to_gcs() -> int:
    """Backup scraped AO content to GCS."""
    from .downloader import backup_to_gcs as _backup
    return _backup()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="AO Surgery Reference Scraper")
    parser.add_argument(
        "--region", default="all",
        choices=["all", "upper_extremity", "lower_extremity", "spine"],
        help="Body region to scrape (default: all)",
    )
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--backup-gcs", action="store_true", help="Backup to GCS after scraping")
    args = parser.parse_args()

    print(f"Scraping AO Surgery Reference: {args.region}")
    results = await scrape_region(args.region, headless=not args.no_headless)

    print(f"\n{'=' * 60}")
    print(f"Results:")
    total_tokens = 0
    for source_id, tokens in sorted(results.items()):
        status = f"{tokens:,} tokens" if tokens > 0 else "EMPTY"
        print(f"  {source_id}: {status}")
        total_tokens += tokens
    print(f"\nTotal: {total_tokens:,} tokens across {len(results)} sources")

    if args.backup_gcs:
        print("\nBacking up to GCS...")
        count = backup_to_gcs()
        print(f"Backed up {count} files")


if __name__ == "__main__":
    asyncio.run(main())
