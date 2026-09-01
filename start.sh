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
    # Register WARP (first time only, non-interactive)
    warp-cli registration new 2>/dev/null || true
    
    # Set mode to proxy (SOCKS5 on port 40000)
    warp-cli mode proxy 2>/dev/null || true
    
    # Connect to WARP
    warp-cli connect 2>/dev/null
    WARP_STATUS=$?
    
    # Wait for WARP to establish connection
    sleep 3
    
    # Verify WARP is working
    if warp-cli status 2>/dev/null | grep -q "Connected"; then
        echo "✓ Cloudflare WARP connected (SOCKS5 on localhost:40000)"
        export USE_WARP=true
        export WARP_PROXY=socks5://127.0.0.1:40000
    else
        echo "⚠ Cloudflare WARP status check failed, attempting anyway..."
        export USE_WARP=true
        export WARP_PROXY=socks5://127.0.0.1:40000
    fi
else
    echo "⚠ warp-cli not found, WARP proxy disabled"
    export USE_WARP=false
    export WARP_PROXY=""
fi

# Wait for WARP to be ready
sleep 2

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
