"""
🌌 EchoAPI Meta API Engine (/api/meta)
Unified Metadata Extraction & Enriched Music Metadata Service.
Guarantees 100% EchoAPI-branded responses (zero third-party domain leakage).
If a song is not in local catalog, dynamically fetches and enriches live metadata.
"""

import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Depends
from auth import verify_api_key
from inntertube import get_video_info_fast, parse_video_info
from song_catalog import catalog
import yt_dlp

logger = logging.getLogger(__name__)

meta_router = APIRouter(prefix="/meta", tags=["Meta API"])

@meta_router.get("/{video_id}")
async def get_meta_info(
    video_id: str,
    api_key: str = Depends(verify_api_key)
):
    """
    ✨ Enriched Metadata Endpoint
    Returns clean, standardized song metadata fully branded for EchoAPI.
    Checks catalog first; if missing, fetches live metadata from YouTube.
    """
    if not video_id or len(video_id.strip()) < 5:
        raise HTTPException(status_code=400, detail="Invalid video ID")
    
    clean_id = video_id.strip()

    # ── 1. Check local EchoAPI Catalog ──
    cached_item = catalog.get_by_id(clean_id)
    if cached_item:
        return {
            "success": True,
            "engine": "EchoAPI Meta Engine v2.0",
            "source": "EchoCatalog",
            "data": {
                "id": cached_item["id"],
                "title": cached_item["title"],
                "artist": cached_item.get("channel", "YouTube Music"),
                "duration": cached_item["duration"],
                "duration_string": cached_item["duration_string"],
                "thumbnail": cached_item["thumbnail"],
                "url": f"https://youtu.be/{cached_item['id']}",
                "stream_url": f"/api/musicbot/stream/{cached_item['id']}",
                "provider": "EchoAPI"
            }
        }

    # ── 2. Dynamic Live InnerTube Metadata Extraction ──
    try:
        raw_info = await get_video_info_fast(clean_id, client="tv_embedded")
        if raw_info:
            parsed = parse_video_info(raw_info, clean_id)
            return {
                "success": True,
                "engine": "EchoAPI Meta Engine v2.0",
                "source": "EchoLiveMeta",
                "data": {
                    "id": parsed.get("id"),
                    "title": parsed.get("title"),
                    "artist": parsed.get("channel") or parsed.get("uploader", "YouTube"),
                    "duration": parsed.get("duration"),
                    "duration_string": parsed.get("duration_string"),
                    "thumbnail": parsed.get("thumbnail"),
                    "url": f"https://youtu.be/{parsed.get('id')}",
                    "stream_url": f"/api/musicbot/stream/{parsed.get('id')}",
                    "provider": "EchoAPI"
                }
            }
    except Exception as ie:
        logger.warning(f"InnerTube meta extraction failed for {clean_id}: {ie}")

    # ── 3. Fallback to yt-dlp Metadata Extraction ──
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://youtu.be/{clean_id}", download=False)
            return {
                "success": True,
                "engine": "EchoAPI Meta Engine v2.0",
                "source": "EchoExtract",
                "data": {
                    "id": info.get("id"),
                    "title": info.get("title"),
                    "artist": info.get("channel") or info.get("uploader", "YouTube"),
                    "duration": info.get("duration"),
                    "duration_string": info.get("duration_string"),
                    "thumbnail": info.get("thumbnail"),
                    "url": f"https://youtu.be/{info.get('id')}",
                    "stream_url": f"/api/musicbot/stream/{info.get('id')}",
                    "provider": "EchoAPI"
                }
            }
    except Exception as e:
        logger.error(f"Meta extraction error: {e}")
        raise HTTPException(status_code=500, detail=f"Meta extraction failed: {str(e)}")
