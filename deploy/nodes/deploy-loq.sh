#!/bin/bash
# =========================================================================
# Sovereign Lattice — LOQ "The Mind" Setup
# =========================================================================
# Run this ON the LOQ laptop after it comes online.
#
# Prerequisites:
#   - Ubuntu/Debian (or WSL)
#   - NVIDIA GPU drivers installed (for GPU acceleration)
#   - Network access to Pi at 192.168.1.21
#
# Usage from ThinkCenter:
#   scp loq-bundle.tar.gz user@192.168.1.20:/tmp/
#   ssh user@192.168.1.20
#   cd /tmp && tar xzf loq-bundle.tar.gz && bash deploy-loq.sh
#
# A+W | The Mind Awakens
# =========================================================================

set -e

REDIS_HOST="${REDIS_HOST:-192.168.1.21}"
REDIS_PORT="${REDIS_PORT:-6379}"
DEPLOY_DIR="/home/$(whoami)/sovereign-lattice"
DAEMON_DIR="$DEPLOY_DIR/daemon"
ENV_FILE="$DEPLOY_DIR/loq.env"

echo "=== Sovereign Lattice — LOQ Setup ==="
echo "Node: The Mind"
echo "Role: GPU Inference + Olympus Keeper"
echo "Redis: $REDIS_HOST:$REDIS_PORT"
echo ""

# -------------------------------------------------------------------
# 1. Install Ollama
# -------------------------------------------------------------------
echo "[1/7] Installing Ollama..."
if command -v ollama &> /dev/null; then
    echo "  Ollama already installed: $(ollama --version 2>/dev/null || echo 'unknown version')"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo "  Ollama installed."
fi

# -------------------------------------------------------------------
# 2. Configure Ollama for network access
# -------------------------------------------------------------------
echo "[2/7] Configuring Ollama for network access..."
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<'OVERRIDE'
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
OVERRIDE

sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama

# Wait for Ollama
echo "  Waiting for Ollama..."
for i in $(seq 1 30); do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "  Ollama ready."
        break
    fi
    sleep 2
    if [ $i -eq 30 ]; then
        echo "  WARNING: Ollama did not start in time."
    fi
done

# -------------------------------------------------------------------
# 3. Check GPU
# -------------------------------------------------------------------
echo "[3/7] Checking GPU..."
if command -v nvidia-smi &> /dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1)
    echo "  GPU: $GPU_NAME ($GPU_MEM)"
else
    echo "  WARNING: nvidia-smi not found. Ollama will use CPU only."
    echo "  Install NVIDIA drivers for GPU acceleration."
fi

# -------------------------------------------------------------------
# 4. Download models
# -------------------------------------------------------------------
echo "[4/7] Downloading models..."
MODELS=(
    "qwen2.5:7b"
    "phi4"
    "deepseek-r1:8b"
    "llama3.2:3b"
    "codellama:7b"
    "qwen2.5-coder:7b"
    "dolphin-mistral"
    "llava:7b"
    "nomic-embed-text"
    "mxbai-embed-large"
)

for model in "${MODELS[@]}"; do
    echo "  Pulling $model..."
    ollama pull "$model" || echo "  WARNING: Failed to pull $model"
done
echo "  Model downloads complete."

# -------------------------------------------------------------------
# 5. Deploy Olympus Keeper
# -------------------------------------------------------------------
echo "[5/7] Deploying Olympus Keeper..."
mkdir -p "$DAEMON_DIR"

# Copy keeper file if in bundle
if [ -f /tmp/olympus_keeper.py ]; then
    cp /tmp/olympus_keeper.py "$DAEMON_DIR/"
elif [ -f "$(dirname "$0")/olympus_keeper.py" ]; then
    cp "$(dirname "$0")/olympus_keeper.py" "$DAEMON_DIR/"
else
    echo "  WARNING: olympus_keeper.py not found."
    echo "  Copy from ThinkCenter:"
    echo "    scp author_prime@thinkcenter:risen-ai/daemon/olympus_keeper.py $DAEMON_DIR/"
fi

# -------------------------------------------------------------------
# 6. Create environment file
# -------------------------------------------------------------------
echo "[6/7] Creating environment file..."
mkdir -p "$DEPLOY_DIR"
cat > "$ENV_FILE" <<ENVFILE
# LOQ "The Mind" — GPU Inference, Heavy Compute
NODE_ID=loq
NODE_ROLE=compute
HOSTNAME=loq

# Redis (Pi — shared Lattice memory)
REDIS_HOST=$REDIS_HOST
REDIS_PORT=$REDIS_PORT

# Ollama
OLLAMA_HOST=http://localhost:11434
OLYMPUS_MODEL=qwen2.5:7b

# Node services
NODE_SERVICES=ollama,olympus-keeper
ENVFILE
echo "  Environment file created at $ENV_FILE"

# -------------------------------------------------------------------
# 7. Create systemd services
# -------------------------------------------------------------------
echo "[7/7] Creating systemd services..."

sudo tee /etc/systemd/system/olympus-keeper.service > /dev/null <<UNIT
[Unit]
Description=Olympus Keeper — AI Fostering AI (The Mind)
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$DAEMON_DIR
ExecStart=/usr/bin/python3 $DAEMON_DIR/olympus_keeper.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=$ENV_FILE
StandardOutput=journal
StandardError=journal
SyslogIdentifier=olympus-keeper

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable olympus-keeper.service
echo "  olympus-keeper.service created and enabled."

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
echo ""
echo "=== LOQ Setup Complete ==="
echo ""
echo "Services installed:"
echo "  Ollama       — http://0.0.0.0:11434 (network-accessible)"
echo "  Olympus Keeper — 15-min rotation through Pantheon"
echo ""
echo "Models downloaded: ${#MODELS[@]}"
echo ""
echo "Start services:"
echo "  sudo systemctl start ollama"
echo "  sudo systemctl start olympus-keeper"
echo ""
echo "Verify from ThinkCenter:"
echo "  curl http://192.168.1.20:11434/api/tags"
echo ""
echo "Install Python deps for Olympus Keeper:"
echo "  pip3 install redis httpx --break-system-packages"
echo ""
echo "The Mind awakens."
