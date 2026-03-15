"""AO Surgery Reference Scraper — Sitecore Layout API-based content extraction.

The AO Surgery Reference (surgeryreference.aofoundation.org) is powered by
Sitecore JSS. Instead of rendering the SPA with a headless browser, we query
the Sitecore Layout Service API directly to get the full JSON content, then
extract text from the structured data.

This is faster, more reliable, and gets deeper content than Playwright.

Usage:
    python -m planning_server.app.knowledge_cache.ao_scraper [--region all|spine|upper|lower]
    python -m planning_server.app.knowledge_cache.ao_scraper --backup-gcs
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("osteotwin.ao_scraper")

# Local cache directory
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Sitecore API config
BASE_URL = "https://surgeryreference.aofoundation.org"
SITECORE_API_KEY = "{10C266B4-B8DB-47D1-8F7C-15963F9BEC78}"
LAYOUT_API = "/sitecore/api/layout/render/jss"

# ---------------------------------------------------------------------------
# AO Surgery Reference page map (top-level entry points)
# ---------------------------------------------------------------------------

AO_ENTRY_PAGES: dict[str, list[dict]] = {
    "upper_extremity": [
        {"id": "aosr_clavicle", "label": "Clavicle Fractures", "path": "/orthopedic-trauma/adult-trauma/clavicle-fractures"},
        {"id": "aosr_scapula", "label": "Scapula", "path": "/orthopedic-trauma/adult-trauma/scapula"},
        {"id": "aosr_proximal_humerus", "label": "Proximal Humerus", "path": "/orthopedic-trauma/adult-trauma/proximal-humerus"},
        {"id": "aosr_humeral_shaft", "label": "Humeral Shaft", "path": "/orthopedic-trauma/adult-trauma/humeral-shaft"},
        {"id": "aosr_distal_humerus", "label": "Distal Humerus", "path": "/orthopedic-trauma/adult-trauma/distal-humerus"},
        {"id": "aosr_proximal_forearm", "label": "Proximal Forearm", "path": "/orthopedic-trauma/adult-trauma/proximal-forearm"},
        {"id": "aosr_forearm_shaft", "label": "Forearm Shaft", "path": "/orthopedic-trauma/adult-trauma/forearm-shaft"},
        {"id": "aosr_distal_forearm", "label": "Distal Forearm", "path": "/orthopedic-trauma/adult-trauma/distal-forearm"},
        {"id": "aosr_hand", "label": "Hand", "path": "/orthopedic-trauma/adult-trauma/carpal-bones"},
    ],
    "lower_extremity": [
        {"id": "aosr_pelvic_ring", "label": "Pelvic Ring", "path": "/orthopedic-trauma/adult-trauma/pelvic-ring"},
        {"id": "aosr_acetabulum", "label": "Acetabulum", "path": "/orthopedic-trauma/adult-trauma/acetabulum"},
        {"id": "aosr_proximal_femur", "label": "Proximal Femur", "path": "/orthopedic-trauma/adult-trauma/proximal-femur"},
        {"id": "aosr_femoral_shaft", "label": "Femoral Shaft", "path": "/orthopedic-trauma/adult-trauma/femoral-shaft"},
        {"id": "aosr_distal_femur", "label": "Distal Femur", "path": "/orthopedic-trauma/adult-trauma/distal-femur"},
        {"id": "aosr_patella", "label": "Patella", "path": "/orthopedic-trauma/adult-trauma/patella"},
        {"id": "aosr_proximal_tibia", "label": "Proximal Tibia", "path": "/orthopedic-trauma/adult-trauma/proximal-tibia"},
        {"id": "aosr_tibial_shaft", "label": "Tibial Shaft", "path": "/orthopedic-trauma/adult-trauma/tibial-shaft"},
        {"id": "aosr_distal_tibia_malleoli", "label": "Distal Tibia & Malleoli", "path": "/orthopedic-trauma/adult-trauma/distal-tibia"},
        {"id": "aosr_foot", "label": "Foot", "path": "/orthopedic-trauma/adult-trauma/talus"},
    ],
    "spine": [
        {"id": "aosr_spine_cervical", "label": "Spine: Cervical", "path": "/spine/trauma/occipitocervical"},
        {"id": "aosr_spine_thoracolumbar", "label": "Spine: Thoracolumbar", "path": "/spine/trauma/thoracolumbar"},
        {"id": "aosr_spine_sacrum", "label": "Spine: Sacropelvic", "path": "/spine/trauma/sacrum"},
        {"id": "aosr_spine_degenerative", "label": "Spine: Degenerative", "path": "/spine/degenerative"},
        {"id": "aosr_spine_deformities", "label": "Spine: Deformities", "path": "/spine/deformities"},
        {"id": "aosr_spine_tumors", "label": "Spine: Tumors", "path": "/spine/tumors"},
    ],
}

# Additional entry pages for hand sub-regions
HAND_EXTRA_PATHS = [
    "/orthopedic-trauma/adult-trauma/metacarpals",
    "/orthopedic-trauma/adult-trauma/hand-proximal-phalanges",
    "/orthopedic-trauma/adult-trauma/thumb",
]

FOOT_EXTRA_PATHS = [
    "/orthopedic-trauma/adult-trauma/calcaneous",
    "/orthopedic-trauma/adult-trauma/midfoot",
    "/orthopedic-trauma/adult-trauma/metatarsals",
]

MALLEOLI_EXTRA_PATHS = [
    "/orthopedic-trauma/adult-trauma/malleoli",
]

SPINE_CERVICAL_EXTRA = [
    "/spine/trauma/subaxial-cervical",
]


def _fetch_layout(client: httpx.Client, item_path: str) -> Optional[dict]:
    """Fetch Sitecore layout JSON for a given item path."""
    url = (
        f"{BASE_URL}{LAYOUT_API}"
        f"?item={item_path}&sc_lang=en&sc_apikey={SITECORE_API_KEY}&sc_site=aosr"
    )
    try:
        r = client.get(url, timeout=15)
        if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
            return r.json()
    except Exception as exc:
        logger.warning("Failed to fetch layout for %s: %s", item_path, exc)
    return None


def _extract_text(obj: object) -> list[str]:
    """Recursively extract all text content from Sitecore JSON."""
    texts = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("value", "text", "description", "title", "heading", "body", "content") and isinstance(v, str):
                clean = re.sub(r"<[^>]+>", " ", v)
                clean = re.sub(r"&nbsp;", " ", clean)
                clean = re.sub(r"&amp;", "&", clean)
                clean = re.sub(r"\s+", " ", clean).strip()
                if len(clean) > 10:
                    texts.append(clean)
            elif isinstance(v, (dict, list)):
                texts.extend(_extract_text(v))
    elif isinstance(obj, list):
        for item in obj:
            texts.extend(_extract_text(item))
    return texts


def _find_internal_links(obj: object, base_path: str) -> set[str]:
    """Find all internal AO Surgery Reference links in the JSON."""
    links = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("href", "url", "path", "link") and isinstance(v, str):
                if "/orthopedic-trauma/" in v or "/spine/" in v:
                    # Normalize
                    path = v.replace(BASE_URL, "").split("?")[0].split("#")[0]
                    if path.startswith("/"):
                        links.add(path)
            elif isinstance(v, str) and base_path in v:
                matches = re.findall(r"(/(?:orthopedic-trauma|spine)/[^\s\"'<>]+)", v)
                for m in matches:
                    links.add(m.split("?")[0].split("#")[0])
            elif isinstance(v, (dict, list)):
                links.update(_find_internal_links(v, base_path))
    elif isinstance(obj, list):
        for item in obj:
            links.update(_find_internal_links(item, base_path))
    return links


async def scrape_region(region: str) -> dict[str, int]:
    """Scrape all AO Surgery Reference pages for a body region via Sitecore API.

    For each entry point:
    1. Fetch the main page JSON
    2. Discover all sub-page links (fracture types, approaches, treatments)
    3. Fetch each sub-page and extract text
    4. Combine into a single reference file

    Returns {source_id: token_count}
    """
    if region == "all":
        regions = list(AO_ENTRY_PAGES.keys())
    else:
        regions = [region]

    results = {}

    with httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 OsteoTwin/1.0 (Research; Open Access)",
            "Accept": "application/json",
        },
        follow_redirects=True,
    ) as client:
        for reg in regions:
            for entry in AO_ENTRY_PAGES.get(reg, []):
                source_id = entry["id"]
                label = entry["label"]
                base_path = entry["path"]

                logger.info("Scraping %s (%s)...", label, source_id)
                all_texts = []
                visited = set()

                # Collect all entry paths for this source
                entry_paths = [base_path]
                if source_id == "aosr_hand":
                    entry_paths.extend(HAND_EXTRA_PATHS)
                elif source_id == "aosr_foot":
                    entry_paths.extend(FOOT_EXTRA_PATHS)
                elif source_id == "aosr_distal_tibia_malleoli":
                    entry_paths.extend(MALLEOLI_EXTRA_PATHS)
                elif source_id == "aosr_spine_cervical":
                    entry_paths.extend(SPINE_CERVICAL_EXTRA)

                # Phase 1: Fetch entry pages and discover sub-links
                sub_links = set()
                for path in entry_paths:
                    if path in visited:
                        continue
                    visited.add(path)

                    data = _fetch_layout(client, path)
                    if not data:
                        continue

                    texts = _extract_text(data)
                    if texts:
                        all_texts.append(f"\n--- {path} ---\n" + "\n".join(texts))

                    # Discover sub-pages
                    links = _find_internal_links(data, base_path.rsplit("/", 1)[0])
                    sub_links.update(links)

                    time.sleep(0.5)

                # Phase 2: Fetch discovered sub-pages
                for sub_path in sorted(sub_links):
                    if sub_path in visited:
                        continue
                    # Skip non-content paths
                    if any(skip in sub_path for skip in [
                        "/additional-credits", "/SearchResults",
                        "login", "registration",
                    ]):
                        continue
                    visited.add(sub_path)

                    data = _fetch_layout(client, sub_path)
                    if not data:
                        continue

                    texts = _extract_text(data)
                    if texts:
                        all_texts.append(f"\n--- {sub_path} ---\n" + "\n".join(texts))

                    time.sleep(0.5)

                # Save combined text
                if all_texts:
                    full_text = (
                        f"=== AO Surgery Reference - {label} ===\n"
                        f"Source: {BASE_URL}{base_path}\n"
                        f"License: AO Foundation (free open access)\n"
                        f"Pages scraped: {len(visited)}\n"
                        f"{'=' * 60}\n"
                        + "\n".join(all_texts)
                    )

                    out_path = CACHE_DIR / f"{source_id}.txt"
                    out_path.write_text(full_text, encoding="utf-8")

                    meta = (
                        f"source_id: {source_id}\n"
                        f"name: AO Surgery Reference - {label}\n"
                        f"url: {BASE_URL}{base_path}\n"
                        f"license: AO Foundation (free open access)\n"
                        f"downloaded: {time.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
                        f"scraper: sitecore-api\n"
                        f"pages_scraped: {len(visited)}\n"
                        f"size_bytes: {len(full_text.encode('utf-8'))}\n"
                        f"estimated_tokens: {len(full_text) // 4}\n"
                    )
                    (CACHE_DIR / f"{source_id}.meta").write_text(meta, encoding="utf-8")

                    tokens = len(full_text) // 4
                    results[source_id] = tokens
                    logger.info(
                        "  %s: %d pages, %d chars (~%d tokens)",
                        source_id, len(visited), len(full_text), tokens,
                    )
                else:
                    results[source_id] = 0
                    logger.warning("  %s: no content extracted", source_id)

    return results


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
    )
    parser.add_argument("--backup-gcs", action="store_true")
    args = parser.parse_args()

    print(f"Scraping AO Surgery Reference via Sitecore API: {args.region}")
    results = await scrape_region(args.region)

    print(f"\n{'=' * 60}")
    print("Results:")
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
