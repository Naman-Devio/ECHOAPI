"""
🐦 Twitter / X Extractor for EchoAPI
Supports:
- Video Tweets across all bitrates (1080p, 720p, 480p, 320p MP4)
- Animated GIFs (MP4 looping)
- Photo Tweets (Original 4K/HD JPG)
- High-speed Twitter Syndication API (< 100ms, zero authentication needed)
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

TWITTER_REGEX = re.compile(
    r"https?://(?:(?:www\.)?twitter\.com|(?:www\.)?x\.com)/(?:[^/]+)/status/(\d+)",
    re.IGNORECASE
)


def _to_base36(num: float) -> str:
    """Convert float to base36 string representation."""
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    int_part = int(num)
    frac_part = num - int_part
    res = ""
    while int_part > 0:
        res = chars[int_part % 36] + res
        int_part //= 36
    res = res or "0"
    res += "."
    for _ in range(12):
        frac_part *= 36
        d = int(frac_part)
        res += chars[d]
        frac_part -= d
    return res


def _get_syndication_token(tweet_id: str) -> str:
    """Compute Twitter embed syndication API token based on tweet ID."""
    import math
    raw = (float(tweet_id) / 1e15) * math.pi
    b36 = _to_base36(raw)
    return b36.replace(".", "").replace("0", "")


class TwitterExtractor(BasePlatformExtractor):
    platform_name = "twitter"

    def match(self, url: str) -> bool:
        return bool(TWITTER_REGEX.search(url))

    def extract_tweet_id(self, url: str) -> Optional[str]:
        match = TWITTER_REGEX.search(url)
        return match.group(1) if match else None

    async def extract(self, url: str) -> Optional[PlatformResult]:
        tweet_id = self.extract_tweet_id(url)
        if not tweet_id:
            return None

        # ── Tier 1: Twitter Syndication API (Fastest, zero-auth, < 100ms) ──
        try:
            result = await self._extract_syndication(tweet_id, url)
            if result:
                logger.info(f"✓ Twitter Syndication API extracted tweet {tweet_id}")
                return result
        except Exception as e:
            logger.warning(f"Twitter Tier 1 Syndication API failed for {tweet_id}: {e}")

        # ── Tier 2: yt-dlp Twitter Extractor Fallback ──
        try:
            result = await self._extract_ytdlp(url, tweet_id)
            if result:
                logger.info(f"✓ Twitter Tier 2 yt-dlp extracted tweet {tweet_id}")
                return result
        except Exception as e:
            logger.warning(f"Twitter Tier 2 yt-dlp failed for {tweet_id}: {e}")

        return None

    async def _extract_syndication(self, tweet_id: str, source_url: str) -> Optional[PlatformResult]:
        """
        Query Twitter's official syndication embed API with calculated token.
        Returns full video streams and highest quality MP4 variants.
        """
        token = _get_syndication_token(tweet_id)
        api_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token={token}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://platform.twitter.com/",
        }

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(api_url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Twitter Syndication returned HTTP {resp.status_code}")
                return None
            data = resp.json()

        text = data.get("text", f"Twitter Status {tweet_id}")
        user_data = data.get("user", {})
        author = PlatformAuthor(
            name=user_data.get("name"),
            username=user_data.get("screen_name"),
            avatar=user_data.get("profile_image_url_https"),
            url=f"https://x.com/{user_data.get('screen_name')}" if user_data.get("screen_name") else None
        )

        media_type = "video"
        thumbnail = None
        formats: List[MediaFormat] = []

        # 1. Video and Animated GIF variants
        video_data = data.get("video")
        if video_data and isinstance(video_data, dict):
            thumbnail = video_data.get("poster")
            variants = video_data.get("variants", [])
            # Filter mp4 files and sort by bitrate descending
            mp4_variants = [v for v in variants if v.get("type") == "video/mp4" and v.get("src")]
            mp4_variants.sort(key=lambda v: v.get("bitrate") or 0, reverse=True)

            for v in mp4_variants:
                src = v["src"]
                bitrate = v.get("bitrate") or 0
                # Approximate quality tag based on bitrate
                if bitrate > 1500000:
                    quality = "1080p HD"
                elif bitrate > 700000:
                    quality = "720p"
                elif bitrate > 400000:
                    quality = "480p"
                else:
                    quality = "320p"

                formats.append(MediaFormat(
                    format_id=f"twitter_{bitrate}",
                    type="video",
                    url=f"/api/stream?url={httpx.URL(src)}",
                    direct_url=src,
                    quality=quality,
                    ext="mp4",
                    bitrate=bitrate,
                    has_audio=True
                ))

        # 2. Photos / Images if no video
        media_details = data.get("mediaDetails", [])
        if not formats and media_details:
            media_type = "image"
            for idx, m in enumerate(media_details):
                m_url = m.get("media_url_https")
                if m_url:
                    thumbnail = thumbnail or m_url
                    formats.append(MediaFormat(
                        format_id=f"photo_{idx + 1}",
                        type="image",
                        url=m_url,
                        direct_url=m_url,
                        quality="original",
                        ext="jpg",
                        has_audio=False
                    ))

        if not formats:
            return PlatformResult(
                success=True,
                platform="twitter",
                id=tweet_id,
                url=source_url,
                title=text[:120] if text else f"Tweet {tweet_id}",
                description=text,
                author=author,
                thumbnail=thumbnail,
                media_type="text",
                formats=[],
                download_url=None,
                extra={
                    "favorite_count": data.get("favorite_count"),
                    "reply_count": data.get("reply_count"),
                }
            )

        return PlatformResult(
            success=True,
            platform="twitter",
            id=tweet_id,
            url=source_url,
            title=text[:120] if text else f"Tweet {tweet_id}",
            description=text,
            author=author,
            thumbnail=thumbnail,
            media_type=media_type,
            formats=formats,
            download_url=formats[0].url if formats else None,
            extra={
                "favorite_count": data.get("favorite_count"),
                "reply_count": data.get("reply_count"),
            }
        )

    async def _extract_ytdlp(self, url: str, tweet_id: str) -> Optional[PlatformResult]:
        loop = asyncio.get_running_loop()
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'socket_timeout': 15,
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
            platform="twitter",
            id=tweet_id,
            url=url,
            title=info.get("title") or f"Tweet {tweet_id}",
            description=info.get("description"),
            author=PlatformAuthor(name=info.get("uploader"), username=info.get("uploader_id")),
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
            media_type="video",
            formats=formats,
            download_url=formats[0].url if formats else None
        )
