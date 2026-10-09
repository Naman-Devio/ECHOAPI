"""
📷 Instagram Extractor for EchoAPI
Supports:
- Instagram Reels (1080p/720p MP4)
- Video Posts (MP4)
- Photo Posts & Multi-Image Carousels (HD JPG)
- Audio Streams
- Fallback chain: Public Embed Captioned Scraper -> Mobile Web API -> yt-dlp with session/proxy
"""
import os
import re
import json
import logging
import asyncio
from typing import Optional, List, Dict, Any
import httpx
import yt_dlp

from platforms.base import BasePlatformExtractor, PlatformResult, MediaFormat, PlatformAuthor

logger = logging.getLogger(__name__)

INSTAGRAM_REGEX = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:reel|p|tv|stories)/([a-zA-Z0-9_\-]+)",
    re.IGNORECASE
)
INSTAGRAM_ANY_REGEX = re.compile(
    r"https?://(?:[a-zA-Z0-9_\.]+\.)?instagram\.com/",
    re.IGNORECASE
)


class InstagramExtractor(BasePlatformExtractor):
    platform_name = "instagram"

    def match(self, url: str) -> bool:
        return bool(INSTAGRAM_ANY_REGEX.search(url))

    def extract_shortcode(self, url: str) -> Optional[str]:
        match = INSTAGRAM_REGEX.search(url)
        return match.group(1) if match else None

    async def extract(self, url: str) -> Optional[PlatformResult]:
        shortcode = self.extract_shortcode(url) or "instagram_media"

        # ── Tier 1: Public Embed Captioned Scraper (Zero-Login / Unblocked) ──
        try:
            result = await self._extract_embed(shortcode, url)
            if result:
                logger.info(f"✓ Instagram Tier 1 Embed successfully extracted {shortcode}")
                return result
        except Exception as e:
            logger.warning(f"Instagram Tier 1 Embed extraction failed for {shortcode}: {e}")

        # ── Tier 2: Public Mobile GraphQL API ──
        try:
            result = await self._extract_graphql_mobile(shortcode, url)
            if result:
                logger.info(f"✓ Instagram Tier 2 Mobile GraphQL successfully extracted {shortcode}")
                return result
        except Exception as e:
            logger.warning(f"Instagram Tier 2 Mobile GraphQL failed for {shortcode}: {e}")

        # ── Tier 3: yt-dlp with Session Cookie / ProxyManager ──
        try:
            result = await self._extract_ytdlp(url, shortcode)
            if result:
                logger.info(f"✓ Instagram Tier 3 yt-dlp successfully extracted {shortcode}")
                return result
        except Exception as e:
            logger.warning(f"Instagram Tier 3 yt-dlp failed for {shortcode}: {e}")

        return None

    async def _extract_embed(self, shortcode: str, source_url: str) -> Optional[PlatformResult]:
        """
        Extract direct video and photo URLs from Instagram's public embed endpoint.
        This endpoint is unauthenticated and widely accessible across cloud IPs.
        """
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(embed_url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Instagram embed returned HTTP {resp.status_code}")
                return None
            html = resp.text

        formats: List[MediaFormat] = []
        media_type = "image"
        thumbnail = None
        title = f"Instagram Post {shortcode}"
        author_name = "Instagram User"
        author_user = None

        # 1. Search for video tag src directly in embed HTML
        video_src_match = re.search(r'<video[^>]+src="([^">]+)"', html)
        if not video_src_match:
            video_src_match = re.search(r'"video_url"\s*:\s*"([^"]+)"', html)

        if video_src_match:
            raw_video = video_src_match.group(1).replace(r"\u0026", "&").replace("&amp;", "&")
            media_type = "video"
            formats.append(MediaFormat(
                format_id="embed_video_1080p",
                type="video",
                url=f"/api/stream?url={httpx.URL(raw_video)}",
                direct_url=raw_video,
                quality="HD Video",
                ext="mp4",
                has_audio=True
            ))

        # 2. Search for high-res display image
        img_src_match = re.search(r'<img[^>]+class="EmbeddedMediaImage"[^>]+src="([^">]+)"', html)
        if not img_src_match:
            img_src_match = re.search(r'"display_url"\s*:\s*"([^"]+)"', html)

        if img_src_match:
            raw_img = img_src_match.group(1).replace(r"\u0026", "&").replace("&amp;", "&")
            thumbnail = raw_img
            if media_type != "video":
                formats.append(MediaFormat(
                    format_id="embed_image_original",
                    type="image",
                    url=f"/api/stream?url={httpx.URL(raw_img)}",
                    direct_url=raw_img,
                    quality="Original Photo",
                    ext="jpg",
                    has_audio=False
                ))

        # 3. Extract caption/title if available
        caption_match = re.search(r'<div class="Caption"[^>]*>(.*?)</div>', html, re.DOTALL)
        if caption_match:
            clean_caption = re.sub(r'<[^>]+>', '', caption_match.group(1)).strip()
            if clean_caption:
                title = clean_caption[:150]

        # 4. Extract author username
        author_match = re.search(r'<a class="Username"[^>]*href="[^"]*instagram\.com/([^/"]+)/?"[^>]*>(.*?)</a>', html)
        if author_match:
            author_user = author_match.group(1)
            author_name = re.sub(r'<[^>]+>', '', author_match.group(2)).strip() or author_user

        if not formats:
            return None

        download_url = formats[0].url if formats else None

        return PlatformResult(
            success=True,
            platform="instagram",
            id=shortcode,
            url=source_url,
            title=title,
            description=title,
            author=PlatformAuthor(
                username=author_user,
                name=author_name,
                url=f"https://www.instagram.com/{author_user}/" if author_user else None
            ),
            thumbnail=thumbnail,
            media_type=media_type,
            formats=formats,
            download_url=download_url
        )

    async def _extract_graphql_mobile(self, shortcode: str, source_url: str) -> Optional[PlatformResult]:
        """Query Instagram public mobile JSON API with mobile app spoofing."""
        api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
        headers = {
            "User-Agent": "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; Google/google; Pixel 7; cheetah; cheetah; en_US; 455432095)",
            "Accept": "*/*",
            "X-IG-App-ID": "936619743392459",
            "X-ASBD-ID": "198387",
            "X-IG-WWW-Claim": "0",
        }

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(api_url, headers=headers)
            if resp.status_code != 200:
                return None
            try:
                data = resp.json()
            except Exception:
                return None

        items = data.get("items") or [data.get("graphql", {}).get("shortcode_media")]
        if not items or not items[0]:
            return None

        item = items[0]
        media_type = "video" if item.get("video_versions") or item.get("is_video") else "image"
        formats: List[MediaFormat] = []
        thumbnail = None

        if item.get("video_versions"):
            for idx, v in enumerate(item["video_versions"]):
                v_url = v.get("url")
                if v_url:
                    formats.append(MediaFormat(
                        format_id=f"video_{v.get('height', 720)}p",
                        type="video",
                        url=f"/api/stream?url={httpx.URL(v_url)}",
                        direct_url=v_url,
                        quality=f"{v.get('height', 720)}p",
                        ext="mp4",
                        width=v.get("width"),
                        height=v.get("height"),
                        has_audio=True
                    ))

        if not formats and item.get("image_versions2", {}).get("candidates"):
            cands = item["image_versions2"]["candidates"]
            thumbnail = cands[0].get("url")
            formats.append(MediaFormat(
                format_id="photo_high",
                type="image",
                url=f"/api/stream?url={httpx.URL(thumbnail)}",
                direct_url=thumbnail,
                quality="HD Photo",
                ext="jpg",
                has_audio=False
            ))

        if not formats:
            return None

        user_info = item.get("user", {})
        caption_text = ""
        if item.get("caption") and isinstance(item["caption"], dict):
            caption_text = item["caption"].get("text", "")

        return PlatformResult(
            success=True,
            platform="instagram",
            id=shortcode,
            url=source_url,
            title=caption_text[:120] if caption_text else f"Instagram {shortcode}",
            description=caption_text,
            author=PlatformAuthor(
                username=user_info.get("username"),
                name=user_info.get("full_name"),
                avatar=user_info.get("profile_pic_url")
            ),
            thumbnail=thumbnail,
            media_type=media_type,
            formats=formats,
            download_url=formats[0].url if formats else None
        )

    async def _extract_ytdlp(self, url: str, shortcode: str) -> Optional[PlatformResult]:
        loop = asyncio.get_running_loop()
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'socket_timeout': 15,
            'extractor_args': {
                'instagram': {
                    'api_client': ['ios', 'android']
                }
            }
        }

        # Check for session cookie from environment variable or cookie file
        session_id = os.getenv("INSTAGRAM_SESSION_ID")
        if session_id:
            ydl_opts["http_headers"] = {
                "Cookie": f"sessionid={session_id};"
            }

        cookie_path = os.getenv("INSTAGRAM_COOKIES_PATH", "config/cookies/instagram.txt")
        if os.path.exists(cookie_path):
            ydl_opts["cookiefile"] = cookie_path

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
                has_audio=bool(f.get("acodec") not in (None, "none"))
            ))

        return PlatformResult(
            success=True,
            platform="instagram",
            id=shortcode,
            url=url,
            title=info.get("title") or f"Instagram Post {shortcode}",
            description=info.get("description"),
            author=PlatformAuthor(name=info.get("uploader"), username=info.get("uploader_id")),
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
            media_type="video" if formats else "image",
            formats=formats,
            download_url=formats[0].url if formats else None
        )
