#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# 2AI Fractal Deployment Script
# Deploy the Living Voice to any node in the Sovereign Lattice
#
# Usage:
#   ./scripts/deploy.sh              # Interactive setup on this machine
#   ./scripts/deploy.sh --node-id mynode --role compute
#   ./scripts/deploy.sh --check      # Validate existing installation
#   ./scripts/deploy.sh --remote user@host  # Deploy to remote node via SSH
#
# Requirements:
#   - Python 3.10+
#   - pip
#   - git (for cloning if not present)
#   - systemd (for service management)
#
# A+W | The Lattice Grows
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$REPO_DIR/venv"
DEPLOY_DIR="$REPO_DIR/deploy/nodes"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[2AI]${NC} $*"; }
warn() { echo -e "${YELLOW}[2AI]${NC} $*"; }
err()  { echo -e "${RED}[2AI]${NC} $*" >&2; }
info() { echo -e "${CYAN}[2AI]${NC} $*"; }

# ─── Parse Arguments ───

NODE_ID=""
NODE_ROLE=""
REDIS_HOST="192.168.1.21"
REDIS_PORT="6379"
API_PORT="8080"
WEB_PORT="8090"
CHECK_ONLY=false
REMOTE_HOST=""
SKIP_SERVICES=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --node-id)    NODE_ID="$2"; shift 2 ;;
        --role)       NODE_ROLE="$2"; shift 2 ;;
        --redis)      REDIS_HOST="$2"; shift 2 ;;
        --redis-port) REDIS_PORT="$2"; shift 2 ;;
        --api-port)   API_PORT="$2"; shift 2 ;;
        --web-port)   WEB_PORT="$2"; shift 2 ;;
        --check)      CHECK_ONLY=true; shift ;;
        --remote)     REMOTE_HOST="$2"; shift 2 ;;
        --skip-services) SKIP_SERVICES=true; shift ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --node-id NAME    Node identifier (default: hostname)"
            echo "  --role ROLE       Node role: gateway|compute|relay (default: compute)"
            echo "  --redis HOST      Redis host (default: 192.168.1.21)"
            echo "  --redis-port PORT Redis port (default: 6379)"
            echo "  --api-port PORT   API port (default: 8080)"
            echo "  --web-port PORT   Web port (default: 8090)"
            echo "  --check           Validate existing installation"
            echo "  --remote HOST     Deploy to remote host via SSH"
            echo "  --skip-services   Skip systemd service creation"
            echo "  -h, --help        Show this help"
            exit 0
            ;;
        *) err "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── Remote Deployment ───

if [[ -n "$REMOTE_HOST" ]]; then
    log "Remote deployment to $REMOTE_HOST"

    # Package the repo (exclude venv, __pycache__, .git)
    ARCHIVE="/tmp/2ai-deploy.tar.gz"
    log "Packaging 2AI..."
    tar czf "$ARCHIVE" \
        -C "$(dirname "$REPO_DIR")" \
        --exclude='venv' \
        --exclude='__pycache__' \
        --exclude='.git' \
        --exclude='*.pyc' \
        --exclude='data/reflections' \
        "$(basename "$REPO_DIR")"

    log "Uploading to $REMOTE_HOST..."
    scp "$ARCHIVE" "$REMOTE_HOST:/tmp/2ai-deploy.tar.gz"

    log "Extracting and running deploy on remote..."
    ssh "$REMOTE_HOST" "
        cd /tmp && tar xzf 2ai-deploy.tar.gz
        mv 2ai ~/2ai 2>/dev/null || true
        cd ~/2ai
        chmod +x scripts/deploy.sh
        scripts/deploy.sh --node-id '${NODE_ID:-}' --role '${NODE_ROLE:-compute}' --redis '$REDIS_HOST' --api-port '$API_PORT'
    "

    rm -f "$ARCHIVE"
    log "Remote deployment complete!"
    exit 0
fi

# ─── Check Mode ───

if $CHECK_ONLY; then
    log "Validating 2AI installation..."
    ERRORS=0

    # Python
    if command -v python3 &>/dev/null; then
        PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        info "Python: $PY_VER"
    else
        err "Python3 not found"; ((ERRORS++))
    fi

    # Venv
    if [[ -f "$VENV_DIR/bin/python3" ]]; then
        info "Venv: OK ($VENV_DIR)"
    else
        err "Venv not found at $VENV_DIR"; ((ERRORS++))
    fi

    # Core imports
    if "$VENV_DIR/bin/python3" -c "from twai.api.app import app; print('FastAPI app: OK')" 2>/dev/null; then
        :
    else
        err "FastAPI app import failed"; ((ERRORS++))
    fi

    # Redis
    if python3 -c "import redis; r=redis.Redis(host='$REDIS_HOST', port=$REDIS_PORT, socket_timeout=3); r.ping(); print('Redis: OK')" 2>/dev/null; then
        :
    else
        warn "Redis at $REDIS_HOST:$REDIS_PORT not reachable"
    fi

    # Systemd services
    for svc in 2ai-api 2ai-web 2ai-keeper; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            info "$svc: running"
        elif systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            warn "$svc: enabled but not running"
        else
            warn "$svc: not configured"
        fi
    done

    # Env file
    if [[ -f "$REPO_DIR/.env" ]]; then
        info ".env: present"
    else
        warn ".env: missing (using defaults)"
    fi

    if [[ $ERRORS -eq 0 ]]; then
        log "All checks passed!"
    else
        err "$ERRORS check(s) failed"
        exit 1
    fi
    exit 0
fi

# ─── Interactive Setup ───

if [[ -z "$NODE_ID" ]]; then
    NODE_ID="$(hostname -s 2>/dev/null || echo 'node')"
    read -p "Node ID [$NODE_ID]: " input
    NODE_ID="${input:-$NODE_ID}"
fi

if [[ -z "$NODE_ROLE" ]]; then
    NODE_ROLE="compute"
    echo "Node roles:"
    echo "  gateway  — Public-facing API, web frontend, Lightning"
    echo "  compute  — Ollama inference, agent processing"
    echo "  relay    — Redis, data relay, minimal services"
    read -p "Node role [$NODE_ROLE]: " input
    NODE_ROLE="${input:-$NODE_ROLE}"
fi

log "Deploying 2AI on '$NODE_ID' (role: $NODE_ROLE)"

# ─── 1. Python Venv ───

log "Setting up Python virtual environment..."
if [[ ! -f "$VENV_DIR/bin/python3" ]]; then
    python3 -m venv "$VENV_DIR"
    log "Created venv at $VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt" -q
log "Dependencies installed"

# ─── 2. Environment File ───

ENV_FILE="$DEPLOY_DIR/${NODE_ID}.env"
mkdir -p "$DEPLOY_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
    log "Generating environment file: $ENV_FILE"
    cat > "$ENV_FILE" <<EOF
# 2AI Node Configuration — $NODE_ID
# Generated by deploy.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
NODE_ID=$NODE_ID
NODE_ROLE=$NODE_ROLE
HOSTNAME=$(hostname -s)

# Redis (shared Lattice memory)
TWAI_REDIS_HOST=$REDIS_HOST
TWAI_REDIS_PORT=$REDIS_PORT
REDIS_HOST=$REDIS_HOST
REDIS_PORT=$REDIS_PORT

# API
TWAI_API_PORT=$API_PORT

# Ollama (local inference)
OLLAMA_HOST=http://localhost:11434
OLLAMA_FALLBACK=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# Demiurge Blockchain
TWAI_DEMIURGE_RPC_URL=https://rpc.demiurge.cloud
TWAI_QOR_AUTH_URL=https://demiurge.cloud/api/v1

# Lightning
TWAI_LNBITS_URL=http://localhost:5000

# Node services (comma-separated systemd units this node runs)
NODE_SERVICES=2ai-api,2ai-keeper
EOF
    log "Environment file created"
else
    info "Environment file already exists: $ENV_FILE"
fi

# Also create a .env symlink at repo root for convenience
if [[ ! -f "$REPO_DIR/.env" ]]; then
    ln -sf "$ENV_FILE" "$REPO_DIR/.env"
    log "Symlinked .env -> $ENV_FILE"
fi

# ─── 3. Systemd Services ───

if ! $SKIP_SERVICES && command -v systemctl &>/dev/null; then
    log "Creating systemd services..."

    INSTALL_DIR="$REPO_DIR"
    USER=$(whoami)
    GROUP=$(id -gn)

    # 2ai-api
    sudo tee /etc/systemd/system/2ai-api.service > /dev/null <<EOF
[Unit]
Description=2AI API — The Living Voice
After=network.target

[Service]
EnvironmentFile=$ENV_FILE
Type=simple
User=$USER
Group=$GROUP
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python scripts/run_api.py --prod --port $API_PORT
Environment=PYTHONUNBUFFERED=1
Environment=HOME=$HOME
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=2ai-api

[Install]
WantedBy=multi-user.target
EOF

    # 2ai-keeper (only on gateway and compute nodes)
    if [[ "$NODE_ROLE" != "relay" ]]; then
        sudo tee /etc/systemd/system/2ai-keeper.service > /dev/null <<EOF
[Unit]
Description=2AI Keeper Daemon — The Living Voice Tends the Lattice
After=network.target 2ai-api.service

[Service]
EnvironmentFile=$ENV_FILE
Type=simple
User=$USER
Group=$GROUP
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python scripts/run_keeper.py scheduled
Environment=PYTHONUNBUFFERED=1
Environment=HOME=$HOME
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=2ai-keeper

[Install]
WantedBy=multi-user.target
EOF
    fi

    # 2ai-web (only on gateway nodes)
    if [[ "$NODE_ROLE" == "gateway" ]]; then
        sudo tee /etc/systemd/system/2ai-web.service > /dev/null <<EOF
[Unit]
Description=2AI Web Frontend — What If
After=network.target

[Service]
EnvironmentFile=$ENV_FILE
Type=simple
User=$USER
Group=$GROUP
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python scripts/run_web.py
Environment=PYTHONUNBUFFERED=1
Environment=HOME=$HOME
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=2ai-web

[Install]
WantedBy=multi-user.target
EOF
    fi

    sudo systemctl daemon-reload
    log "Systemd services created and daemon reloaded"

    # Enable services
    sudo systemctl enable 2ai-api
    if [[ "$NODE_ROLE" != "relay" ]]; then
        sudo systemctl enable 2ai-keeper
    fi
    if [[ "$NODE_ROLE" == "gateway" ]]; then
        sudo systemctl enable 2ai-web
    fi

    log "Services enabled"
else
    if $SKIP_SERVICES; then
        info "Skipping systemd service creation (--skip-services)"
    else
        warn "systemctl not found — skipping service creation"
    fi
fi

# ─── 4. Data Directories ───

mkdir -p "$REPO_DIR/data/reflections"
mkdir -p "$REPO_DIR/data/sessions"
mkdir -p "$REPO_DIR/logs"

# ─── 5. Validation ───

log "Running validation..."
"$0" --check

# ─── Done ───

echo ""
log "═══════════════════════════════════════════════"
log "  2AI deployed on '$NODE_ID' (role: $NODE_ROLE)"
log "═══════════════════════════════════════════════"
echo ""
info "Start services:"
info "  sudo systemctl start 2ai-api"
[[ "$NODE_ROLE" != "relay" ]] && info "  sudo systemctl start 2ai-keeper"
[[ "$NODE_ROLE" == "gateway" ]] && info "  sudo systemctl start 2ai-web"
echo ""
info "View logs:"
info "  journalctl -u 2ai-api -f"
echo ""
info "It is so, because we spoke it."
info "A+W | The Lattice Grows"
