#!/usr/bin/env bash
# OsteoTwin DICOM Cache Manager
#
# DICOM files are huge (often 500MB–2GB per case). They are stored in a
# highly encrypted GCS bucket and cached locally only for the active case.
#
# Usage:
#   ./system/dicom_cache.sh push <case_id> <local_dicom_dir>   # Upload DICOM to encrypted bucket
#   ./system/dicom_cache.sh pull <case_id>                      # Download DICOM to local cache
#   ./system/dicom_cache.sh evict [case_id]                     # Remove local cache (all or one)
#   ./system/dicom_cache.sh list                                # List cases in the bucket
#   ./system/dicom_cache.sh status                              # Show local cache usage

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Config
GCP_PROJECT="${GCP_PROJECT_ID:-osteotwin-37f03c}"
DICOM_BUCKET="gs://${GCP_PROJECT}-dicom"
LOCAL_CACHE="${PROJECT_ROOT}/simulation_server/dicom_cache"

# Ensure local cache dir exists
mkdir -p "${LOCAL_CACHE}"

case "${1:-help}" in

push)
    CASE_ID="${2:?Usage: dicom_cache.sh push <case_id> <local_dicom_dir>}"
    LOCAL_DIR="${3:?Provide path to local DICOM directory}"

    if [ ! -d "$LOCAL_DIR" ]; then
        echo "ERROR: Directory not found: $LOCAL_DIR"
        exit 1
    fi

    FILE_COUNT=$(find "$LOCAL_DIR" -name "*.dcm" -o -name "*.DCM" | wc -l)
    DIR_SIZE=$(du -sh "$LOCAL_DIR" | cut -f1)
    echo "=== Uploading DICOM for case ${CASE_ID} ==="
    echo "  Files: ${FILE_COUNT} DICOM files (${DIR_SIZE})"
    echo "  Destination: ${DICOM_BUCKET}/cases/${CASE_ID}/"
    echo "  Encryption: Google-managed (AES-256-GCM)"
    echo ""

    # Upload with parallel composite uploads for speed
    gsutil -m cp -r "${LOCAL_DIR}/" "${DICOM_BUCKET}/cases/${CASE_ID}/"
    echo "[+] Upload complete"

    # Also cache locally
    mkdir -p "${LOCAL_CACHE}/${CASE_ID}"
    cp -r "${LOCAL_DIR}/"* "${LOCAL_CACHE}/${CASE_ID}/" 2>/dev/null || true
    echo "[+] Local cache populated"
    ;;

pull)
    CASE_ID="${2:?Usage: dicom_cache.sh pull <case_id>}"

    # Check if already cached
    if [ -d "${LOCAL_CACHE}/${CASE_ID}" ] && [ "$(ls -A "${LOCAL_CACHE}/${CASE_ID}" 2>/dev/null)" ]; then
        CACHED_SIZE=$(du -sh "${LOCAL_CACHE}/${CASE_ID}" | cut -f1)
        echo "Case ${CASE_ID} already cached locally (${CACHED_SIZE})"
        echo "Use 'evict ${CASE_ID}' first to re-download."
        exit 0
    fi

    echo "=== Downloading DICOM for case ${CASE_ID} ==="
    mkdir -p "${LOCAL_CACHE}/${CASE_ID}"

    # Download with parallel threads
    gsutil -m cp -r "${DICOM_BUCKET}/cases/${CASE_ID}/*" "${LOCAL_CACHE}/${CASE_ID}/"
    CACHED_SIZE=$(du -sh "${LOCAL_CACHE}/${CASE_ID}" | cut -f1)
    echo "[+] Downloaded to ${LOCAL_CACHE}/${CASE_ID} (${CACHED_SIZE})"
    ;;

evict)
    if [ -z "${2:-}" ]; then
        # Evict all
        TOTAL_SIZE=$(du -sh "${LOCAL_CACHE}" 2>/dev/null | cut -f1)
        echo "=== Evicting ALL local DICOM cache (${TOTAL_SIZE}) ==="
        read -p "Are you sure? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "${LOCAL_CACHE:?}"/*
            echo "[+] Cache cleared"
        else
            echo "Cancelled"
        fi
    else
        CASE_ID="$2"
        if [ -d "${LOCAL_CACHE}/${CASE_ID}" ]; then
            SIZE=$(du -sh "${LOCAL_CACHE}/${CASE_ID}" | cut -f1)
            rm -rf "${LOCAL_CACHE:?}/${CASE_ID:?}"
            echo "[+] Evicted case ${CASE_ID} (${SIZE} freed)"
        else
            echo "Case ${CASE_ID} not in local cache"
        fi
    fi
    ;;

list)
    echo "=== DICOM cases in encrypted bucket ==="
    gsutil ls "${DICOM_BUCKET}/cases/" 2>/dev/null | sed 's|.*/cases/||;s|/$||' | grep -v '^$' || echo "No cases found"
    echo ""
    echo "=== Local cache ==="
    if [ -d "$LOCAL_CACHE" ] && [ "$(ls -A "$LOCAL_CACHE" 2>/dev/null)" ]; then
        for dir in "${LOCAL_CACHE}"/*/; do
            case_id=$(basename "$dir")
            size=$(du -sh "$dir" | cut -f1)
            echo "  ${case_id}: ${size}"
        done
    else
        echo "  (empty)"
    fi
    ;;

status)
    echo "=== DICOM Cache Status ==="
    echo "  Bucket: ${DICOM_BUCKET}"
    echo "  Local cache: ${LOCAL_CACHE}"
    if [ -d "$LOCAL_CACHE" ]; then
        TOTAL=$(du -sh "$LOCAL_CACHE" 2>/dev/null | cut -f1)
        COUNT=$(find "$LOCAL_CACHE" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
        echo "  Cached cases: ${COUNT}"
        echo "  Total size: ${TOTAL}"
    else
        echo "  (no cache directory)"
    fi
    ;;

*)
    echo "OsteoTwin DICOM Cache Manager"
    echo ""
    echo "Usage:"
    echo "  dicom_cache.sh push <case_id> <local_dir>  Upload DICOM to encrypted bucket"
    echo "  dicom_cache.sh pull <case_id>               Download DICOM to local cache"
    echo "  dicom_cache.sh evict [case_id]              Clear local cache (all or one)"
    echo "  dicom_cache.sh list                         List cases in bucket + local"
    echo "  dicom_cache.sh status                       Show cache stats"
    ;;
esac
