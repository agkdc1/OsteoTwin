# Planning Server — Cloud Run container
# Multi-stage build: slim Python 3.13 (compatible with google-cloud-storage SDK)
FROM python:3.13-slim AS base

# System deps for PyMuPDF, lxml, and crypto
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache layer)
COPY planning_server/requirements.txt /app/planning_server/requirements.txt
RUN pip install --no-cache-dir -r /app/planning_server/requirements.txt

# Copy shared schemas (single source of truth)
COPY shared/ /app/shared/

# Copy planning server code
COPY planning_server/ /app/planning_server/

# Create data dirs (ephemeral on Cloud Run — use Firestore/GCS for persistence)
RUN mkdir -p /app/planning_server/data \
    /app/planning_server/static \
    /app/planning_server/knowledge_data

# Cloud Run uses PORT env var (default 8080)
ENV PORT=8080
ENV PLAN_HOST=0.0.0.0
ENV PLAN_PORT=8080

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "planning_server.app.main:app", \
     "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
