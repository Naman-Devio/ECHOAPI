"""
🎵 TikTok Extractor for EchoAPI
Supports:
- Watermark-Free HD Videos (1080p/720p MP4)
- Original Sound / Music Extraction (MP3)
- Photo Slideshow / Gallery Posts
- Shortlinks (vm.tiktok.com/..., vt.tiktok.com/...)
- Creator Profiles & Statistics
"""
import re
import json
import logging
import asyncio
from typing import Optional, List, Dict, Any
import httpx
import yt_dlp

from platforms.base import BasePlatformExtractor, PlatformResult, MediaFormat, PlatformAuthor

logger = logging.getLogger(__name__)

TIKTOK_STANDARD_REGEX = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([^/?#]+)/video/(\d+)",
    re.IGNORECASE
)
TIKTOK_SHORT_REGEX = re.compile(
    r"https?://(?:vm|vt|v)\.tiktok\.com/([a-zA-Z0-9]+)",
    re.IGNORECASE
)
TIKTOK_ANY_REGEX = re.compile(
    r"https?://(?:[a-zA-Z0-9_\.]+\.)?tiktok\.com/",
    re.IGNORECASE
)


class TikTokExtractor(BasePlatformExtractor):
    platform_name = "tiktok"

    def match(self, url: str) -> bool:
        return bool(TIKTOK_ANY_REGEX.search(url))

    async def unshorten_url(self, url: str) -> str:
        """Resolve vm.tiktok.com and vt.tiktok.com shortlinks."""
        if not TIKTOK_SHORT_REGEX.search(url):
            return url
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.head(url, headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                })
                resolved = str(resp.url)
                logger.info(f"Resolved TikTok shortlink: {url} -> {resolved}")
                return resolved
        except Exception as e:
            logger.warning(f"Failed to unshorten TikTok URL {url}: {e}")
            return url

    async def extract(self, url: str) -> Optional[PlatformResult]:
        canonical_url = await self.unshorten_url(url)
        
        # Extract video ID if present
        video_id = "tiktok_item"
        match = TIKTOK_STANDARD_REGEX.search(canonical_url)
        if match:
            video_id = match.group(2)

        # ── Tier 1: Direct No-Watermark API (The DataSocial Aweme Method) ──
        try:
            result = await self._extract_nowm_api(canonical_url, video_id)
            if result:
                return result
        except Exception as e:
            logger.warning(f"TikTok Tier 1 No-WM API failed for {video_id}: {e}")

        # ── Tier 2: yt-dlp TikTok Extractor Fallback ──
        try:
            result = await self._extract_ytdlp(canonical_url, video_id)
            if result:
                return result
        except Exception as e:
            logger.warning(f"TikTok Tier 2 yt-dlp failed for {video_id}: {e}")

        return None

    async def _extract_nowm_api(self, url: str, video_id: str) -> Optional[PlatformResult]:
        """
        Query public Aweme/TikWM resolver to obtain clean, unwatermarked HD video and audio.
        """
        api_endpoint = "https://www.tikwm.com/api/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        params = {"url": url, "hd": 1}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(api_endpoint, data=params, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"TikWM API returned HTTP {resp.status_code}")
                return None
            data = resp.json()

        if data.get("code") != 0 or not data.get("data"):
            logger.warning(f"TikWM error code: {data.get('msg')}")
            return None

        item = data["data"]
        real_id = str(item.get("id") or video_id)
        title = item.get("title") or f"TikTok Video {real_id}"
        duration = float(item.get("duration", 0))
        thumbnail = item.get("cover") or item.get("origin_cover")
        
        author_info = item.get("author", {})
        author = PlatformAuthor(
            username=author_info.get("unique_id"),
            name=author_info.get("nickname"),
            avatar=author_info.get("avatar"),
            url=f"https://www.tiktok.com/@{author_info.get('unique_id')}" if author_info.get("unique_id") else None
        )

        formats: List[MediaFormat] = []
        media_type = "video"

        # Check if it's a photo gallery / slideshow post
        images = item.get("images")
        if images and isinstance(images, list):
            media_type = "carousel"
            for idx, img_url in enumerate(images):
                formats.append(MediaFormat(
                    format_id=f"slide_{idx + 1}",
                    type="image",
                    url=img_url,
                    direct_url=img_url,
                    quality="original",
                    ext="jpg",
                    has_audio=False
                ))

        # 1. High Definition No-Watermark Video (HD)
        hd_play = item.get("hdplay")
        if hd_play:
            formats.append(MediaFormat(
                format_id="nowm_1080p",
                type="video",
                url=f"/api/stream?url={httpx.URL(hd_play)}",
                direct_url=hd_play,
                quality="1080p HD (No Watermark)",
                ext="mp4",
                has_audio=True
            ))

        # 2. Standard No-Watermark Video
        play = item.get("play")
        if play:
            formats.append(MediaFormat(
                format_id="nowm_720p",
                type="video",
                url=f"/api/stream?url={httpx.URL(play)}",
                direct_url=play,
                quality="720p (No Watermark)",
                ext="mp4",
                has_audio=True
            ))

        # 3. Watermarked Video (Optional)
        wmplay = item.get("wmplay")
        if wmplay:
            formats.append(MediaFormat(
                format_id="watermark_720p",
                type="video",
                url=f"/api/stream?url={httpx.URL(wmplay)}",
                direct_url=wmplay,
                quality="720p (With Watermark)",
                ext="mp4",
                has_audio=True
            ))

        # 4. Original Audio / Music MP3
        music_url = item.get("music")
        if music_url:
            music_info = item.get("music_info", {})
            formats.append(MediaFormat(
                format_id="audio_original",
                type="audio",
                url=f"/api/stream?url={httpx.URL(music_url)}",
                direct_url=music_url,
                quality="128kbps (Original Sound)",
                ext="mp3",
                has_audio=True
            ))

        if not formats:
            return None

        primary_download = formats[0].url

        return PlatformResult(
            success=True,
            platform="tiktok",
            id=real_id,
            url=url,
            title=title,
            description=title,
            author=author,
            thumbnail=thumbnail,
            duration=duration,
            duration_string=f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else None,
            media_type=media_type,
            formats=formats,
            download_url=primary_download,
            extra={
                "play_count": item.get("play_count"),
                "digg_count": item.get("digg_count"),
                "comment_count": item.get("comment_count"),
                "share_count": item.get("share_count"),
            }
        )

    async def _extract_ytdlp(self, url: str, video_id: str) -> Optional[PlatformResult]:
        loop = asyncio.get_running_loop()
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'socket_timeout': 15,
            'extractor_args': {
                'tiktok': {
                    'app_version': ['34.1.2'],
                }
            }
        }

        def _sync_extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = await loop.run_in_executor(None, _sync_extract)
        if not info:
            return None

        formats: List[MediaFormat] = []
        for f in info.get("formats", []):
            f_url = f.get("url")
            if not f_url:
                continue
            height = f.get("height")
            formats.append(MediaFormat(
                format_id=f.get("format_id"),
                type="video" if f.get("vcodec") not in (None, "none") else "audio",
                url=f"/api/stream?url={httpx.URL(f_url)}",
                direct_url=f_url,
                quality=f"{height}p" if height else f.get("format_note"),
                ext=f.get("ext", "mp4"),
                width=f.get("width"),
                height=height,
                filesize=f.get("filesize"),
                has_audio=bool(f.get("acodec") not in (None, "none"))
            ))

        return PlatformResult(
            success=True,
            platform="tiktok",
            id=str(info.get("id") or video_id),
            url=url,
            title=info.get("title") or f"TikTok Video {video_id}",
            description=info.get("description"),
            author=PlatformAuthor(name=info.get("uploader"), username=info.get("uploader_id")),
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
            media_type="video",
            formats=formats,
            download_url=formats[0].url if formats else None
        )
