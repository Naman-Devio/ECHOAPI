"""
📌 Pinterest Extractor for EchoAPI
Supports:
- Video Pins (MP4 720p/1080p, HLS)
- Original 4K/HD Image Pins (i.pinimg.com/originals)
- Idea/Story Pins
- Shortlinks (pin.it/...)
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

PINTEREST_REGEX = re.compile(
    r"https?://(?:[a-zA-Z]{2,3}\.)?pinterest\.(?:com|[a-z]{2,3}(?:\.[a-z]{2})?)/pin/(\d+)",
    re.IGNORECASE
)
PIN_IT_REGEX = re.compile(
    r"https?://(?:www\.)?pin\.it/([a-zA-Z0-9]+)",
    re.IGNORECASE
)


class PinterestExtractor(BasePlatformExtractor):
    platform_name = "pinterest"

    def match(self, url: str) -> bool:
        return bool(PINTEREST_REGEX.search(url) or PIN_IT_REGEX.search(url))

    async def unshorten_url(self, url: str) -> str:
        """Resolve pin.it shortlinks to canonical pinterest.com/pin/... URL."""
        if not PIN_IT_REGEX.search(url):
            return url
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.head(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                resolved = str(resp.url)
                logger.info(f"Resolved pin.it shortlink: {url} -> {resolved}")
                return resolved
        except Exception as e:
            logger.warning(f"Failed to unshorten pin.it URL {url}: {e}")
            return url

    async def extract(self, url: str) -> Optional[PlatformResult]:
        canonical_url = await self.unshorten_url(url)
        match = PINTEREST_REGEX.search(canonical_url)
        pin_id = match.group(1) if match else "unknown"

        # ── Tier 1: Direct JSON-LD & __PWS_DATA__ Scraper (< 200ms) ──
        try:
            result = await self._extract_direct(canonical_url, pin_id)
            if result:
                return result
        except Exception as e:
            logger.warning(f"Pinterest Tier 1 direct extraction failed for {pin_id}: {e}")

        # ── Tier 2: yt-dlp Pinterest Fallback ──
        try:
            result = await self._extract_ytdlp(canonical_url, pin_id)
            if result:
                return result
        except Exception as e:
            logger.warning(f"Pinterest Tier 2 yt-dlp extraction failed for {pin_id}: {e}")

        return None

    async def _extract_direct(self, url: str, pin_id: str) -> Optional[PlatformResult]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Pinterest page returned HTTP {resp.status_code}")
                return None
            html = resp.text

        title = f"Pinterest Pin {pin_id}"
        description = None
        thumbnail = None
        author_name = "Pinterest Creator"
        author_user = None
        media_type = "image"
        formats: List[MediaFormat] = []

        # 1. Inspect JSON-LD for rich structured schema
        json_ld_matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        for j_str in json_ld_matches:
            try:
                j_data = json.loads(j_str.strip())
                if isinstance(j_data, dict):
                    if j_data.get("name"):
                        title = j_data.get("name")
                    if j_data.get("description"):
                        description = j_data.get("description")
                    if j_data.get("image"):
                        thumbnail = j_data.get("image")
                    if j_data.get("creator") and isinstance(j_data["creator"], dict):
                        author_name = j_data["creator"].get("name") or author_name
                    
                    # Video Object in JSON-LD
                    if j_data.get("@type") == "VideoObject" or "contentUrl" in j_data:
                        v_url = j_data.get("contentUrl")
                        if v_url:
                            media_type = "video"
                            formats.append(MediaFormat(
                                format_id="json_ld_video",
                                type="video",
                                url=f"/api/stream?url={httpx.URL(v_url)}",
                                direct_url=v_url,
                                quality="720p",
                                ext="mp4",
                                has_audio=True
                            ))
            except Exception:
                continue

        # 2. Inspect __PWS_DATA__ (contains direct raw video URLs and original uncompressed images)
        pws_text = None
        pws_idx = html.find('id="__PWS_DATA__"')
        if pws_idx != -1:
            tag_end = html.find('>', pws_idx)
            script_end = html.find('</script>', tag_end)
            if tag_end != -1 and script_end != -1:
                pws_text = html[tag_end+1:script_end].strip()

        if pws_text:
            try:
                pws = json.loads(pws_text)
                # Search recursively for video_list or images
                videos_dict, images_dict = self._search_pws_media(pws)
                if videos_dict:
                    media_type = "video"
                    for key, val in videos_dict.items():
                        if isinstance(val, dict) and val.get("url"):
                            v_url = val["url"]
                            if v_url.endswith(".mp4"):
                                width = val.get("width")
                                height = val.get("height")
                                quality = f"{height}p" if height else key
                                formats.append(MediaFormat(
                                    format_id=f"pws_{key.lower()}",
                                    type="video",
                                    url=f"/api/stream?url={httpx.URL(v_url)}",
                                    direct_url=v_url,
                                    quality=quality,
                                    ext="mp4",
                                    width=width,
                                    height=height,
                                    has_audio=True
                                ))
                
                # Check original high-res image
                if images_dict and isinstance(images_dict, dict):
                    orig = images_dict.get("orig") or images_dict.get("originals")
                    if orig and isinstance(orig, dict) and orig.get("url"):
                        img_url = orig["url"]
                        thumbnail = thumbnail or img_url
                        if media_type != "video":
                            formats.append(MediaFormat(
                                format_id="pws_original_image",
                                type="image",
                                url=img_url,
                                direct_url=img_url,
                                quality="original",
                                ext=img_url.split(".")[-1].split("?")[0] or "jpg",
                                width=orig.get("width"),
                                height=orig.get("height"),
                                has_audio=False
                            ))
            except Exception as pe:
                logger.debug(f"PWS JSON parse error: {pe}")

        # 3. Fallback direct regex search for v.pinimg.com video URLs
        if not formats:
            direct_mp4s = list(set(re.findall(r'https://v\.pinimg\.com/videos/[^"\']+\.mp4', html)))
            for mp4 in direct_mp4s:
                media_type = "video"
                formats.append(MediaFormat(
                    format_id="direct_pinimg_mp4",
                    type="video",
                    url=f"/api/stream?url={httpx.URL(mp4)}",
                    direct_url=mp4,
                    quality="720p",
                    ext="mp4",
                    has_audio=True
                ))

        # 4. OpenGraph og:video and og:image fallback
        if not formats:
            og_video = re.search(r'property="og:video"\s*content="([^"]+)"', html) or re.search(r'content="([^"]+)"\s*property="og:video"', html)
            if og_video:
                v_url = og_video.group(1)
                media_type = "video"
                formats.append(MediaFormat(
                    format_id="og_video",
                    type="video",
                    url=f"/api/stream?url={httpx.URL(v_url)}",
                    direct_url=v_url,
                    quality="720p",
                    ext="mp4",
                    has_audio=True
                ))
            else:
                og_img = re.search(r'property="og:image"\s*content="([^"]+)"', html) or re.search(r'content="([^"]+)"\s*property="og:image"', html)
                if og_img:
                    img_url = og_img.group(1)
                    thumbnail = thumbnail or img_url
                    formats.append(MediaFormat(
                        format_id="og_image",
                        type="image",
                        url=img_url,
                        direct_url=img_url,
                        quality="high",
                        ext="jpg",
                        has_audio=False
                    ))

        # Fallback image search if no formats found
        if not formats and thumbnail:
            formats.append(MediaFormat(
                format_id="pinterest_image",
                type="image",
                url=thumbnail,
                direct_url=thumbnail,
                quality="high",
                ext="jpg",
                has_audio=False
            ))

        if not formats:
            return None

        # Sort video formats by resolution descending
        if media_type == "video":
            formats.sort(key=lambda f: f.height or 0, reverse=True)

        download_url = formats[0].url if formats else None

        return PlatformResult(
            success=True,
            platform="pinterest",
            id=pin_id,
            url=url,
            title=title,
            description=description,
            author=PlatformAuthor(name=author_name, username=author_user),
            thumbnail=thumbnail,
            media_type=media_type,
            formats=formats,
            download_url=download_url
        )

    def _search_pws_media(self, data: Any) -> tuple:
        """Recursively search for video_list and images inside __PWS_DATA__ tree."""
        found_videos = None
        found_images = None

        if isinstance(data, dict):
            if "video_list" in data and isinstance(data["video_list"], dict):
                found_videos = data["video_list"]
            if "images" in data and isinstance(data["images"], dict):
                found_images = data["images"]

            for k, v in data.items():
                if found_videos and found_images:
                    break
                sub_v, sub_i = self._search_pws_media(v)
                if not found_videos and sub_v:
                    found_videos = sub_v
                if not found_images and sub_i:
                    found_images = sub_i

        elif isinstance(data, list):
            for item in data:
                if found_videos and found_images:
                    break
                sub_v, sub_i = self._search_pws_media(item)
                if not found_videos and sub_v:
                    found_videos = sub_v
                if not found_images and sub_i:
                    found_images = sub_i

        return found_videos, found_images

    async def _extract_ytdlp(self, url: str, pin_id: str) -> Optional[PlatformResult]:
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
            platform="pinterest",
            id=pin_id,
            url=url,
            title=info.get("title") or f"Pinterest Pin {pin_id}",
            description=info.get("description"),
            author=PlatformAuthor(name=info.get("uploader")),
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
            media_type="video" if formats else "image",
            formats=formats,
            download_url=formats[0].url if formats else None
        )
