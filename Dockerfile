# ══════════════════════════════════════════════════════════════════════════════
# EchoTube API — Production Dockerfile
# ══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg gcc g++ unzip && \
    rm -rf /var/lib/apt/lists/*

# Deno for yt-dlp JS runtime
RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:${PATH}"

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run
CMD ["python", "server.py"]
