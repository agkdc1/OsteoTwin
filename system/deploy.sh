#!/usr/bin/env bash
# =============================================================================
# OsteoTwin Cloud Deployment Script
# Builds Docker images, pushes to Artifact Registry, deploys to Cloud Run
#
# Usage:
#   bash system/deploy.sh              # deploy all services
#   bash system/deploy.sh planning     # deploy planning server only
#   bash system/deploy.sh simulation   # deploy simulation server only
#   bash system/deploy.sh dashboard    # deploy dashboard only
#   bash system/deploy.sh --cloud-build  # trigger via Cloud Build (CI/CD)
# =============================================================================

set -euo pipefail

# --- Config ---
REGION="${GCP_REGION:-asia-northeast1}"
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
AR_REPO="osteotwin"
TAG="${DEPLOY_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo 'latest')}"

AR_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"

echo "=== OsteoTwin Deploy ==="
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Tag:      ${TAG}"
echo "Registry: ${AR_BASE}"
echo ""

# --- Auth ---
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet 2>/dev/null || true

# --- Functions ---
build_and_push() {
    local service=$1
    local dockerfile=$2
    local image="${AR_BASE}/${service}:${TAG}"
    local latest="${AR_BASE}/${service}:latest"

    echo ">>> Building ${service}..."
    docker build -t "${image}" -t "${latest}" -f "${dockerfile}" .
    echo ">>> Pushing ${service}..."
    docker push "${image}"
    docker push "${latest}"
    echo ">>> ${service} pushed: ${image}"
}

deploy_planning() {
    build_and_push "planning-server" "planning_server/Dockerfile"

    echo ">>> Deploying planning server to Cloud Run..."
    gcloud run deploy osteotwin-planning \
        --image="${AR_BASE}/planning-server:${TAG}" \
        --region="${REGION}" \
        --platform=managed \
        --allow-unauthenticated \
        --memory=1Gi --cpu=2 \
        --min-instances=0 --max-instances=3 \
        --timeout=300 \
        --set-secrets="ANTHROPIC_API_KEY=anthropic-api-key:latest,GEMINI_API_KEY=gemini-api-key:latest,JWT_SECRET_KEY=jwt-secret-key:latest,SIM_API_KEY=sim-api-key:latest,NEO4J_PASSWORD=neo4j-password:latest,ADMIN_PASSWORD=admin-password:latest" \
        --set-env-vars="PLAN_HOST=0.0.0.0,PLAN_PORT=8080,GCP_PROJECT_ID=${PROJECT_ID}" \
        --quiet

    echo ">>> Planning server deployed."
}

deploy_simulation() {
    build_and_push "simulation-server" "simulation_server/Dockerfile"

    echo ">>> Deploying simulation server to Cloud Run..."
    gcloud run deploy osteotwin-simulation \
        --image="${AR_BASE}/simulation-server:${TAG}" \
        --region="${REGION}" \
        --platform=managed \
        --no-allow-unauthenticated \
        --memory=2Gi --cpu=4 \
        --min-instances=0 --max-instances=3 \
        --timeout=300 \
        --set-secrets="SIM_API_KEY=sim-api-key:latest" \
        --set-env-vars="SIM_HOST=0.0.0.0,SIM_PORT=8080,GCP_PROJECT_ID=${PROJECT_ID}" \
        --quiet

    echo ">>> Simulation server deployed."
}

wire_urls() {
    echo ">>> Wiring inter-service URLs..."
    local sim_url
    sim_url=$(gcloud run services describe osteotwin-simulation \
        --region="${REGION}" --format='value(status.url)' 2>/dev/null || echo "")

    if [ -n "${sim_url}" ]; then
        gcloud run services update osteotwin-planning \
            --region="${REGION}" \
            --update-env-vars="SIMULATION_SERVER_URL=${sim_url}" \
            --quiet
        echo ">>> Planning → Simulation wired: ${sim_url}"
    else
        echo ">>> WARNING: Simulation server not found, skipping URL wiring"
    fi
}

deploy_dashboard() {
    build_and_push "dashboard" "dashboard/Dockerfile"

    # Get backend URLs
    local plan_url sim_url
    plan_url=$(gcloud run services describe osteotwin-planning \
        --region="${REGION}" --format='value(status.url)' 2>/dev/null || echo "http://localhost:8200")
    sim_url=$(gcloud run services describe osteotwin-simulation \
        --region="${REGION}" --format='value(status.url)' 2>/dev/null || echo "http://localhost:8300")

    echo ">>> Deploying dashboard to Cloud Run..."
    gcloud run deploy osteotwin-dashboard \
        --image="${AR_BASE}/dashboard:${TAG}" \
        --region="${REGION}" \
        --platform=managed \
        --allow-unauthenticated \
        --memory=256Mi --cpu=1 \
        --min-instances=0 --max-instances=2 \
        --timeout=60 \
        --set-env-vars="PLANNING_API_URL=${plan_url},SIMULATION_API_URL=${sim_url}" \
        --quiet

    echo ">>> Dashboard deployed."
}

# --- Main ---
TARGET="${1:-all}"

case "${TARGET}" in
    planning)
        deploy_planning
        wire_urls
        ;;
    simulation)
        deploy_simulation
        wire_urls
        ;;
    dashboard)
        deploy_dashboard
        ;;
    --cloud-build)
        echo ">>> Submitting to Cloud Build..."
        gcloud builds submit --config=cloudbuild.yaml \
            --substitutions="_REGION=${REGION}" \
            --project="${PROJECT_ID}"
        ;;
    all)
        deploy_planning
        deploy_simulation
        wire_urls
        deploy_dashboard
        ;;
    *)
        echo "Usage: $0 [planning|simulation|dashboard|all|--cloud-build]"
        exit 1
        ;;
esac

echo ""
echo "=== Deploy Complete ==="

# Print URLs
echo ""
echo "Service URLs:"
for svc in osteotwin-planning osteotwin-simulation osteotwin-dashboard; do
    url=$(gcloud run services describe "${svc}" \
        --region="${REGION}" --format='value(status.url)' 2>/dev/null || echo "(not deployed)")
    echo "  ${svc}: ${url}"
done
