#!/usr/bin/env bash
# OsteoTwin Restore Script — downloads backup from GCS and restores
# Usage: ./system/restore.sh <tag>
# Example: ./system/restore.sh 20260315-120000
# List available: ./system/restore.sh --list

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Config
GCP_PROJECT="${GCP_PROJECT_ID:-osteotwin-37f03c}"
BUCKET="gs://${GCP_PROJECT}-data"

if [ "${1:-}" = "--list" ]; then
    echo "=== Available backups ==="
    gsutil ls "${BUCKET}/backups/" 2>/dev/null || echo "No backups found"
    exit 0
fi

TAG="${1:?Usage: restore.sh <tag> or restore.sh --list}"
ARCHIVE="/tmp/osteotwin-backup-${TAG}.tar.gz"
RESTORE_DIR="/tmp/osteotwin-backup-${TAG}"

echo "=== OsteoTwin Restore (tag: ${TAG}) ==="

# Download from GCS
gsutil cp "${BUCKET}/backups/osteotwin-backup-${TAG}.tar.gz" "${ARCHIVE}"
echo "[+] Downloaded backup"

# Extract
tar -xzf "${ARCHIVE}" -C /tmp
echo "[+] Extracted archive"

# 1. Database
if [ -f "${RESTORE_DIR}/osteotwin.db" ]; then
    mkdir -p "${PROJECT_ROOT}/planning_server/data"
    cp "${RESTORE_DIR}/osteotwin.db" "${PROJECT_ROOT}/planning_server/data/osteotwin.db"
    echo "[+] Database restored"
fi

# 2. Case data
if [ -d "${RESTORE_DIR}/cases" ]; then
    mkdir -p "${PROJECT_ROOT}/planning_server/data"
    cp -r "${RESTORE_DIR}/cases" "${PROJECT_ROOT}/planning_server/data/cases"
    echo "[+] Case data restored"
fi

# 3. Simulation jobs
if [ -d "${RESTORE_DIR}/jobs" ]; then
    cp -r "${RESTORE_DIR}/jobs" "${PROJECT_ROOT}/simulation_server/jobs"
    echo "[+] Simulation jobs restored"
fi

# 4. Mesh cache
if [ -d "${RESTORE_DIR}/mesh_cache" ]; then
    cp -r "${RESTORE_DIR}/mesh_cache" "${PROJECT_ROOT}/simulation_server/mesh_cache"
    echo "[+] Mesh cache restored"
fi

# 5. Terraform state
if [ -f "${RESTORE_DIR}/terraform.tfstate" ]; then
    mkdir -p "${PROJECT_ROOT}/infra/terraform"
    cp "${RESTORE_DIR}/terraform.tfstate" "${PROJECT_ROOT}/infra/terraform/terraform.tfstate"
    echo "[+] Terraform state restored"
fi

# Cleanup
rm -rf "${RESTORE_DIR}" "${ARCHIVE}"

echo "=== Restore complete ==="
echo ""
echo "To restore secrets, run:"
echo "  bash system/fetch_secrets.sh ${GCP_PROJECT}"
echo ""
echo "To restore DICOM files for a case, run:"
echo "  bash system/dicom_cache.sh pull <case_id>"
