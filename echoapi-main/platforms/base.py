"""
Base data models and abstract extractor for EchoAPI Multi-Platform Engine.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class MediaFormat(BaseModel):
    format_id: Optional[str] = None
    type: str = "video"  # "video", "audio", "image"
    url: str             # Streaming pipe or direct URL
    direct_url: Optional[str] = None  # Raw upstream CDN URL
    quality: Optional[str] = None     # e.g., "1080p", "720p", "original", "128kbps"
    ext: str = "mp4"                  # "mp4", "mp3", "jpg", "png", "webp"
    width: Optional[int] = None
    height: Optional[int] = None
    bitrate: Optional[int] = None
    filesize: Optional[int] = None
    has_audio: bool = True


class PlatformAuthor(BaseModel):
    username: Optional[str] = None
    name: Optional[str] = None
    avatar: Optional[str] = None
    url: Optional[str] = None


class PlatformResult(BaseModel):
    success: bool = True
    platform: str                     # "instagram", "pinterest", "tiktok", "twitter", "youtube"
    id: str
    url: str                          # Original source URL
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[PlatformAuthor] = None
    thumbnail: Optional[str] = None
    duration: Optional[float] = None
    duration_string: Optional[str] = None
    media_type: str = "video"         # "video", "image", "carousel", "audio"
    formats: List[MediaFormat] = Field(default_factory=list)
    download_url: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)
    cached: bool = False


class BasePlatformExtractor:
    """Abstract interface that every platform extractor must implement."""
    platform_name: str = "base"

    def match(self, url: str) -> bool:
        raise NotImplementedError

    async def extract(self, url: str) -> Optional[PlatformResult]:
        raise NotImplementedError
