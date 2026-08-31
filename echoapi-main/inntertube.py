"""
Fast YouTube InnerTube API - Async HTTP extraction (no yt-dlp overhead)
=======================================================================
Uses raw async httpx for direct YouTube InnerTube API calls.
Bypasses yt-dlp entirely for /api/info and /api/search endpoints.

Response time: ~300-800ms for info, ~1000-2000ms for search.
"""

import re
import time
import json
import logging
from typing import Optional, Dict, List, Any

import httpx

logger = logging.getLogger(__name__)

# ─── Reusable async HTTP client ──────────────────────────────────────────────
_http_client: Optional[httpx.AsyncClient] = None

INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
INNERTUBE_BASE = "https://www.youtube.com/youtubei/v1"
WEB_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-YouTube-Client-Name": "1",
    "X-YouTube-Client-Version": "2.20250101.00.00",
    "Origin": "https://www.youtube.com",
    "Referer": "https://www.youtube.com/",
}


async def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
            follow_redirects=True,
        )
    return _http_client


async def close_http_client():
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# ─── Video ID Extraction ─────────────────────────────────────────────────────
_YT_ID_PATTERNS = [
    r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
    r'^([a-zA-Z0-9_-]{11})$',
]


def extract_video_id(url: str) -> Optional[str]:
    for pattern in _YT_ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# ─── Fast Video Info (~300-800ms) ───────────────────────────────────────────
async def get_video_info_fast(video_id: str, client: str = "web", proxy: str = None, po_token: str = None, visitor_data: str = None) -> Optional[Dict]:
    """Fetch video info directly from YouTube InnerTube API (async).
    
    Args:
        video_id: YouTube video ID
        client: Client type (currently always uses WEB)
        proxy: Optional HTTP proxy
        po_token: Optional PO token for streaming data from cloud IPs
        visitor_data: Optional visitor data (must match the PO token)
    """
    ctx_client = {
        "clientName": "WEB",
        "clientVersion": "2.20250101.00.00",
        "hl": "en",
        "gl": "US",
    }
    
    # Add visitor_data if provided (required for PO token auth)
    if visitor_data:
        ctx_client["visitorData"] = visitor_data

    payload = {
        "context": {
            "client": ctx_client,
        },
        "videoId": video_id,
    }
    
    # Add PO token for streaming data (bypasses cloud IP blocking)
    if po_token:
        payload["serviceIntegrityDimensions"] = {
            "poToken": po_token,
        }
        logger.debug(f"InnerTube request with PO token for {video_id}")

    url = f"{INNERTUBE_BASE}/player?key={INNERTUBE_API_KEY}"
    try:
        if proxy:
            # Use a one-off client with proxy
            async with httpx.AsyncClient(proxy=proxy, timeout=15.0) as c:
                resp = await c.post(url, json=payload, headers=WEB_HEADERS)
                resp.raise_for_status()
                return resp.json()
        else:
            c = await _get_client()
            resp = await c.post(url, json=payload, headers=WEB_HEADERS)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"InnerTube player failed for {video_id}: {e}")
        return None


def parse_video_info(data: Dict, video_id: str) -> Dict:
    """Parse InnerTube response into clean video info dict."""
    vd = data.get("videoDetails", {})
    mf = data.get("microformat", {}).get("playerMicroformatRenderer", {})

    title = vd.get("title", "Unknown")
    duration = int(vd.get("lengthSeconds", 0))
    view_count = int(vd.get("viewCount", 0))

    thumbnails_raw = vd.get("thumbnail", {}).get("thumbnails", [])
    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
    if thumbnails_raw:
        thumbnail_url = thumbnails_raw[-1].get("url", thumbnail_url)

    uploader = vd.get("author", "Unknown")
    channel_id = vd.get("channelId", "")
    channel_url = f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""
    description = vd.get("shortDescription", "")
    tags = vd.get("keywords", [])

    upload_date_raw = mf.get("uploadDate", "")
    upload_date = upload_date_raw.replace("-", "") if upload_date_raw else ""

    # Available formats
    sd = data.get("streamingData", {})
    all_fmts = sd.get("formats", []) + sd.get("adaptiveFormats", [])
    available_formats = sorted({f"{f['height']}p" for f in all_fmts if f.get("height")})

    return {
        "id": video_id,
        "title": title,
        "uploader": uploader,
        "channel_url": channel_url,
        "duration": duration,
        "duration_string": _format_duration(duration),
        "view_count": view_count,
        "like_count": None,
        "thumbnail": thumbnail_url,
        "thumbnails": [
            {"url": t.get("url"), "width": t.get("width"), "height": t.get("height")}
            for t in thumbnails_raw[-3:]
        ],
        "description": description[:500],
        "tags": tags[:10],
        "upload_date": upload_date,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "available_formats": available_formats,
    }


def _format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ─── Fast Search (~1000-2000ms) ─────────────────────────────────────────────
async def search_youtube_fast(query: str, max_results: int = 5) -> List[Dict]:
    """Search YouTube directly via InnerTube API (async, no proxy)."""
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20250101.00.00",
                "hl": "en",
                "gl": "US",
            },
        },
        "query": query,
    }

    url = f"{INNERTUBE_BASE}/search?key={INNERTUBE_API_KEY}"
    try:
        c = await _get_client()
        resp = await c.post(url, json=payload, headers=WEB_HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"InnerTube search failed: {e}")
        return []

    results = []
    contents = (
        data.get("contents", {})
        .get("twoColumnSearchResultsRenderer", {})
        .get("primaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents", [])
    )

    for section in contents:
        items = section.get("itemSectionRenderer", {}).get("contents", [])
        for item in items:
            vr = item.get("videoRenderer")
            if not vr:
                continue

            vid = vr.get("videoId", "")
            if not vid:
                continue

            title = _extract_text(vr.get("title", {}))
            channel = _extract_text(vr.get("ownerText", {}))
            view_text = _extract_text(vr.get("viewCountText", {}))
            duration_text = _extract_text(vr.get("lengthText", {}))

            view_count = 0
            if view_text:
                m = re.search(r'([\d,]+)', view_text.replace(",", ""))
                if m:
                    view_count = int(m.group(1).replace(",", ""))

            duration = 0
            if duration_text:
                parts = duration_text.split(":")
                try:
                    if len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                except ValueError:
                    pass

            thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
            thumb_url = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            if thumbs:
                thumb_url = thumbs[-1].get("url", thumb_url)

            results.append({
                "id": vid,
                "title": title,
                "url": f"https://youtube.com/watch?v={vid}",
                "duration": duration,
                "duration_string": _format_duration(duration),
                "thumbnail": thumb_url,
                "uploader": channel,
                "view_count": view_count,
            })

            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    return results


def _extract_text(text_obj: Dict) -> str:
    if not text_obj:
        return ""
    runs = text_obj.get("runs", [])
    if runs:
        return "".join(r.get("text", "") for r in runs)
    return text_obj.get("simpleText", "")


# ─── Fast Stream URL Extraction ──────────────────────────────────────────────
async def get_stream_urls_fast(video_id: str, po_token: str = None, visitor_data: str = None) -> Dict:
    """Get audio/video stream URLs from InnerTube."""
    data = await get_video_info_fast(video_id, po_token=po_token, visitor_data=visitor_data)
    if not data:
        return {"audio": None, "video": None}

    sd = data.get("streamingData", {})
    formats = sd.get("formats", [])
    adaptive = sd.get("adaptiveFormats", [])

    audio_streams = [f for f in adaptive if "audio" in f.get("mimeType", "") and f.get("url")]
    audio_streams.sort(key=lambda x: x.get("bitrate", 0), reverse=True)

    combined = [f for f in formats if f.get("url") and f.get("audioQuality")]
    combined.sort(key=lambda x: x.get("height", 0), reverse=True)

    video_streams = [f for f in adaptive if "video" in f.get("mimeType", "") and f.get("url") and not f.get("audioQuality")]
    video_streams.sort(key=lambda x: x.get("height", 0), reverse=True)

    best_audio = audio_streams[0] if audio_streams else None
    best_video = video_streams[0] if video_streams else None
    best_combined = combined[0] if combined else None

    return {
        "audio": {
            "url": best_audio.get("url") if best_audio else None,
            "format": best_audio.get("mimeType", "").split(";")[0] if best_audio else None,
            "bitrate": best_audio.get("bitrate") if best_audio else None,
        } if best_audio else None,
        "video": {
            "url": (best_video or best_combined or {}).get("url"),
            "height": (best_video or best_combined or {}).get("height"),
            "width": (best_video or best_combined or {}).get("width"),
            "format": ((best_video or best_combined or {}).get("mimeType", "") or "").split(";")[0],
        } if best_video or best_combined else None,
    }
