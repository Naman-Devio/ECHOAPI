"""
🤖 Telegram Music Bot Compatibility Engine (compat.py)
Drop-in replacement for Telegram Music Bots (Yukki, AnonX, Fallen, Rose, PyTgCalls, VCPlayer).
Provides 100% compatibility with standard Telegram bot YouTubeAPI interface.

Usage in Telegram Music Bots:
    from compat import YouTubeAPI
    YouTube = YouTubeAPI()
"""

import os
import re
import asyncio
import httpx
import logging
from typing import Union, List, Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)

def extract_video_id(url: str) -> str:
    """Extract 11-character YouTube video ID from any standard or shortened link."""
    if not url:
        return ""
    url = str(url).strip()
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    patterns = [
        r'(?:v=)([a-zA-Z0-9_-]{11})',
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
        r'/shorts/([a-zA-Z0-9_-]{11})',
        r'/embed/([a-zA-Z0-9_-]{11})',
        r'/live/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return url

class YouTubeAPI:
    """
    Drop-in Telegram Music Bot API Client interface.
    Connects to local EchoAPI engine or remote EchoAPI deployment.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8000", api_key: str = "ytdl_clXaiUsf8CQAnXhHvBdS9YRX9vEHndLLFPSraSOFcM8"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def exists(self, link: str, videoid: Union[bool, str] = None) -> bool:
        """Check if link/videoid is a valid YouTube video ID."""
        if videoid and isinstance(videoid, str):
            link = f"https://www.youtube.com/watch?v={videoid}"
        vid = extract_video_id(link)
        return bool(vid and re.match(r'^[a-zA-Z0-9_-]{11}$', vid))

    async def url(self, message_1: Any, message_2: Any = None) -> Optional[str]:
        """Extract YouTube URL from Pyrogram / Telethon message entities."""
        messages = [message_1, message_2]
        text = ""
        offset = None
        length = None
        for message in messages:
            if not message:
                continue
            if getattr(message, "entities", None):
                for entity in message.entities:
                    if entity.type == "url":
                        text = getattr(message, "text", "") or getattr(message, "caption", "")
                        offset, length = entity.offset, entity.length
                        break
            elif getattr(message, "caption_entities", None):
                for entity in message.caption_entities:
                    if entity.type == "text_link":
                        return entity.url
        if offset is not None:
            return text[offset : offset + length]
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None) -> Tuple[str, str, int, str, str]:
        """
        Get track metadata tuple for Telegram Music Bots:
        Returns: (title, duration_min, duration_sec, thumbnail, vidid)
        """
        vid_id = extract_video_id(link) if not videoid else (videoid if isinstance(videoid, str) else extract_video_id(link))
        
        # 1. Check local catalog first
        from song_catalog import catalog
        cat_song = catalog.get_by_id(vid_id)
        if cat_song:
            dur_sec = cat_song.get("duration", 210)
            dur_min = cat_song.get("duration_string", "3:30")
            return (cat_song["title"], dur_min, dur_sec, cat_song["thumbnail"], vid_id)

        # 2. Live InnerTube resolution
        try:
            from inntertube import get_video_info_fast, parse_video_info
            raw = await get_video_info_fast(vid_id)
            if raw:
                info = parse_video_info(raw, vid_id)
                dur_sec = info.get("duration", 210)
                dur_min = info.get("duration_string", "3:30")
                return (info.get("title", f"Video {vid_id}"), dur_min, dur_sec, info.get("thumbnail"), vid_id)
        except Exception as e:
            logger.warning(f"Live details resolution failed for {vid_id}: {e}")

        return (f"YouTube Track {vid_id}", "3:30", 210, f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg", vid_id)

    async def track(self, link: str, videoid: Union[bool, str] = None) -> Tuple[str, str, int, str, str]:
        """Alias for details()"""
        return await self.details(link, videoid)

    async def title(self, link: str, videoid: Union[bool, str] = None) -> str:
        res = await self.details(link, videoid)
        return res[0]

    async def duration(self, link: str, videoid: Union[bool, str] = None) -> str:
        res = await self.details(link, videoid)
        return res[1]

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None) -> str:
        res = await self.details(link, videoid)
        return res[3]

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search tracks via 3-Way Async Race Engine."""
        from search_engine import race_search
        return await race_search(query, limit=limit)

    async def formats(self, link: str, videoid: Union[bool, str] = None) -> Tuple[List[Dict[str, str]], str]:
        vid = extract_video_id(link) or link
        formats_list = [
            {"format": "Audio (High Quality)", "ext": "m4a", "format_id": "audio"},
            {"format": "Video (720p HD)", "ext": "mp4", "format_id": "video"}
        ]
        return formats_list, link

    async def playlist(self, link: str, limit: int = 50, user_id: Any = None) -> List[str]:
        """Extract playlist tracks list."""
        from search_engine import race_search
        results = await race_search(link, limit=limit)
        return [r["id"] for r in results]

    async def stream_url(self, link: str, type: str = "audio") -> str:
        """Get direct stream URL for PyTgCalls / FFmpeg."""
        vid_id = extract_video_id(link)
        
        # Check catalog vault
        from song_catalog import catalog
        cat_song = catalog.get_by_id(vid_id)
        if cat_song and cat_song.get("stream_url") and cat_song["stream_url"].startswith("http"):
            return cat_song["stream_url"]

        # Return EchoAPI direct stream endpoint URL
        return f"{self.base_url}/api/musicbot/stream/{vid_id}?quality=high&api_key={self.api_key}"

    async def video(self, link: str, videoid: Union[bool, str] = None) -> Tuple[int, Optional[str]]:
        """PyTgCalls voice/video chat stream tuple: (1, stream_url)."""
        if videoid and isinstance(videoid, str):
            link = f"https://www.youtube.com/watch?v={videoid}"
        try:
            url = await self.stream_url(link, type="video")
            return 1, url
        except Exception as e:
            logger.error(f"Video stream error: {e}")
            return 0, None

    async def download(
        self,
        link: str,
        mystic: Any = None,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> Tuple[str, bool]:
        """
        Download track stream URL for PyTgCalls / FFmpeg playback.
        Returns: (stream_url_or_path, True)
        """
        if videoid and isinstance(videoid, str):
            link = f"https://www.youtube.com/watch?v={videoid}"
        
        req_type = "video" if (video or songvideo or format_id == "video") else "audio"
        stream_link = await self.stream_url(link, type=req_type)
        return stream_link, True

    async def is_live(self, link: str, videoid: Union[bool, str] = None) -> bool:
        return False

# Global Singleton Alias
YouTube = YouTubeAPI
