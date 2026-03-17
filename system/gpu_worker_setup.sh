#!/bin/bash
# OsteoTwin L4 GPU Worker Setup
#
# Installs SOFA Framework, Python deps, and THUMS data on a fresh
# GCP g2-standard-8 + NVIDIA L4 instance.
#
# Usage (on the worker VM):
#   curl -sL https://raw.githubusercontent.com/agkdc1/OsteoTwin/main/system/gpu_worker_setup.sh | bash
#
# Or manually after SSH:
#   bash system/gpu_worker_setup.sh

set -euo pipefail

echo "=== OsteoTwin GPU Worker Setup ==="
echo "Instance: $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'not detected yet')"

PROJECT_ID="${GCP_PROJECT_ID:-osteotwin-37f03c}"
BUCKET="gs://${PROJECT_ID}-data"

# --- 1. System packages ---
echo "[1/7] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-pip python3-venv git wget unzip \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxrender1 libxext6 \
    libgomp1

# --- 2. NVIDIA driver check ---
echo "[2/7] Checking NVIDIA driver..."
if ! nvidia-smi &>/dev/null; then
    echo "Installing NVIDIA driver..."
    sudo apt-get install -y -qq nvidia-driver-550
    echo "Driver installed. Reboot may be required."
fi
nvidia-smi

# --- 3. Clone project ---
echo "[3/7] Cloning OsteoTwin..."
mkdir -p /opt/osteotwin
cd /opt/osteotwin
if [ ! -d ".git" ]; then
    git clone https://github.com/agkdc1/OsteoTwin.git .
else
    git pull
fi

# --- 4. Python environment ---
echo "[4/7] Setting up Python environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r planning_server/requirements.txt
pip install -r simulation_server/requirements.txt

# --- 5. SOFA Framework ---
echo "[5/7] Installing SOFA Framework..."
SOFA_VERSION="v24.12.00"
SOFA_DIR="/opt/sofa"

if [ ! -d "$SOFA_DIR" ]; then
    mkdir -p /tmp/sofa_install
    cd /tmp/sofa_install

    # Download SOFA binary release
    wget -q "https://github.com/sofa-framework/sofa/releases/download/${SOFA_VERSION}/SOFA_${SOFA_VERSION}_Linux.zip" \
        -O sofa.zip || {
        echo "SOFA binary download failed. Trying conda fallback..."
        pip install sofapython3 || echo "WARNING: SOFA not available. Spring-mass fallback will be used."
    }

    if [ -f sofa.zip ]; then
        unzip -q sofa.zip -d /opt/
        mv /opt/SOFA_* "$SOFA_DIR"
        echo "SOFA installed to $SOFA_DIR"
    fi

    cd /opt/osteotwin
    rm -rf /tmp/sofa_install
fi

# Add SOFA to path
if [ -d "$SOFA_DIR" ]; then
    export SOFA_ROOT="$SOFA_DIR"
    export PATH="$SOFA_DIR/bin:$PATH"
    export PYTHONPATH="$SOFA_DIR/plugins/SofaPython3/lib/python3/site-packages:$PYTHONPATH"
    echo "export SOFA_ROOT=$SOFA_DIR" >> /opt/osteotwin/.venv/bin/activate
    echo "export PATH=$SOFA_DIR/bin:\$PATH" >> /opt/osteotwin/.venv/bin/activate
    echo "export PYTHONPATH=$SOFA_DIR/plugins/SofaPython3/lib/python3/site-packages:\$PYTHONPATH" >> /opt/osteotwin/.venv/bin/activate
fi

# --- 6. THUMS data ---
echo "[6/7] Downloading THUMS data from GCS..."
cd /opt/osteotwin
gcloud storage cp -r "${BUCKET}/thums_v71/" fea/thums/ 2>/dev/null || echo "THUMS raw data not available in GCS"
gcloud storage cp -r "${BUCKET}/thums_v71_parsed/" fea/thums_output/ 2>/dev/null || echo "THUMS parsed data not available in GCS"

# --- 7. Secrets ---
echo "[7/7] Fetching secrets..."
bash system/fetch_secrets.sh "$PROJECT_ID" 2>/dev/null || echo "Secrets fetch skipped (manual: bash system/fetch_secrets.sh)"

# --- Verify ---
echo ""
echo "=== Setup Complete ==="
echo "Python: $(python --version)"
echo "GPU:    $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'N/A')"
echo "SOFA:   $(runSofa --version 2>/dev/null || echo 'not installed (spring-mass fallback)')"
echo "THUMS:  $(ls fea/thums_output/ 2>/dev/null | wc -l) subject(s) parsed"
echo ""
echo "To start servers:"
echo "  source .venv/bin/activate"
echo "  python -m simulation_server.app.main  # Port 8300"
echo ""
echo "To run SOFA knee joint FEA:"
echo "  python -c \"from simulation_server.app.soft_tissue.sofa_scene_thums import *; print(generate_knee_scene('AM50', valgus_deg=5))\""
