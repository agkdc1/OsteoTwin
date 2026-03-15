"""Downloads and preprocesses open access reference texts.

Handles PDF extraction, HTML scraping, and text cleanup.
Stores processed text files in a local cache directory and
backs them up to GCS.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Optional

import httpx

from .. import config
from .sources import ReferenceSource, SourceType

logger = logging.getLogger("osteotwin.knowledge_cache.downloader")

# Local cache directory (git-ignored, backed up to GCS)
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# GCS bucket for knowledge backup
GCS_BUCKET = f"{config.GCP_PROJECT_ID}-data" if config.GCP_PROJECT_ID else ""
GCS_PREFIX = "knowledge_cache/"


def _text_file_path(source_id: str) -> Path:
    """Path to the processed text file for a source."""
    return CACHE_DIR / f"{source_id}.txt"


def _meta_file_path(source_id: str) -> Path:
    """Path to metadata file for a source."""
    return CACHE_DIR / f"{source_id}.meta"


def is_cached(source_id: str) -> bool:
    """Check if a source has been downloaded and processed."""
    return _text_file_path(source_id).exists()


def get_cached_text(source_id: str) -> Optional[str]:
    """Read cached text for a source. Returns None if not cached."""
    path = _text_file_path(source_id)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


async def download_source(source: ReferenceSource, force: bool = False) -> str:
    """Download and preprocess a reference source.

    Returns the processed text content.
    """
    if not force and is_cached(source.id):
        logger.info("Source '%s' already cached, skipping download", source.id)
        return get_cached_text(source.id)

    logger.info("Downloading source: %s (%s)", source.name, source.url)

    try:
        if source.source_type == SourceType.pdf:
            text = await _download_pdf(source)
        elif source.source_type == SourceType.html:
            text = await _download_html(source)
        else:
            logger.warning("Unsupported source type: %s", source.source_type)
            return ""

        # Clean and normalize
        text = _clean_text(text)

        # Add source header
        header = (
            f"=== {source.name} ===\n"
            f"Source: {source.url}\n"
            f"License: {source.license}\n"
            f"{'=' * 60}\n\n"
        )
        text = header + text

        # Save locally
        path = _text_file_path(source.id)
        path.write_text(text, encoding="utf-8")

        # Save metadata
        meta = (
            f"source_id: {source.id}\n"
            f"name: {source.name}\n"
            f"url: {source.url}\n"
            f"license: {source.license}\n"
            f"downloaded: {time.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
            f"size_bytes: {len(text.encode('utf-8'))}\n"
            f"estimated_tokens: {len(text) // 4}\n"
            f"checksum: {hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}\n"
        )
        _meta_file_path(source.id).write_text(meta, encoding="utf-8")

        logger.info(
            "Source '%s' cached: %d chars (~%d tokens)",
            source.id, len(text), len(text) // 4,
        )
        return text

    except Exception as exc:
        logger.error("Failed to download '%s': %s", source.id, exc)
        return ""


async def _download_pdf(source: ReferenceSource) -> str:
    """Download a PDF and extract text."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OsteoTwin/1.0 (Research; Open Access Retrieval)",
    }
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True, headers=headers) as client:
        resp = await client.get(source.url)
        resp.raise_for_status()
        pdf_bytes = resp.content

    # Try PyMuPDF (fitz) first, fall back to pdfminer
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        pass

    try:
        from pdfminer.high_level import extract_text
        from io import BytesIO

        return extract_text(BytesIO(pdf_bytes))
    except ImportError:
        pass

    logger.warning("No PDF extractor available. Install PyMuPDF: pip install pymupdf")
    return f"[PDF content from {source.url} — install pymupdf to extract]"


async def _download_html(source: ReferenceSource) -> str:
    """Download HTML page(s) and extract text content."""
    urls = source.sub_urls if source.sub_urls else [source.url]
    all_text = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OsteoTwin/1.0 (Research; Open Access Retrieval)",
        "Accept": "text/html,application/xhtml+xml",
    }

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers=headers) as client:
        for url in urls:
            try:
                # NCBI/PMC: use E-Utilities API for full text
                if "ncbi.nlm.nih.gov/books/" in url:
                    text = await _fetch_ncbi_book(client, url)
                elif "pmc.ncbi.nlm.nih.gov" in url:
                    text = await _fetch_pmc_article(client, url)
                else:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    text = _html_to_text(resp.text)

                if text.strip():
                    all_text.append(text)

                # Rate limit: be polite to public APIs
                time.sleep(1.0)

            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", url, exc)

    return "\n\n---\n\n".join(all_text)


async def _fetch_ncbi_book(client: httpx.AsyncClient, url: str) -> str:
    """Fetch NCBI Bookshelf content via E-Utilities efetch API."""
    import re as _re

    # Extract book ID (NBKxxxxxx) from URL
    match = _re.search(r"NBK(\d+)", url)
    if not match:
        logger.warning("Could not extract NBK ID from %s", url)
        return ""

    nbk_id = f"NBK{match.group(1)}"
    # Use efetch to get full text in plain text format
    api_url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=books&id={nbk_id}&rettype=full&retmode=text"
    )
    resp = await client.get(api_url)

    if resp.status_code == 200 and len(resp.text) > 200:
        return resp.text

    # Fallback: try fetching the printable version
    printable_url = url.rstrip("/") + "/?report=printable"
    resp = await client.get(printable_url)
    if resp.status_code == 200:
        return _html_to_text(resp.text)

    return ""


async def _fetch_pmc_article(client: httpx.AsyncClient, url: str) -> str:
    """Fetch PMC article via E-Utilities API."""
    import re as _re

    # Extract PMC ID from URL
    match = _re.search(r"PMC(\d+)", url)
    if not match:
        return ""

    pmc_id = f"PMC{match.group(1)}"
    api_url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pmc&id={pmc_id}&rettype=full&retmode=text"
    )
    resp = await client.get(api_url)

    if resp.status_code == 200 and len(resp.text) > 200:
        return resp.text

    return ""


def _html_to_text(html: str) -> str:
    """Convert HTML to clean text, preserving structure."""
    # Try BeautifulSoup first
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Remove script, style, nav, footer elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Try to find main content
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", class_=re.compile(r"content|main|article"))
            or soup.find("body")
        )

        if main:
            return main.get_text(separator="\n", strip=True)
        return soup.get_text(separator="\n", strip=True)

    except ImportError:
        pass

    # Fallback: regex-based HTML stripping
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    return text


def _clean_text(text: str) -> str:
    """Clean and normalize extracted text for prompt usage."""
    # Collapse excessive whitespace
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r" {3,}", " ", text)
    # Remove common artifacts
    text = re.sub(r"(Advertisement|Cookie Policy|Privacy Policy|Accept All).*?\n", "", text)
    # Remove very short lines (likely navigation)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) < 3 and stripped not in ("", "-", "*"):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


async def download_all_sources(
    sources: list[ReferenceSource],
    force: bool = False,
) -> dict[str, int]:
    """Download all sources. Returns {source_id: token_count}."""
    results = {}
    for source in sources:
        text = await download_source(source, force=force)
        results[source.id] = len(text) // 4 if text else 0
    return results


def backup_to_gcs() -> int:
    """Backup all cached knowledge files to GCS. Returns file count."""
    if not GCS_BUCKET:
        logger.warning("GCP_PROJECT_ID not set — skipping GCS backup")
        return 0

    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        count = 0

        for path in CACHE_DIR.glob("*"):
            if path.is_file():
                blob_name = f"{GCS_PREFIX}{path.name}"
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(str(path))
                count += 1

        logger.info("Backed up %d files to gs://%s/%s", count, GCS_BUCKET, GCS_PREFIX)
        return count

    except Exception as exc:
        logger.error("GCS backup failed: %s", exc)
        return 0


def restore_from_gcs() -> int:
    """Restore knowledge cache from GCS. Returns file count."""
    if not GCS_BUCKET:
        logger.warning("GCP_PROJECT_ID not set — skipping GCS restore")
        return 0

    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        count = 0

        blobs = bucket.list_blobs(prefix=GCS_PREFIX)
        for blob in blobs:
            filename = blob.name.replace(GCS_PREFIX, "")
            if filename:
                local_path = CACHE_DIR / filename
                blob.download_to_filename(str(local_path))
                count += 1

        logger.info("Restored %d files from gs://%s/%s", count, GCS_BUCKET, GCS_PREFIX)
        return count

    except Exception as exc:
        logger.error("GCS restore failed: %s", exc)
        return 0
