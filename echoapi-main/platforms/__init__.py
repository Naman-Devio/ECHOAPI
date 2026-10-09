"""
EchoAPI Universal Multi-Platform Engine
Exports:
- extract_platform_media(url: str) -> Optional[PlatformResult]
- detect_platform(url: str) -> Optional[str]
- stream_media_pipe(url: str, request: Request)
"""
import time
import logging
from typing import Optional, Dict, Tuple
from platforms.base import PlatformResult
from platforms.pinterest import PinterestExtractor
from platforms.tiktok import TikTokExtractor
from platforms.instagram import InstagramExtractor
from platforms.twitter import TwitterExtractor
from platforms.stream_pipe import stream_media_pipe

logger = logging.getLogger(__name__)

# Register all platform extractors
EXTRACTORS = [
    PinterestExtractor(),
    TikTokExtractor(),
    InstagramExtractor(),
    TwitterExtractor(),
]

# Simple in-memory cache with TTL (1 hour)
_CACHE: Dict[str, Tuple[PlatformResult, float]] = {}
CACHE_TTL = 3600


def detect_platform(url: str) -> Optional[str]:
    """Identify which social platform a URL belongs to."""
    if not url:
        return None
    for extractor in EXTRACTORS:
        if extractor.match(url):
            return extractor.platform_name
    return None


async def extract_platform_media(url: str) -> Optional[PlatformResult]:
    """
    Universal media extractor dispatcher.
    Auto-detects platform, checks cache, and dispatches to appropriate extractor.
    """
    if not url:
        return None

    clean_url = url.strip()

    # 1. Check in-memory cache
    now = time.time()
    if clean_url in _CACHE:
        cached_res, timestamp = _CACHE[clean_url]
        if now - timestamp < CACHE_TTL:
            cached_res.cached = True
            return cached_res
        else:
            del _CACHE[clean_url]

    # 2. Dispatch to matching extractor
    for extractor in EXTRACTORS:
        if extractor.match(clean_url):
            logger.info(f"Dispatching {clean_url[:60]} to {extractor.platform_name} extractor")
            result = await extractor.extract(clean_url)
            if result:
                _CACHE[clean_url] = (result, now)
                return result
            else:
                logger.warning(f"Extractor {extractor.platform_name} returned no results for {clean_url[:60]}")

    return None
