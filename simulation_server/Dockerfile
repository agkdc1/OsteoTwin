# Simulation Server — Cloud Run container
# Uses Python 3.13 with VTK, trimesh, and collision detection libs
FROM python:3.13-slim AS base

# System deps for VTK, trimesh, FCL, and spatial indexing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libspatialindex-dev \
    libfcl-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache layer)
COPY simulation_server/requirements.txt /app/simulation_server/requirements.txt
RUN pip install --no-cache-dir -r /app/simulation_server/requirements.txt

# Copy shared schemas
COPY shared/ /app/shared/

# Copy simulation server code
COPY simulation_server/ /app/simulation_server/

# Create working dirs (ephemeral — heavy data lives in GCS)
RUN mkdir -p /app/simulation_server/jobs \
    /app/simulation_server/mesh_cache \
    /app/simulation_server/dicom_cache

# Cloud Run uses PORT env var
ENV PORT=8080
ENV SIM_HOST=0.0.0.0
ENV SIM_PORT=8080

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "simulation_server.app.main:app", \
     "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
