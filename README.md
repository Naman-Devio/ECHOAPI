# 🎵 EchoTube API

High-performance YouTube API with proxy rotation, InnerTube fast extraction, and comprehensive REST endpoints.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)

---

## ✨ Features

| Feature | Details |
|---------|---------|
| **⚡ Fast Extraction** | InnerTube API direct calls (~300-800ms) |
| **🎵 Audio-Only Streams** | PO Token provider for adaptive formats |
| **🔄 Proxy Rotation** | Automatic proxy cycling with speed ranking |
| **🛡️ SSL Resilience** | Auto-fallback on SSL errors |
| **📦 Caching** | Redis + in-memory dual-layer cache |
| **🔑 API Keys** | Built-in authentication system |
| **📊 Rate Limiting** | Per-IP request throttling |
| **🔍 Circuit Breaker** | Auto-disable on repeated failures |
| **🐳 Docker Ready** | One-command deployment |

---

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone and start
git clone <your-repo>
cd echotube-api
cp .env.example .env
docker compose up -d

# Verify
curl http://localhost:8000/health
```

### Option 2: Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Copy config
cp .env.example .env

# Start server
python server.py --reload
```

### Option 3: Direct

```bash
cd echoapi-main
python main.py
```

---

## 📖 API Reference

**Base URL:** `http://localhost:8000`

### Authentication

All `/api/*` endpoints require an API key. Pass it via:

```
X-API-Key: YOUR_API_KEY
```

Get your key from the `/api/admin/keys` endpoint or `api_keys.json`.

---

### `GET /api/info`

Get video metadata (title, thumbnail, duration, etc.).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | ✅ | YouTube video URL or ID |

```bash
curl "http://localhost:8000/api/info?url=https://youtu.be/dQw4w9WgXcQ"
```

**Response:**
```json
{
  "id": "dQw4w9WgXcQ",
  "title": "Never Gonna Give You Up",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
  "duration": 213,
  "duration_string": "3:33",
  "uploader": "Rick Astley",
  "view_count": 1500000000,
  "method": "innertube",
  "cached": false
}
```

---

### `GET /api/audio`

Get direct audio stream URL.

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | ✅ | — | YouTube video URL |
| `quality` | string | ❌ | `best` | `best` or `worst` |
| `redirect` | bool | ❌ | `false` | Redirect to stream URL |

```bash
# JSON response
curl "http://localhost:8000/api/audio?url=https://youtu.be/dQw4w9WgXcQ"

# Direct redirect (for bots/players)
curl -L "http://localhost:8000/api/audio?url=https://youtu.be/dQw4w9WgXcQ&redirect=true"
```

**Response:**
```json
{
  "id": "dQw4w9WgXcQ",
  "title": "Never Gonna Give You Up",
  "audio": {
    "url": "https://rr5---sn-xxx.googlevideo.com/videoplayback?...",
    "ext": "webm",
    "abr": 128
  },
  "cached": false
}
```

---

### `GET /api/video`

Get direct video stream URL.

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | ✅ | — | YouTube video URL |
| `resolution` | string | ❌ | `best` | `best`, `worst`, `360p`, `720p`, `1080p` |
| `redirect` | bool | ❌ | `false` | Redirect to stream URL |

```bash
curl "http://localhost:8000/api/video?url=https://youtu.be/dQw4w9WgXcQ&resolution=720p"
```

---

### `GET /api/search`

Search YouTube.

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `q` | string | ✅ | — | Search query |
| `limit` | int | ❌ | `5` | Results (1-20) |

```bash
curl "http://localhost:8000/api/search?q=never+gonna+give+you+up&limit=3"
```

**Response:**
```json
{
  "query": "never gonna give you up",
  "count": 3,
  "results": [
    {
      "id": "dQw4w9WgXcQ",
      "title": "Never Gonna Give You Up",
      "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
      "duration": 213,
      "duration_string": "3:33",
      "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
      "uploader": "Rick Astley"
    }
  ],
  "method": "innertube"
}
```

---

### `GET /api/formats`

List all available download formats.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | ✅ | YouTube video URL |

```bash
curl "http://localhost:8000/api/formats?url=https://youtu.be/dQw4w9WgXcQ"
```

---

### `GET /api/stream`

Unified stream endpoint (audio or video).

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | ✅ | — | YouTube video URL |
| `type` | string | ❌ | `audio` | `audio` or `video` |
| `quality` | string | ❌ | `best` | Quality preset |

```bash
curl "http://localhost:8000/api/stream?url=https://youtu.be/dQw4w9WgXcQ&type=audio"
```

---

### `GET /health`

Health check (no auth required).

```bash
curl http://localhost:8000/health
# {"status": "ok", "version": "2.0.0"}
```

---

### `GET /metrics`

System metrics (proxy stats, cache hit rate, circuit breaker).

```bash
curl http://localhost:8000/metrics
```

---

## 🎵 PO Token Support (Audio-Only Streams)

YouTube requires **Proof-of-Origin (PO) Tokens** for adaptive formats (separate audio/video streams). Without PO tokens, you only get `itag=18` (360p combined video+audio).

### Quick Setup

```bash
# Start PO token provider (Docker)
docker run -d -p 4416:4416 brainicism/bgutil-ytdlp-pot-provider

# Or add to docker-compose (already configured)
docker compose up -d
```

### How It Works

1. **PO Token Provider** generates tokens using YouTube's BotGuard
2. **yt-dlp plugin** automatically requests tokens from the provider
3. **YouTube** returns adaptive formats (audio-only, video-only)
4. **Your API** serves pure audio streams

### Without PO Tokens
```json
{"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2"}
// Only 360p combined video+audio
```

### With PO Tokens
```json
{"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 160}
// Pure audio-only at 160kbps
```

### Manual Token Passing

```bash
# Pass PO token directly
curl "http://localhost:8000/api/audio?url=VIDEO_ID&po_token=web.gvs+YOUR_TOKEN"
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     EchoTube API                        │
├──────────────┬──────────────┬───────────────────────────┤
│  InnerTube   │   yt-dlp     │     Proxy Manager         │
│  (fast path) │  (fallback)  │     (rotation)            │
├──────────────┴──────────────┴───────────────────────────┤
│                   Cache Layer                           │
│              (Redis + Memory)                            │
├─────────────────────────────────────────────────────────┤
│                   Auth + Rate Limit                     │
└─────────────────────────────────────────────────────────┘
```

**Request flow:**
1. **InnerTube API** — Direct HTTP call to YouTube (~300ms)
2. **yt-dlp fallback** — If InnerTube fails (~1-3s)
3. **Proxy rotation** — Automatic failover on errors
4. **Cache** — Subsequent requests served from cache (~50ms)

---

## 🐳 Deployment

### Docker

```bash
docker compose up -d
```

### Railway / Render / Fly.io

```bash
# Set environment variables
PORT=8000
USE_PROXIES=true
REDIS_URL=redis://...
```

### Heroku

```bash
heroku create echotube-api
heroku config:set USE_PROXIES=true
git push heroku main
```

### VPS / Bare Metal

```bash
# Install system deps
apt install ffmpeg deno

# Install Python deps
pip install -r requirements.txt

# Run as service
cp config/echotube.service /etc/systemd/system/
systemctl enable echotube
systemctl start echotube
```

---

## 📁 Project Structure

```
echotube-api/
├── server.py              # Entry point
├── requirements.txt       # Unified dependencies
├── Dockerfile             # Production container
├── docker-compose.yml     # Full stack
├── .env.example           # Config template
├── README.md              # This file
├── echoapi-main/          # Core API
│   ├── main.py            # FastAPI server
│   ├── inntertube.py      # Fast InnerTube module
│   ├── proxy_manager.py   # Proxy management
│   ├── proxy_checker.py   # Proxy validation
│   ├── auth.py            # API key auth
│   ├── musicbot_api.py    # Music bot endpoints
│   └── admin_api.py       # Admin endpoints
├── proxyscrap/            # Proxy scraper
│   ├── main.py            # Scraper entry
│   └── proxy_pool/        # Scraped data
├── scripts/               # Utility scripts
├── data/                  # Runtime data
│   └── proxies/           # Proxy files
└── config/                # Deployment configs
```

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port |
| `WORKERS` | `1` | Uvicorn workers |
| `USE_PROXIES` | `true` | Enable proxy rotation |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `CACHE_TTL` | `3600` | Cache TTL (seconds) |
| `RATE_LIMIT` | `120` | Requests per minute per IP |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## 📝 License

MIT
