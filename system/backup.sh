#!/usr/bin/env bash
# OsteoTwin Backup Script — uploads project data to GCS
# Usage: ./system/backup.sh [tag]
# Example: ./system/backup.sh v0.1
#
# DICOM files are NOT included in general backups — they live in the
# encrypted DICOM bucket (gs://<project>-dicom) and are managed separately.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Config
GCP_PROJECT="${GCP_PROJECT_ID:-osteotwin-37f03c}"
BUCKET="gs://${GCP_PROJECT}-data"
TAG="${1:-$(date +%Y%m%d-%H%M%S)}"
BACKUP_DIR="/tmp/osteotwin-backup-${TAG}"

echo "=== OsteoTwin Backup (tag: ${TAG}) ==="

# Create temp backup directory
mkdir -p "${BACKUP_DIR}"

# 1. Database
if [ -f "${PROJECT_ROOT}/planning_server/data/osteotwin.db" ]; then
    cp "${PROJECT_ROOT}/planning_server/data/osteotwin.db" "${BACKUP_DIR}/osteotwin.db"
    echo "[+] Database copied"
fi

# 2. Case data (fracture cases, debate logs, surgical plans)
if [ -d "${PROJECT_ROOT}/planning_server/data/cases" ]; then
    cp -r "${PROJECT_ROOT}/planning_server/data/cases" "${BACKUP_DIR}/cases"
    echo "[+] Case data copied"
fi

# 3. Simulation jobs & results
if [ -d "${PROJECT_ROOT}/simulation_server/jobs" ]; then
    cp -r "${PROJECT_ROOT}/simulation_server/jobs" "${BACKUP_DIR}/jobs"
    echo "[+] Simulation jobs copied"
fi

# 4. Cached meshes (STL/OBJ extracted from DICOM — reproducible, but saves time)
if [ -d "${PROJECT_ROOT}/simulation_server/mesh_cache" ]; then
    CACHE_SIZE=$(du -sm "${PROJECT_ROOT}/simulation_server/mesh_cache" 2>/dev/null | cut -f1)
    if [ "${CACHE_SIZE:-0}" -lt 500 ]; then
        cp -r "${PROJECT_ROOT}/simulation_server/mesh_cache" "${BACKUP_DIR}/mesh_cache"
        echo "[+] Mesh cache copied (${CACHE_SIZE}MB)"
    else
        echo "[!] Mesh cache too large (${CACHE_SIZE}MB) — skipping (regenerable from DICOM)"
    fi
fi

# 5. Environment config (without secrets — secrets are in Secret Manager)
if [ -f "${PROJECT_ROOT}/.env" ]; then
    grep -v '_KEY\|_SECRET\|PASSWORD' "${PROJECT_ROOT}/.env" > "${BACKUP_DIR}/env.nonsecret" || true
    echo "[+] Non-secret env config copied"
fi

# 6. Terraform state
if [ -f "${PROJECT_ROOT}/infra/terraform/terraform.tfstate" ]; then
    cp "${PROJECT_ROOT}/infra/terraform/terraform.tfstate" "${BACKUP_DIR}/terraform.tfstate"
    echo "[+] Terraform state copied"
fi

# Create archive
ARCHIVE="/tmp/osteotwin-backup-${TAG}.tar.gz"
tar -czf "${ARCHIVE}" -C /tmp "osteotwin-backup-${TAG}"
echo "[+] Archive created: ${ARCHIVE}"

# Upload to GCS (Standard storage — hot for 14 days, then auto-tiered)
gsutil cp "${ARCHIVE}" "${BUCKET}/backups/osteotwin-backup-${TAG}.tar.gz"
echo "[+] Uploaded to ${BUCKET}/backups/osteotwin-backup-${TAG}.tar.gz"

# ---------------------------------------------------------------------------
# Storage tiering: move backups older than 14 days to Coldline
# This is handled by GCS lifecycle rules (see Terraform), but we also
# run an explicit rewrite for any that the lifecycle hasn't caught yet.
# ---------------------------------------------------------------------------
echo "[*] Checking for backups to tier to Coldline..."
HOT_CUTOFF=$(date -d "14 days ago" +%Y%m%d 2>/dev/null || date -v-14d +%Y%m%d 2>/dev/null || echo "")

if [ -n "${HOT_CUTOFF}" ]; then
    gsutil ls -l "${BUCKET}/backups/" 2>/dev/null | while read -r line; do
        # Extract filename and check date
        FNAME=$(echo "$line" | awk '{print $NF}')
        if echo "$FNAME" | grep -qP 'osteotwin-backup-(\d{8})'; then
            BACKUP_DATE=$(echo "$FNAME" | grep -oP '\d{8}' | head -1)
            if [ -n "$BACKUP_DATE" ] && [ "$BACKUP_DATE" -lt "$HOT_CUTOFF" ] 2>/dev/null; then
                CURRENT_CLASS=$(gsutil stat "$FNAME" 2>/dev/null | grep "Storage class" | awk '{print $3}')
                if [ "$CURRENT_CLASS" = "STANDARD" ]; then
                    echo "[*] Tiering to Coldline: $FNAME (date: $BACKUP_DATE)"
                    gsutil rewrite -s COLDLINE "$FNAME" 2>/dev/null || true
                fi
            fi
        fi
    done
    echo "[+] Storage tiering complete"
else
    echo "[!] Could not compute cutoff date — skipping tiering"
fi

# Cleanup local temp files
rm -rf "${BACKUP_DIR}" "${ARCHIVE}"
echo "=== Backup complete ==="
