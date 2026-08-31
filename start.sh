#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# EchoTube API — Startup Script
# Runs PO token server (port 4416) + API server (port 8000) together
# ══════════════════════════════════════════════════════════════════════════════

echo "Starting EchoTube API stack..."

# Start PO token server in background
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

# Start API server
cd /app
echo "Starting API server on port ${PORT:-8000}..."
exec python server.py
