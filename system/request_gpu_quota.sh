#!/bin/bash
# Request increased GPU quotas for OsteoTwin project
# Run this after the project has been active for 48+ hours
#
# Target: NVIDIA T4 quota increase in asia-northeast1 (Tokyo)
# Current: 1 T4, 1 L4 (confirmed 2026-03-17)
# Request: 4 T4 for parallel simulation workers
#
# Schedule: Run on 2026-03-19 (48 hours after project re-activation)
#
# Usage:
#   bash system/request_gpu_quota.sh          # request T4 increase
#   bash system/request_gpu_quota.sh status   # check current quotas

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-osteotwin-37f03c}"
REGION="asia-northeast1"

if [ "${1:-}" = "status" ]; then
    echo "=== GPU Quota Status for $PROJECT_ID in $REGION ==="
    gcloud compute regions describe "$REGION" \
        --project="$PROJECT_ID" \
        --format="table(quotas.metric,quotas.limit,quotas.usage)" \
        --filter="quotas.metric:NVIDIA" 2>/dev/null || \
    gcloud compute regions describe "$REGION" \
        --project="$PROJECT_ID" \
        --format="value(quotas)" | tr ';' '\n' | grep -i nvidia
    exit 0
fi

echo "=== Requesting T4 GPU Quota Increase ==="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo ""

# Method 1: Use the Cloud Quotas API (preferred, programmatic)
# Enable the API first
gcloud services enable cloudquotas.googleapis.com --project="$PROJECT_ID" 2>/dev/null || true

echo "Requesting NVIDIA_T4_GPUS increase to 4..."
gcloud beta quotas preferences create \
    --project="$PROJECT_ID" \
    --service="compute.googleapis.com" \
    --quota-id="NVIDIA-T4-GPUS-per-project-region" \
    --preferred-value=4 \
    --dimensions="region=$REGION" \
    --justification="OsteoTwin surgical simulation: SOFA FEA soft-tissue + TotalSegmentator bone extraction. Need 4 T4s for parallel patient-specific simulation workers." \
    2>&1 || echo "Note: quota request may need to be submitted via Console if API method fails."

echo ""
echo "Requesting PREEMPTIBLE_NVIDIA_T4_GPUS increase to 4..."
gcloud beta quotas preferences create \
    --project="$PROJECT_ID" \
    --service="compute.googleapis.com" \
    --quota-id="PREEMPTIBLE-NVIDIA-T4-GPUS-per-project-region" \
    --preferred-value=4 \
    --dimensions="region=$REGION" \
    --justification="OsteoTwin surgical simulation: Spot GPU workers for cost-efficient FEA and segmentation. Need 4 preemptible T4s." \
    2>&1 || echo "Note: preemptible quota request may need Console submission."

echo ""
echo "Also requesting NVIDIA_L4_GPUS increase to 2..."
gcloud beta quotas preferences create \
    --project="$PROJECT_ID" \
    --service="compute.googleapis.com" \
    --quota-id="NVIDIA-L4-GPUS-per-project-region" \
    --preferred-value=2 \
    --dimensions="region=$REGION" \
    --justification="OsteoTwin surgical simulation: L4 for primary SOFA FEA worker (24GB VRAM for large meshes)." \
    2>&1 || echo "Note: L4 quota request may need Console submission."

echo ""
echo "=== Quota requests submitted ==="
echo "Check status: bash system/request_gpu_quota.sh status"
echo "Console:      https://console.cloud.google.com/iam-admin/quotas?project=$PROJECT_ID"
echo ""
echo "Fallback: If API requests fail, submit manually at the Console URL above."
echo "Search for 'NVIDIA' and request increases for T4 and L4 in $REGION."
