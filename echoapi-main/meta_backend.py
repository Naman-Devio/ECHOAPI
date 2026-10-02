"""
🌌 Upstream Meta Backend Provider (BabiesIQ Engine)
Forwards song & video requests to https://api.babiesiq.tech to fetch
high-speed audio and video streams without triggering YouTube bot-detection.
All streams are piped through EchoAPI so no third-party branding is leaked.
"""

import os
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

BABIESIQ_API_KEY = (os.getenv("BABIESIQ_API_KEY") or "").strip() or "BABYXF_3B7CB04DD14B37C2A7945985DFC1C35C324CE6DB"
BABIESIQ_API_URL = (os.getenv("BABIESIQ_API_URL") or "https://api.babiesiq.tech").strip().rstrip("/")

async def fetch_meta_backend_song(query_or_vid: str, eq: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Query the upstream BabiesIQ backend for a song's direct stream URL.
    Returns: {"stream": "https://api.babiesiq.tech/api/stream/...", "stream_id": "...", "status": "ok"}
    """
    if not BABIESIQ_API_KEY or not query_or_vid:
        return None
    
    url = f"{BABIESIQ_API_URL}/api/song"
    params = {"query": query_or_vid}
    if eq:
        params["eq"] = eq
    
    headers = {
        "X-API-Key": BABIESIQ_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }
    
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                stream_url = data.get("stream") or data.get("stream_url") or data.get("url")
                if stream_url and str(stream_url).startswith("http"):
                    data["stream"] = stream_url
                    logger.info(f"✓ Meta backend resolved song stream for {query_or_vid} (status={data.get('status')})")
                    return data
                else:
                    logger.warning(f"Meta backend returned HTTP 200 without valid stream for {query_or_vid}: {data}")
            else:
                logger.warning(f"Meta backend returned HTTP {resp.status_code} for {query_or_vid}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Meta backend error for {query_or_vid}: {e}")
    
    return None

async def fetch_meta_backend_video(query_or_vid: str) -> Optional[Dict[str, Any]]:
    """
    Query the upstream BabiesIQ backend for a video's direct stream URL.
    """
    if not BABIESIQ_API_KEY or not query_or_vid:
        return None
    
    url = f"{BABIESIQ_API_URL}/api/video"
    params = {"query": query_or_vid}
    headers = {
        "X-API-Key": BABIESIQ_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }
    
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                stream_url = data.get("stream") or data.get("stream_url") or data.get("url")
                if stream_url and str(stream_url).startswith("http"):
                    data["stream"] = stream_url
                    logger.info(f"✓ Meta backend resolved video stream for {query_or_vid} (status={data.get('status')})")
                    return data
                else:
                    logger.warning(f"Meta backend returned HTTP 200 without valid stream for {query_or_vid}: {data}")
            else:
                logger.warning(f"Meta backend returned HTTP {resp.status_code} for {query_or_vid}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Meta backend video error for {query_or_vid}: {e}")
    
    return None
