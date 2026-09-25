"""
PO Token Helper — Direct extraction from bgutil server
========================================================
Fetches PO tokens from the bgutil HTTP server for use with yt-dlp.
The server handles visitor_data generation internally.
"""

import os
import json
import time
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# PO Token server URL (configurable via env, default local port 4416)
POT_SERVER_URL = os.getenv("POT_SERVER_URL") or os.getenv("POT_PROVIDER_URL") or "http://127.0.0.1:4416"

# Cache for PO tokens (tokens are valid for ~6-12 hours)
_token_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 3600 * 6  # 6 hours


def _is_server_available() -> bool:
    """Check if PO token server is reachable."""
    try:
        resp = httpx.get(f"{POT_SERVER_URL}/ping", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


def get_po_token_full(client: str = "web", video_id: str = "") -> Optional[Dict[str, Any]]:
    """
    Get a PO token from the bgutil server using content_binding.
    
    Returns:
        Dict with 'po_token' and 'content_binding' keys, or None
    """
    cache_key = f"{client}:{video_id}"

    # Check cache
    if cache_key in _token_cache:
        entry = _token_cache[cache_key]
        if time.time() < entry["expires"]:
            logger.debug(f"Using cached PO token for {client}:{video_id}")
            return {"po_token": entry["token"], "content_binding": entry.get("content_binding", video_id)}

    # Fetch from server
    try:
        payload: Dict[str, Any] = {"client": client}
        if video_id:
            payload["content_binding"] = video_id

        resp = httpx.post(
            f"{POT_SERVER_URL}/get_pot",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

        if resp.status_code == 200:
            data = resp.json()
            token = data.get("poToken") or data.get("po_token")
            cb = data.get("contentBinding") or video_id
            if token:
                _token_cache[cache_key] = {
                    "token": token,
                    "content_binding": cb,
                    "expires": time.time() + _CACHE_TTL,
                }
                logger.info(f"✓ Got PO token for {client}:{video_id} (expires in {_CACHE_TTL}s)")
                return {"po_token": token, "content_binding": cb}
        else:
            logger.warning(f"PO token server returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Failed to get PO token: {e}")

    return None


def get_po_token(client: str = "web", video_id: str = "") -> Optional[str]:
    """Get a PO token (backward compatible)."""
    result = get_po_token_full(client, video_id)
    return result.get("po_token") if result else None


def get_po_token_extractor_args(client: str = "web", video_id: str = "") -> Dict[str, Any]:
    """
    Get extractor args dict with PO token included.
    Pass this to yt-dlp's extractor_args for web/mweb clients.
    """
    result = get_po_token_full(client, video_id)
    if result and result.get("po_token"):
        return {
            "youtube": {
                "player_client": [client],
                "po_token": [f"{client}.gvs+{result['po_token']}"],
            }
        }
    return {}


def invalidate_cache():
    """Clear the PO token cache."""
    _token_cache.clear()
    logger.info("PO token cache cleared")


# Auto-check server availability on import
_server_checked = False
_server_available = False

def check_server() -> bool:
    """Check and cache server availability (re-checks if previously unavailable)."""
    global _server_checked, _server_available
    if not _server_checked or not _server_available:
        _server_available = _is_server_available()
        _server_checked = True
        if _server_available:
            logger.info(f"✓ PO Token server available at {POT_SERVER_URL}")
        else:
            logger.warning(f"⚠ PO Token server not available at {POT_SERVER_URL}")
    return _server_available
