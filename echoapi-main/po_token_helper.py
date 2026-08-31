"""
PO Token Helper — Direct extraction from bgutil server
========================================================
Fetches PO tokens from the bgutil HTTP server for use with yt-dlp.
The server handles visitor_data generation internally.
"""

import json
import time
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# PO Token server URL
POT_SERVER_URL = "http://127.0.0.1:4416"

# Cache for PO tokens (tokens are valid for ~6 hours)
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
    Get a PO token from the bgutil server.
    
    Returns:
        Dict with 'po_token' and 'visitor_data' keys, or None
    """
    cache_key = f"{client}:{video_id}"

    # Check cache
    if cache_key in _token_cache:
        entry = _token_cache[cache_key]
        if time.time() < entry["expires"]:
            logger.debug(f"Using cached PO token for {client}:{video_id}")
            return {"po_token": entry["token"], "visitor_data": entry.get("visitor_data", "")}

    # Fetch from server
    try:
        payload = {
            "client": client,
            "visitor_data": "",
            "data_sync_id": "",
        }

        resp = httpx.post(
            f"{POT_SERVER_URL}/get_pot",
            json=payload,
            timeout=30.0,
        )

        if resp.status_code == 200:
            data = resp.json()
            token = data.get("poToken")
            if token:
                _token_cache[cache_key] = {
                    "token": token,
                    "visitor_data": "",
                    "expires": time.time() + _CACHE_TTL,
                }
                logger.info(f"✓ Got PO token for {client} (expires in {_CACHE_TTL}s)")
                return {"po_token": token, "visitor_data": ""}
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
    Pass this to yt-dlp's extractor_args for mweb/web clients.
    """
    result = get_po_token_full(client, video_id)
    if result and result.get("po_token"):
        return {
            "youtube": {
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
    """Check and cache server availability."""
    global _server_checked, _server_available
    if not _server_checked:
        _server_available = _is_server_available()
        _server_checked = True
        if _server_available:
            logger.info(f"✓ PO Token server available at {POT_SERVER_URL}")
        else:
            logger.warning(f"⚠ PO Token server not available at {POT_SERVER_URL}")
    return _server_available
