# ══════════════════════════════════════════════════════════════════════════════
# EchoTube API — Production Dockerfile (API + PO Token Server)
# ══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

# System deps + Node.js + Deno
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg gcc g++ unzip git && \
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
RUN pip install --no-cache-dir -r requirements.txt

# Install PO token server
RUN git clone --single-branch --branch 1.3.2 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /tmp/bgutil && \
    cd /tmp/bgutil/server && \
    npm ci && \
    npx tsc && \
    rm -rf /tmp/bgutil/.git

# Copy source
COPY . .

# Copy PO token server startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Expose ports
EXPOSE 8000 4416

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run both API + PO token server
CMD ["/app/start.sh"]
