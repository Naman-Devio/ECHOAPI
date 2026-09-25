"""
Music Bot API Endpoints
Specialized endpoints for Discord/Telegram music bots
"""

import yt_dlp
from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Optional, List
from auth import verify_api_key, verify_api_key_optional
import logging
import os
import ssl

logger = logging.getLogger(__name__)

# SSL bypass environment variable for the entire process
os.environ["PYTHONHTTPSVERIFY"] = "0"

# Create router
musicbot_router = APIRouter(prefix="/musicbot", tags=["Music Bot API"])

@musicbot_router.get("/search")
async def search_music(
    q: str = Query(description="Search query for music/videos"),
    limit: int = Query(default=10, ge=1, le=50, description="Number of results"),
    api_key: str = Depends(verify_api_key)
):
    """
    🎵 Search for music and videos
    
    **Authentication Required**: Include your API key
    - Header: `Authorization: Bearer your_api_key`
    - Query: `?api_key=your_api_key`
    
    Perfect for music bots to find songs!
    """
    # ── Try ultra-fast InnerTube search first (no bot detection, ~300ms) ──
    try:
        from inntertube import search_youtube_fast
        fast_results = await search_youtube_fast(q, max_results=limit)
        if fast_results:
            results = []
            for entry in fast_results:
                results.append({
                    "id": entry.get('id'),
                    "title": entry.get('title'),
                    "duration": entry.get('duration'),
                    "duration_string": entry.get('duration_string'),
                    "thumbnail": entry.get('thumbnail'),
                    "channel": entry.get('uploader'),
                    "url": entry.get('url') or f"https://youtu.be/{entry.get('id')}",
                    "view_count": entry.get('view_count'),
                })
            return {
                "success": True,
                "query": q,
                "results": results,
                "total": len(results)
            }
    except Exception as e:
        logger.warning(f"Fast InnerTube search failed, falling back to yt-dlp: {e}")

    # ── Fallback to yt-dlp search ──
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'socket_timeout': 30,
            'retries': 5,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch{limit}:{q}", download=False)
            
            results = []
            for entry in search_results.get('entries', []):
                if entry:
                    results.append({
                        "id": entry.get('id'),
                        "title": entry.get('title'),
                        "duration": entry.get('duration'),
                        "duration_string": entry.get('duration_string'),
                        "thumbnail": entry.get('thumbnail'),
                        "channel": entry.get('channel') or entry.get('uploader'),
                        "url": f"https://youtu.be/{entry.get('id')}",
                        "view_count": entry.get('view_count'),
                    })
            
            return {
                "success": True,
                "query": q,
                "results": results,
                "total": len(results)
            }
            
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@musicbot_router.get("/info/{video_id}")
async def get_music_info(
    video_id: str,
    api_key: str = Depends(verify_api_key)
):
    """
    📋 Get detailed information about a video/song
    
    **Authentication Required**: Include your API key
    
    Returns: title, duration, thumbnail, formats, etc.
    """
    try:
        url = f"https://youtu.be/{video_id}"
        
        from po_token_helper import POT_SERVER_URL, check_server as pot_check
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'socket_timeout': 30,
            'retries': 5,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'mweb']
                }
            }
        }
        if pot_check():
            ydl_opts["extractor_args"]["youtubepot-bgutilhttp"] = {"base_url": [POT_SERVER_URL]}
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extract audio formats
            audio_formats = []
            for fmt in info.get('formats', []):
                if fmt.get('acodec') not in (None, 'none', '') and fmt.get('vcodec') in (None, 'none', ''):
                    abr = fmt.get('abr') or fmt.get('tbr') or 'unknown'
                    audio_formats.append({
                        "format_id": fmt.get('format_id'),
                        "quality": f"{abr}kbps" if isinstance(abr, (int, float)) else str(abr),
                        "ext": fmt.get('ext'),
                        "filesize": fmt.get('filesize'),
                        "protocol": fmt.get('protocol'),
                    })
            
            return {
                "success": True,
                "id": info.get('id'),
                "title": info.get('title'),
                "channel": info.get('channel') or info.get('uploader'),
                "duration": info.get('duration'),
                "duration_string": info.get('duration_string'),
                "thumbnail": info.get('thumbnail'),
                "description": info.get('description', '')[:500],
                "view_count": info.get('view_count'),
                "like_count": info.get('like_count'),
                "upload_date": info.get('upload_date'),
                "audio_formats": audio_formats[:10],
                "url": f"https://youtu.be/{info.get('id')}"
            }
            
    except Exception as e:
        logger.error(f"Info extraction error: {e}")
        raise HTTPException(status_code=500, detail=f"Info extraction failed: {str(e)}")

@musicbot_router.get("/stream/{video_id}")
async def get_stream_url(
    video_id: str,
    quality: str = Query(default="medium", description="Audio quality: low, medium, high"),
    api_key: str = Depends(verify_api_key)
):
    """
    🌊 Get direct stream URL (no download needed)
    
    **Authentication Required**: Include your API key
    
    Perfect for streaming audio in Discord/Telegram bots!
    Returns a direct URL that expires in ~6 hours.
    """
    try:
        url = f"https://youtu.be/{video_id}"
        
        from po_token_helper import POT_SERVER_URL, check_server as pot_check
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'format': 'bestaudio/best',
            'nocheckcertificate': True,
            'socket_timeout': 30,
            'retries': 5,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'mweb']
                }
            }
        }
        if pot_check():
            ydl_opts["extractor_args"]["youtubepot-bgutilhttp"] = {"base_url": [POT_SERVER_URL]}
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats = info.get('formats', [])
            
            # Find streams with audio and a valid URL
            audio_streams = [
                f for f in formats
                if f.get('acodec') not in (None, 'none', '') and f.get('vcodec') in (None, 'none', '') and f.get('url')
            ]
            
            # Prioritize progressive direct HTTPS streams (m4a, webm) over HLS m3u8_native
            direct_https = [f for f in audio_streams if f.get('protocol') == 'https']
            candidates = direct_https if direct_https else audio_streams
            
            if not candidates:
                # Fallback to combined streams with audio
                candidates = [
                    f for f in formats
                    if f.get('acodec') not in (None, 'none', '') and f.get('url')
                ]
            
            if not candidates:
                raise HTTPException(status_code=404, detail="No audio streams available")
            
            def _get_bitrate(f):
                return f.get('abr') or f.get('tbr') or 0
                
            candidates.sort(key=_get_bitrate, reverse=True)
            
            # Select based on quality preference
            if quality == "low":
                best_stream = candidates[-1]
            elif quality == "high":
                best_stream = candidates[0]
            else:  # medium
                best_stream = candidates[len(candidates) // 2]
            
            abr = best_stream.get('abr') or best_stream.get('tbr') or 'unknown'
            
            return {
                "success": True,
                "title": info.get('title'),
                "stream_url": best_stream.get('url'),
                "quality": f"{abr}kbps" if isinstance(abr, (int, float)) else str(abr),
                "format": best_stream.get('ext'),
                "protocol": best_stream.get('protocol'),
                "duration": info.get('duration'),
                "duration_string": info.get('duration_string'),
                "expires_in": "~6 hours",
                "note": "Stream URL expires after ~6 hours. Request again if expired."
            }
            
    except Exception as e:
        logger.error(f"Stream URL error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream URL generation failed: {str(e)}")

@musicbot_router.get("/playlist/{playlist_id}")
async def get_playlist(
    playlist_id: str,
    limit: int = Query(default=50, ge=1, le=100, description="Max videos to return"),
    api_key: str = Depends(verify_api_key)
):
    """
    📚 Get playlist information
    
    **Authentication Required**: Include your API key
    
    Extract all videos from a YouTube playlist.
    """
    
    try:
        url = f"https://www.youtube.com/playlist?list={playlist_id}"
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'playlistend': limit,
            'nocheckcertificate': True,  # Bypass SSL verification
            'socket_timeout': 30,
            'retries': 5,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            playlist_info = ydl.extract_info(url, download=False)
            
            videos = []
            for entry in playlist_info.get('entries', []):
                if entry:
                    videos.append({
                        "id": entry.get('id'),
                        "title": entry.get('title'),
                        "duration": entry.get('duration'),
                        "duration_string": entry.get('duration_string'),
                        "uploader": entry.get('uploader'),
                        "url": f"https://youtu.be/{entry.get('id')}"
                    })
            
            return {
                "success": True,
                "playlist_id": playlist_id,
                "title": playlist_info.get('title'),
                "uploader": playlist_info.get('uploader'),
                "video_count": len(videos),
                "videos": videos
            }
            
    except Exception as e:
        logger.error(f"Playlist extraction error: {e}")
        raise HTTPException(status_code=500, detail=f"Playlist extraction failed: {str(e)}")

@musicbot_router.get("/status")
async def musicbot_status(api_key: Optional[str] = Depends(verify_api_key_optional)):
    """
    ✅ Check Music Bot API status
    
    Public endpoint (no authentication required)
    Authenticated users get additional information.
    """
    
    response = {
        "status": "online",
        "api": "youtube-musicbot-api",
        "version": "1.0.0",
        "endpoints": {
            "search": "/musicbot/search",
            "info": "/musicbot/info/{video_id}",
            "stream": "/musicbot/stream/{video_id}",
            "playlist": "/musicbot/playlist/{playlist_id}",
            "status": "/musicbot/status"
        },
        "features": [
            "YouTube search",
            "Direct stream URLs",
            "Playlist support",
            "High-quality audio",
            "Fast extraction"
        ]
    }
    
    if api_key:
        # Authenticated user gets more info
        from auth import api_key_manager
        key_info = api_key_manager.get_key_info(api_key)
        if key_info:
            response["your_usage"] = {
                "tier": key_info.get("tier", "unknown"),
                "requests_today": key_info.get("requests_today", 0),
                "rate_limit": key_info.get("rate_limit", 0),
                "remaining": key_info.get("rate_limit", 0) - key_info.get("requests_today", 0)
            }
    
    return response
