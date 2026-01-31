#!/bin/bash
# =========================================================================
# Sovereign Lattice — Pi 5 "The Foundation" Setup
# =========================================================================
# Run this ON the Pi after SSH access is established.
#
# Usage from ThinkCenter:
#   scp deploy-pi.sh pi@192.168.1.21:/tmp/
#   scp monitor.py pi@192.168.1.21:/tmp/
#   ssh pi@192.168.1.21 'bash /tmp/deploy-pi.sh'
#
# A+W | The Foundation Holds
# =========================================================================

set -e

echo "=== Sovereign Lattice — Pi 5 Setup ==="
echo "Node: The Foundation"
echo "Role: Infrastructure (Redis + Health Monitor)"
echo ""

# -------------------------------------------------------------------
# 1. Enable Redis AOF persistence
# -------------------------------------------------------------------
echo "[1/5] Configuring Redis persistence..."
REDIS_CONF="/etc/redis/redis.conf"

if grep -q "^appendonly no" "$REDIS_CONF" 2>/dev/null; then
    sudo sed -i 's/^appendonly no/appendonly yes/' "$REDIS_CONF"
    echo "  appendonly → yes"
elif ! grep -q "^appendonly yes" "$REDIS_CONF" 2>/dev/null; then
    echo "appendonly yes" | sudo tee -a "$REDIS_CONF" > /dev/null
    echo "  appendonly → yes (appended)"
else
    echo "  appendonly already enabled"
fi

# Ensure appendfsync is set
if ! grep -q "^appendfsync everysec" "$REDIS_CONF" 2>/dev/null; then
    sudo sed -i 's/^# appendfsync everysec/appendfsync everysec/' "$REDIS_CONF" 2>/dev/null || true
    sudo sed -i 's/^appendfsync .*/appendfsync everysec/' "$REDIS_CONF" 2>/dev/null || true
    echo "  appendfsync → everysec"
else
    echo "  appendfsync already set"
fi

sudo systemctl restart redis-server || sudo systemctl restart redis
echo "  Redis restarted with AOF persistence."

# -------------------------------------------------------------------
# 2. Install Python dependencies
# -------------------------------------------------------------------
echo "[2/5] Installing dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip > /dev/null 2>&1

# Install httpx for health checks
pip3 install httpx redis --break-system-packages 2>/dev/null || pip3 install httpx redis
echo "  Python dependencies installed."

# -------------------------------------------------------------------
# 3. Create health monitor directory
# -------------------------------------------------------------------
echo "[3/5] Setting up health monitor..."
MONITOR_DIR="/home/$(whoami)/lattice-health"
mkdir -p "$MONITOR_DIR"

# Copy monitor.py if available in /tmp
if [ -f /tmp/monitor.py ]; then
    cp /tmp/monitor.py "$MONITOR_DIR/monitor.py"
    echo "  monitor.py deployed."
else
    echo "  WARNING: /tmp/monitor.py not found. Deploy it manually:"
    echo "    scp monitor.py pi@192.168.1.21:$MONITOR_DIR/"
fi

# -------------------------------------------------------------------
# 4. Create systemd service
# -------------------------------------------------------------------
echo "[4/5] Creating systemd service..."
sudo tee /etc/systemd/system/lattice-health.service > /dev/null <<UNIT
[Unit]
Description=Lattice Health Monitor — The Foundation Watches
After=network.target redis-server.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$MONITOR_DIR
ExecStart=/usr/bin/python3 $MONITOR_DIR/monitor.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1
Environment=REDIS_HOST=127.0.0.1
Environment=REDIS_PORT=6379
Environment=NODE_ID=pi
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lattice-health

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable lattice-health.service
echo "  lattice-health.service created and enabled."

# -------------------------------------------------------------------
# 5. Verify
# -------------------------------------------------------------------
echo "[5/5] Verifying..."
redis-cli ping && echo "  Redis: OK" || echo "  Redis: FAILED"
redis-cli CONFIG GET appendonly | grep -q "yes" && echo "  AOF: ON" || echo "  AOF: OFF"

echo ""
echo "=== Pi Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Deploy monitor.py to $MONITOR_DIR/"
echo "  2. Start: sudo systemctl start lattice-health"
echo "  3. Check: journalctl -u lattice-health -f"
echo ""
echo "The Foundation holds."
