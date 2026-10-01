"""
🏓 Universal Anti-Sleep Keep-Alive Engine
Auto-detects cloud platform domain (Render, Railway, Koyeb, Heroku, etc.)
and executes periodic background self-pings to keep free-tier instances awake 24/7.
"""

import os
import asyncio
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

PING_INTERVAL = 14 * 60  # 14 minutes (Render sleeps after 15 min)

def get_public_url() -> Optional[str]:
    """Auto-detect public URL from host platform environment variables."""
    custom_url = os.getenv("APP_URL") or os.getenv("SERVER_URL")
    if custom_url:
        return custom_url.rstrip("/")

    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        return render_url.rstrip("/")

    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway_domain:
        return f"https://{railway_domain}".rstrip("/")

    koyeb_domain = os.getenv("KOYEB_PUBLIC_DOMAIN")
    if koyeb_domain:
        return f"https://{koyeb_domain}".rstrip("/")

    heroku_name = os.getenv("HEROKU_APP_NAME")
    if heroku_name:
        return f"https://{heroku_name}.herokuapp.com"

    return None

async def start_keep_alive_task():
    """Background task running self-ping loop every 14 minutes."""
    url = get_public_url()
    if not url:
        logger.info("ℹ Keep-alive: No public URL detected (set APP_URL if needed) — running local fallback.")
        return

    ping_endpoint = f"{url}/health"
    logger.info(f"🏓 Keep-alive active -> Ping target: {ping_endpoint} (every 14 min)")

    # Initial wait (allow server startup to complete)
    await asyncio.sleep(60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                resp = await client.get(ping_endpoint)
                if resp.status_code == 200:
                    logger.info(f"🏓 Self-ping OK -> {ping_endpoint} [200 OK]")
                else:
                    logger.warning(f"⚠ Self-ping returned HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"⚠ Self-ping exception: {e}")

            await asyncio.sleep(PING_INTERVAL)
