"""
🎵 Pre-Indexed Songs Catalog Module
Fast in-memory token-matched song search & lookup for 5,700+ indexed songs.
Provides instant 0-1ms search fallback and cached stream URL retrieval.
"""

import os
import json
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "songs.json")

class SongCatalog:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SongCatalog, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.songs: List[Dict[str, Any]] = []
        self.by_id: Dict[str, Dict[str, Any]] = {}
        self._initialized = True
        self.load_catalog()

    def load_catalog(self):
        """Load songs.json into RAM and build fast ID index."""
        if not os.path.exists(DATA_PATH):
            logger.warning(f"⚠ Catalog data file not found at {DATA_PATH}")
            return
        
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                raw_songs = json.load(f)
            
            for item in raw_songs:
                vid_id = item.get("video_id")
                title = item.get("title", "")
                if not vid_id or not title:
                    continue
                
                raw_stream = item.get("stream_url", "")
                if not raw_stream or "catbox" in raw_stream or "yuki" in raw_stream:
                    stream_url = f"/api/musicbot/stream/{vid_id}"
                else:
                    stream_url = raw_stream

                song_obj = {
                    "id": vid_id,
                    "title": title,
                    "duration": item.get("duration", 210),
                    "duration_string": item.get("duration_string", "3:30"),
                    "thumbnail": item.get("thumbnail") or f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
                    "channel": item.get("artist") or "EchoAPI Music",
                    "url": f"https://youtu.be/{vid_id}",
                    "stream_url": stream_url,
                    "source": "EchoAPI"
                }
                self.songs.append(song_obj)
                self.by_id[vid_id] = song_obj

            logger.info(f"✓ SongCatalog loaded {len(self.songs)} pre-indexed songs into memory")
        except Exception as e:
            logger.error(f"Failed to load song catalog: {e}")

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Smart multi-keyword token matching with relevance scoring.
        Returns top matching tracks from 5,700+ indexed catalog.
        """
        if not query or not query.strip() or not self.songs:
            return []

        tokens = [t.lower() for t in re.split(r'\s+', query.strip()) if len(t) > 1]
        if not tokens:
            return []

        scored_results = []
        for song in self.songs:
            title_lower = song["title"].lower()
            score = 0
            matches = 0
            for token in tokens:
                if token in title_lower:
                    matches += 1
                    # Bonus for exact word match
                    if re.search(r'\b' + re.escape(token) + r'\b', title_lower):
                        score += 3
                    else:
                        score += 1

            if matches == len(tokens):
                # Bonus if all tokens match
                score += 10

            if score > 0:
                scored_results.append((score, song))

        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored_results[:limit]]

    def get_by_id(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Get pre-indexed song details and cached stream URL by 11-char video ID."""
        return self.by_id.get(video_id)

catalog = SongCatalog()
