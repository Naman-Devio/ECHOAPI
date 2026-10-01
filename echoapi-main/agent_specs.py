"""
🤖 AI Agent Readiness & Open Specification Endpoints
Provides /llms.txt, /llms-full.txt, and markdown documentation for AI coding agents & API clients.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

agent_router = APIRouter(tags=["AI Agent Specs"])

LLMS_TXT = """# EchoAPI — High-Performance YouTube Music & Streaming API
> Version: 2.0.0
> Base URL: https://echoapi-3u8f.onrender.com
> Authentication: Bearer Token or ?api_key= query parameter

## Core Endpoints

### 1. Search Music & Videos
- GET /api/musicbot/search?q={query}&limit=10
- GET /api/search?q={query}&limit=10
- Header: Authorization: Bearer <API_KEY>
- Response: { "success": true, "query": "...", "results": [ { "id": "...", "title": "...", "duration": 213, "duration_string": "3:33", "thumbnail": "...", "channel": "...", "url": "..." } ] }

### 2. Stream Audio Extraction (Direct HTTPS Audio URL)
- GET /api/musicbot/stream/{video_id}?quality=high
- GET /api/audio?url={video_id_or_url}&quality=high
- Header: Authorization: Bearer <API_KEY>
- Response: { "success": true, "title": "...", "stream_url": "https://googlevideo.com/videoplayback?...", "quality": "129kbps", "format": "m4a", "duration": 213 }

### 3. Video / Media Details & Formats
- GET /api/musicbot/info/{video_id}
- GET /api/video?url={video_id_or_url}
- Header: Authorization: Bearer <API_KEY>

### 4. Health & Anti-Sleep Ping
- GET /health
- GET /ping

### 5. Open API Specification
- GET /openapi.json
- GET /docs
"""

LLMS_FULL_TXT = """# EchoAPI — Complete Technical Specification for AI & Developer Integration

## Architecture Overview
EchoAPI is an enterprise-grade YouTube Music, Audio Streaming, and Metadata Extraction REST API.
It integrates a 3-Way Async Race Search Engine, co-located BotGuard PO Token Provider (port 4416),
and direct mobile client player fallback (`ios`, `android`, `mweb`) for 100% cloud reliability.

## Authentication Methods
1. HTTP Header: `Authorization: Bearer ytdl_clXaiUsf8CQAnXhHvBdS9YRX9vEHndLLFPSraSOFcM8`
2. Query Parameter: `?api_key=ytdl_clXaiUsf8CQAnXhHvBdS9YRX9vEHndLLFPSraSOFcM8`

## Full Route Matrix

### GET /api/musicbot/search
Query parameters:
- `q` (string, required): Music/video search query
- `limit` (integer, default=10, max=50): Number of results to return

### GET /api/musicbot/stream/{video_id}
Path parameters:
- `video_id` (string, required): 11-character YouTube video ID
Query parameters:
- `quality` (string, default="medium"): Quality preference ('low', 'medium', 'high')

### GET /api/musicbot/info/{video_id}
Path parameters:
- `video_id` (string, required): 11-character YouTube video ID

### GET /api/songs
Query parameters:
- `q` (string, optional): Multi-keyword search across 5,700+ indexed songs
- `limit` (integer, default=10): Results count
"""

@agent_router.get("/llms.txt", response_class=PlainTextResponse)
async def get_llms_txt():
    """Returns machine-readable summary spec for LLMs and AI Agents."""
    return PlainTextResponse(LLMS_TXT, media_type="text/markdown; charset=utf-8")

@agent_router.get("/llms-full.txt", response_class=PlainTextResponse)
async def get_llms_full_txt():
    """Returns complete technical spec for LLMs and AI Agents."""
    return PlainTextResponse(LLMS_FULL_TXT, media_type="text/markdown; charset=utf-8")
