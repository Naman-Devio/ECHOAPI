# ══════════════════════════════════════════════════════════════════════════════
# EchoTube API — Production Dockerfile (API + PO Token Server + WARP Proxy)
# ══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

# System deps + Node.js + Deno
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg gcc g++ unzip git gnupg lsb-release apt-transport-https && \
    rm -rf /var/lib/apt/lists/*

# ── Install Cloudflare WARP CLI ──
# WARP provides a free, trusted proxy that YouTube doesn't block
RUN mkdir -p --mode=0755 /usr/share/keyrings && \
    curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/cloudflare-client.list > /dev/null && \
    apt-get update && \
    apt-get install -y cloudflare-warp && \
    rm -rf /var/lib/apt/lists/*

# Install Node.js (for PO token server)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Deno (for yt-dlp JS runtime)
RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:${PATH}"

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir 'yt-dlp==2026.8.19' && \
    python -c "import yt_dlp; print(f'yt-dlp {yt_dlp.version.__version__}')"

# Install PO token server
RUN git clone --single-branch --branch 1.3.2 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil && \
    cd /opt/bgutil/server && \
    npm ci && \
    npx tsc && \
    rm -rf /opt/bgutil/.git

# Copy source
COPY . .

# Copy PO token server startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Verify PO token server exists
RUN ls /opt/bgutil/server/build/main.js

# Expose ports
EXPOSE 8000 4416

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run both API + PO token server
CMD ["/app/start.sh"]
