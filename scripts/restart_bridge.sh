#!/bin/bash
set -e
echo "Stopping old bridge..."
sudo systemctl stop xiaonai-bridge 2>/dev/null || true
sleep 1
pkill -f 'python3.*bridge.py' 2>/dev/null || true
sleep 1

echo "Clearing cache..."
find /opt/xiaonai/__pycache__ -delete 2>/dev/null || true
find /opt/xiaonai/bridge_pkg/__pycache__ -delete 2>/dev/null || true

echo "Starting bridge fresh..."
cd /opt/xiaonai
nohup python3 bridge.py > /tmp/bridge_new.log 2>&1 &
BGPID=$!
sleep 4

if ss -tlnp 2>/dev/null | grep -q 8080; then
    echo "Bridge running on 8080 (PID $BGPID)"
else
    echo "Bridge NOT listening on 8080!"
    cat /tmp/bridge_new.log
    exit 1
fi
