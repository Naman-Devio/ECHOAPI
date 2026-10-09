"""
🌊 Universal Streaming Reverse-Proxy Pipe
Pipes raw media streams from TikTok, Instagram, Pinterest, Twitter, and CDNs
directly through EchoAPI to bypass CORS, expiring hotlinks, and player 403 Forbidden errors.
Full support for HTTP Range requests (206 Partial Content) and HEAD requests.
"""
import logging
from typing import Optional
import httpx
from fastapi import Request, HTTPException, Response
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


import urllib.parse

async def stream_media_pipe(url: str, request: Request):
    """
    Reverse proxy media stream to client.
    Supports Range header seeking (0-1048576) and HEAD method.
    """
    # Reconstruct upstream URL if unencoded query params were split by ASGI router
    if request:
        raw_query = str(request.url.query)
        if "url=" in raw_query:
            raw_target = raw_query.split("url=", 1)[1]
            if raw_target.startswith("http%3A") or raw_target.startswith("https%3A"):
                raw_target = urllib.parse.unquote(raw_target)
            if len(raw_target) > len(url) and raw_target.startswith("http"):
                url = raw_target

    if not url or not str(url).startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid media URL provided")

    range_header = request.headers.get("range")
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://www.google.com/",
        "Accept": "*/*",
    }
    if range_header:
        req_headers["Range"] = range_header

    client = httpx.AsyncClient(timeout=45.0, follow_redirects=True)
    try:
        upstream = await client.send(
            client.build_request("GET", url, headers=req_headers),
            stream=True
        )
    except Exception as e:
        await client.aclose()
        logger.error(f"Upstream stream connect failed for {url[:100]}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to connect to upstream stream: {e}")

    content_type = upstream.headers.get("content-type", "video/mp4")
    # Discard HTML error pages if upstream returned an error
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=upstream.status_code, detail=f"Upstream stream returned HTTP {upstream.status_code}")

    res_headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Range, Content-Type",
    }
    if "content-length" in upstream.headers:
        res_headers["Content-Length"] = upstream.headers["content-length"]
    if "content-range" in upstream.headers:
        res_headers["Content-Range"] = upstream.headers["content-range"]

    # Handle HEAD preflight check
    if request.method == "HEAD":
        await upstream.aclose()
        await client.aclose()
        return Response(status_code=upstream.status_code, headers=res_headers)

    async def media_stream_generator():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        media_stream_generator(),
        status_code=upstream.status_code,
        headers=res_headers
    )
