#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# EchoTube API — Startup Script
# Runs Cloudflare WARP + PO Token server (port 4416) + API server (port 8000)
# ══════════════════════════════════════════════════════════════════════════════

echo "Starting EchoTube API stack..."

# ── Step 1: Start Cloudflare WARP proxy ──
echo "Starting Cloudflare WARP proxy..."

# Check if warp-cli is available
if command -v warp-cli &> /dev/null; then
    echo "  warp-cli found, setting up WARP..."
    
    # Register WARP (first time only, non-interactive)
    warp-cli registration new 2>/dev/null || true
    sleep 1
    
    # Set mode to proxy (SOCKS5 on port 40000)
    warp-cli mode proxy 2>/dev/null || true
    sleep 1
    
    # Connect to WARP
    warp-cli connect 2>/dev/null
    sleep 2
    
    # Wait up to 15 seconds for WARP to fully connect
    WARP_READY=false
    for i in $(seq 1 15); do
        WARP_STATUS_OUTPUT=$(warp-cli status 2>&1)
        if echo "$WARP_STATUS_OUTPUT" | grep -qi "connected"; then
            WARP_READY=true
            break
        fi
        echo "  Waiting for WARP... ($i/15)"
        sleep 1
    done
    
    if [ "$WARP_READY" = true ]; then
        echo "✓ Cloudflare WARP connected (SOCKS5 on localhost:40000)"
        export USE_WARP=true
        export WARP_PROXY=socks5://127.0.0.1:40000
    else
        echo "⚠ WARP status unclear (may still be connecting), attempting anyway..."
        echo "  Last status: $WARP_STATUS_OUTPUT"
        export USE_WARP=true
        export WARP_PROXY=socks5://127.0.0.1:40000
    fi
else
    echo "⚠ warp-cli not found, WARP proxy disabled"
    export USE_WARP=false
    export WARP_PROXY=""
fi

# Extra wait for WARP proxy to be fully ready
sleep 3

# ── Step 2: Start PO Token server in background ──
echo "Starting PO Token server on port 4416..."
cd /opt/bgutil/server
node build/main.js --port 4416 &
POT_PID=$!
echo "PO Token server PID: $POT_PID"

# Wait for PO token server to be ready
sleep 3
if kill -0 $POT_PID 2>/dev/null; then
    echo "✓ PO Token server started successfully"
else
    echo "⚠ PO Token server failed to start, continuing without it"
fi

# ── Step 3: Start API server ──
cd /app
echo "Starting API server on port ${PORT:-8000}..."
exec python server.py
