#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# EchoTube API — Startup Script
# Runs Co-located PO Token server (port 4416) + API server (port 8000)
# ══════════════════════════════════════════════════════════════════════════════

echo "════════════════════════════════════════════════════════════════"
echo "  Starting EchoTube API Cloud Stack"
echo "════════════════════════════════════════════════════════════════"

# ── Step 1: Start PO Token server in background ──
echo "[1/2] Starting PO Token Server (port 4416)..."
cd /opt/bgutil/server
node build/main.js --port 4416 --host 0.0.0.0 &
POT_PID=$!
echo "PO Token server PID: $POT_PID"

# Wait for PO token server to be ready
echo "Waiting for PO Token server to respond on /ping..."
READY=false
for i in {1..15}; do
    if curl -s http://127.0.0.1:4416/ping >/dev/null 2>&1; then
        echo "✓ PO Token server ready on port 4416 (attempt $i)"
        READY=true
        break
    fi
    sleep 1
done

if [ "$READY" = false ]; then
    echo "⚠ Warning: PO Token server did not respond within 15 seconds"
fi

# ── Step 2: Start API server ──
cd /app
export POT_PROVIDER_URL="http://127.0.0.1:4416"
export POT_SERVER_URL="http://127.0.0.1:4416"
echo "[2/2] Starting API server on port ${PORT:-8000}..."
exec python server.py
