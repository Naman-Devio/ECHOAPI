import os
import json
import hashlib
import asyncio
import time
import psutil
from typing import Optional
from functools import wraps
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables from .env file (override system env vars)
# .env file always takes precedence over system environment variables
load_dotenv(override=True)

# ─── Add Deno to PATH for yt-dlp JavaScript runtime ──────────────────────────
# This is required for yt-dlp to use Deno for signature decryption
for deno_path in ["/usr/local/bin", os.path.expanduser("~/.deno/bin")]:
    if os.path.exists(os.path.join(deno_path, "deno")) and deno_path not in os.environ["PATH"]:
        os.environ["PATH"] += os.pathsep + deno_path
        break

import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from inntertube import (
    extract_video_id, get_video_info_fast, parse_video_info,
    search_youtube_fast, get_stream_urls_fast, close_http_client,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
import uvicorn
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log
)
import logging

# Import proxy manager
from proxy_manager import ProxyManager
from proxy_checker import ProxyChecker

# Import API authentication and music bot endpoints
from auth import api_key_manager, verify_api_key, verify_api_key_optional
from musicbot_api import musicbot_router
from admin_api import admin_router

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ─── Proxy Manager Setup ──────────────────────────────────────────────────────
# Proxy priority: WARP (free, trusted) > WebShare/ProxyScrap > Direct
USE_WARP = os.getenv("USE_WARP", "false").lower() == "true"
WARP_PROXY = os.getenv("WARP_PROXY", "socks5://127.0.0.1:40000")  # Cloudflare WARP
USE_PROXIES = os.getenv("USE_PROXIES", "false").lower() == "true"  # WebShare/ProxyScrap
PROXY_TYPE = os.getenv("PROXY_TYPE", "any")  # any, http, socks4, socks5
ENABLE_PROXY_CHECKER = os.getenv("ENABLE_PROXY_CHECKER", "true").lower() == "true"

proxy_checker = None

# Auto-detect WARP if available (verify port is actually listening)
if USE_WARP:
    import socket as _socket
    try:
        _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        _s.settimeout(2.0)
        _s.connect(("127.0.0.1", 40000))
        _s.close()
        logger.info("✓ Cloudflare WARP verified on localhost:40000")
    except (ConnectionRefusedError, _socket.timeout, OSError):
        logger.warning("⚠ WARP port 40000 not reachable, disabling WARP")
        USE_WARP = False
        WARP_PROXY = ""

if not USE_WARP:
    import socket as _socket
    try:
        _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        _s.settimeout(2.0)
        _s.connect(("127.0.0.1", 40000))
        _s.close()
        USE_WARP = True
        WARP_PROXY = "socks5://127.0.0.1:40000"
        logger.info("✓ Cloudflare WARP auto-detected on localhost:40000")
    except (ConnectionRefusedError, _socket.timeout, OSError):
        pass

if USE_WARP:
    logger.info(f"✓ Cloudflare WARP proxy: {WARP_PROXY}")
    logger.info(f"  → YouTube will see a trusted Cloudflare IP")

if USE_PROXIES:
    try:
        proxy_manager = ProxyManager()
        logger.info(f"✓ Proxy manager initialized: {proxy_manager.get_stats()}")
        
        # Initialize proxy checker if enabled
        if ENABLE_PROXY_CHECKER:
            proxy_checker = ProxyChecker()
            logger.info("✓ Proxy checker initialized (will run in background)")
    except Exception as e:
        logger.warning(f"Proxy manager failed to initialize: {e}. Running without proxies.")
        USE_PROXIES = False
        proxy_manager = None
else:
    proxy_manager = None
    if not USE_WARP:
        logger.info("Running WITHOUT proxies (USE_WARP=false, USE_PROXIES=false)")
    else:
        logger.info("Running with WARP only (USE_PROXIES=false)")

# ─── Optional Redis (graceful fallback to in-memory) ──────────────────────────
try:
    import redis.asyncio as aioredis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    _redis_client = None
    REDIS_ENABLED = True
except ImportError:
    REDIS_ENABLED = False

# ─── In-memory fallback cache ─────────────────────────────────────────────────
_mem_cache: dict = {}
_mem_cache_lock = asyncio.Lock()
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour default
MAX_MEM_CACHE_SIZE = int(os.getenv("MAX_MEM_CACHE_SIZE", "1000"))  # Prevent memory bloat

# ─── App Setup ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="YT Download API",
    description="High-performance YouTube audio/video extraction API with Music Bot support",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Include routers
app.include_router(musicbot_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

# Add compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ─── Rate Limiting (simple in-memory) ────────────────────────────────────────
_rate_store: dict = {}
_rate_lock = asyncio.Lock()
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "60"))  # requests per minute per IP
RATE_WINDOW = 60  # seconds

async def rate_limit(request: Request):
    ip = request.client.host
    now = time.time()
    window_start = now - RATE_WINDOW
    
    async with _rate_lock:
        hits = _rate_store.get(ip, [])
        # Clean old entries
        hits = [t for t in hits if t > window_start]
        
        if len(hits) >= RATE_LIMIT:
            raise HTTPException(
                status_code=429, 
                detail=f"Rate limit exceeded. Max {RATE_LIMIT} req/min.",
                headers={"Retry-After": "60"}
            )
        
        hits.append(now)
        _rate_store[ip] = hits
        
        # Periodic cleanup of rate store
        if len(_rate_store) > 10000:  # Prevent memory bloat
            _rate_store.clear()

# ─── Cache Helpers ────────────────────────────────────────────────────────────
async def get_redis():
    global _redis_client
    if REDIS_ENABLED and _redis_client is None:
        try:
            import socket
            # Quick check if Redis port is reachable before trying to connect
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)  # 500ms timeout
            try:
                s.connect(('localhost', 6379))
                s.close()
                _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
            except (socket.timeout, ConnectionRefusedError, OSError):
                s.close()
                logger.warning("Redis not reachable, using in-memory cache")
                return None
        except Exception:
            pass
    return _redis_client

async def cache_get(key: str):
    redis = await get_redis()
    if redis:
        try:
            val = await redis.get(key)
            return json.loads(val) if val else None
        except Exception:
            pass
    # fallback to memory
    async with _mem_cache_lock:
        entry = _mem_cache.get(key)
        if entry and time.time() < entry["expires"]:
            return entry["data"]
        # Clean expired entries
        if len(_mem_cache) > MAX_MEM_CACHE_SIZE:
            now = time.time()
            expired = [k for k, v in _mem_cache.items() if now >= v["expires"]]
            for k in expired[:len(expired)//2]:  # Remove half of expired
                _mem_cache.pop(k, None)
    return None

async def cache_set(key: str, data: dict, ttl: int = CACHE_TTL):
    redis = await get_redis()
    if redis:
        try:
            await redis.setex(key, ttl, json.dumps(data))
            return
        except Exception:
            pass
    async with _mem_cache_lock:
        _mem_cache[key] = {"data": data, "expires": time.time() + ttl}

def make_cache_key(*args) -> str:
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()

# ─── yt-dlp Core Extractor with Retry Logic ───────────────────────────────────

# Try to auto-extract cookies from browser
def get_cookies_file():
    """Try to get cookies from browser or use existing cookies.txt"""
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    
    # If cookies.txt exists, use it
    if os.path.exists(cookies_path):
        logger.info(f"Using existing cookies file: {cookies_path}")
        return cookies_path
    
    # Try to extract from browser
    try:
        import browser_cookie3
        
        # Try Chrome first
        try:
            cookies = browser_cookie3.chrome(domain_name='youtube.com')
            if cookies:
                logger.info("Extracted cookies from Chrome browser")
                # Save to file for reuse
                with open(cookies_path, 'w') as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    for cookie in cookies:
                        f.write(f"{cookie.domain}\tTRUE\t{cookie.path}\t{'TRUE' if cookie.secure else 'FALSE'}\t{cookie.expires or 0}\t{cookie.name}\t{cookie.value}\n")
                return cookies_path
        except:
            pass
        
        # Try Firefox
        try:
            cookies = browser_cookie3.firefox(domain_name='youtube.com')
            if cookies:
                logger.info("Extracted cookies from Firefox browser")
                with open(cookies_path, 'w') as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    for cookie in cookies:
                        f.write(f"{cookie.domain}\tTRUE\t{cookie.path}\t{'TRUE' if cookie.secure else 'FALSE'}\t{cookie.expires or 0}\t{cookie.name}\t{cookie.value}\n")
                return cookies_path
        except:
            pass
            
    except ImportError:
        logger.warning("browser_cookie3 not installed, cannot auto-extract cookies")
    except Exception as e:
        logger.warning(f"Could not extract browser cookies: {e}")
    
    return None

# Get cookies file
COOKIES_FILE = os.getenv("COOKIES_FILE", None) or get_cookies_file()

YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "skip_download": True,
    "socket_timeout": 30,  # Increased from 15 for proxy connections
    "nocheckcertificate": True,  # Bypass SSL verification (fixes _ssl.c:1006 with proxies)
    "prefer_insecure": False,
    "no_check_certificate": True,  # Also set this for completeness

    # Performance optimizations
    "concurrent_fragment_downloads": 3,  # Reduced to avoid proxy overload
    "http_chunk_size": 1048576,  # 1MB chunks (better for proxies than 10MB)
    "retries": 5,  # Increased from 3 for better reliability
    "fragment_retries": 5,
    "extractor_retries": 5,  # Added for extractor-level retries

    # Rate limiting to avoid bot detection
    "sleep_requests": 1,  # Sleep 1s between requests
    "sleep_interval": 2,  # Sleep 2s between downloads
    "max_sleep_interval": 8,  # Max random sleep up to 8s

    # Advanced YouTube bypass features
    "geo_bypass": True,  # Bypass geographic restrictions

    # YouTube player client config
    # With PO tokens: use 'web' or 'mweb' for adaptive formats (audio-only, video-only)
    # Without PO tokens: 'tv_embedded' only returns combined itag=18
    "extractor_args": {
        "youtube": {
            # Do NOT use player_skip - it prevents full format listing
        }
    },

    # PO Token provider config (set via env var or auto-detected)
    # If POT_PROVIDER_URL is set, use web/mweb client for adaptive formats
    # Otherwise fallback to tv_embedded (combined format only)


    # Ignore config errors
    "ignoreerrors": False,
    "no_color": True,
}

# Add cookies if available
if COOKIES_FILE:
    YDL_BASE_OPTS["cookiefile"] = COOKIES_FILE
    logger.info(f"✓ Using cookies file for YouTube authentication")
else:
    logger.warning("⚠ No cookies available - relying on tv_embedded client")

# ─── PO Token Provider Setup ─────────────────────────────────────────────────
# PO tokens are required for adaptive formats (audio-only, video-only streams)
# Without PO tokens: only itag=18 (360p combined video+audio)
# With PO tokens: all adaptive formats available
POT_PROVIDER_URL = os.getenv("POT_PROVIDER_URL", "http://127.0.0.1:4416")

# Check if PO token provider is reachable (with retries for startup timing)
def _check_pot_provider(max_retries: int = 5, delay: float = 2.0) -> bool:
    """Check if PO token provider is running and reachable.
    
    Retries with delay because the POT server may start after main.py.
    """
    import socket
    import time
    from urllib.parse import urlparse
    parsed = urlparse(POT_PROVIDER_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4416
    
    for attempt in range(max_retries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((host, port))
            s.close()
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            if attempt < max_retries - 1:
                logger.info(f"  PO Token server not ready, retrying in {delay}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(delay)
            continue
    return False

POT_AVAILABLE = _check_pot_provider()

if POT_AVAILABLE:
    logger.info(f"✓ PO Token provider available at {POT_PROVIDER_URL}")
    # Use web + mweb clients (need PO tokens but return adaptive formats)
    YDL_BASE_OPTS["extractor_args"]["youtube"]["player_client"] = ["web", "mweb"]
    # Add PO token provider URL if non-default
    if POT_PROVIDER_URL != "http://127.0.0.1:4416":
        YDL_BASE_OPTS["extractor_args"]["youtubepot-bgutilhttp"] = {
            "base_url": POT_PROVIDER_URL
        }
    logger.info(f"✓ YouTube player clients: web, mweb (adaptive formats enabled)")
else:
    logger.warning(f"⚠ PO Token provider not reachable at {POT_PROVIDER_URL}")
    logger.warning(f"  Only combined formats available (itag=18). Start PO token provider:")
    logger.warning(f"  docker run -d -p 4416:4416 brainicism/bgutil-ytdlp-pot-provider")
    # Fallback to tv_embedded (no PO token needed, but only combined format)
    YDL_BASE_OPTS["extractor_args"]["youtube"]["player_client"] = ["tv_embedded", "ios", "android"]

# Circuit breaker state
_circuit_breaker = {
    "failures": 0,
    "last_failure_time": 0,
    "state": "closed",  # closed, open, half_open
    "failure_threshold": 10,  # Increased from 5 to 10
    "recovery_timeout": 30,   # Reduced from 60 to 30 seconds
}

# SSL error tracking
_ssl_failures = 0
_max_ssl_failures = 5  # Switch to direct after 5 SSL failures

# Current proxy tracking
_current_proxy = None
_proxy_failures = 0
_max_proxy_failures = 3  # Switch proxy after 3 failures

def get_proxy_for_request():
    """Get proxy for yt-dlp request with automatic rotation.
    
    Priority chain:
      1. Cloudflare WARP (free, trusted IPs, best for YouTube)
      2. WebShare/ProxyScrap proxies (if configured)
      3. Direct connection (no proxy)
    """
    global _current_proxy, _proxy_failures
    
    # ── Priority 1: Cloudflare WARP ──
    if USE_WARP:
        return WARP_PROXY
    
    # ── Priority 2: WebShare/ProxyScrap proxies ──
    if USE_PROXIES and proxy_manager:
        # Switch proxy if current one failed too many times
        if _current_proxy and _proxy_failures >= _max_proxy_failures:
            logger.warning(f"Proxy {_current_proxy} failed {_proxy_failures} times, switching...")
            proxy_manager.mark_failed(_current_proxy)
            _current_proxy = None
            _proxy_failures = 0
        
        # Get new proxy if needed
        if not _current_proxy:
            _current_proxy = proxy_manager.get_random_proxy(PROXY_TYPE)
            _proxy_failures = 0
            if _current_proxy:
                logger.info(f"Using proxy: {_current_proxy}")
        
        return _current_proxy
    
    # ── Priority 3: Direct connection ──
    return None

def check_circuit_breaker():
    """Check if circuit breaker allows requests"""
    now = time.time()
    
    if _circuit_breaker["state"] == "open":
        if now - _circuit_breaker["last_failure_time"] > _circuit_breaker["recovery_timeout"]:
            _circuit_breaker["state"] = "half_open"
            logger.info("Circuit breaker entering half-open state")
        else:
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable. YouTube extraction circuit breaker is open."
            )
    
def record_success():
    """Record successful request"""
    global _proxy_failures
    
    _circuit_breaker["failures"] = 0
    if _circuit_breaker["state"] == "half_open":
        _circuit_breaker["state"] = "closed"
        logger.info("Circuit breaker closed - service recovered")
    
    # Mark proxy as successful
    if _current_proxy and proxy_manager:
        proxy_manager.mark_success(_current_proxy)
        _proxy_failures = 0

def record_failure():
    """Record failed request"""
    global _proxy_failures
    
    _circuit_breaker["failures"] += 1
    _circuit_breaker["last_failure_time"] = time.time()
    
    if _circuit_breaker["failures"] >= _circuit_breaker["failure_threshold"]:
        _circuit_breaker["state"] = "open"
        logger.error(f"Circuit breaker opened after {_circuit_breaker['failures']} failures")
    
    # Track proxy failures
    if _current_proxy:
        _proxy_failures += 1

def _is_ssl_error(e: Exception) -> bool:
    """Check if an exception is an SSL-related error"""
    err_str = str(e).lower()
    ssl_indicators = [
        'ssl', '_ssl.c', 'ssLError', 'certificate', 'cert_verify',
        'sslcertverification', 'sslcertverif', 'sslerror',
        'ssl: unknown error', 'ssl.c:1006', 'ssl.c:1032',
        'wraps_socket', 'do_handshake',
    ]
    return any(ind in err_str for ind in ssl_indicators)

@retry(
    stop=stop_after_attempt(5),  # Increased from 3 to 5
    wait=wait_exponential(multiplier=1, min=2, max=15),  # Increased max wait
    retry=retry_if_exception_type((yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def _run_ytdlp(url: str, extra_opts: dict = {}) -> dict:
    """Run yt-dlp with retry logic, proxy rotation, PO tokens, and direct fallback"""
    global _ssl_failures
    check_circuit_breaker()
    
    # Try to get PO token for adaptive formats
    from po_token_helper import check_server as pot_check, get_po_token_extractor_args
    pot_available = pot_check()
    
    proxy = None
    try:
        # Get proxy for this request
        proxy = get_proxy_for_request()
        
        # Build options with proxy
        opts = {**YDL_BASE_OPTS, **extra_opts}
        if proxy:
            opts["proxy"] = proxy
            logger.debug(f"Using proxy: {proxy}")
        
        # Add PO token + use mweb client (recommended by yt-dlp wiki)
        if pot_available:
            from inntertube import extract_video_id
            vid = extract_video_id(url)
            if vid:
                # mweb + PO token = adaptive formats (audio-only, video-only)
                # Do NOT skip webpage - it's needed for full format listing
                pot_args = get_po_token_extractor_args("mweb", vid)
                if pot_args:
                    if "extractor_args" not in opts:
                        opts["extractor_args"] = {}
                    opts["extractor_args"]["youtube"] = {
                        "player_client": ["mweb"],
                        "po_token": pot_args["youtube"]["po_token"],
                    }
                    logger.info(f"Added mweb + PO token for video {vid}")
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            result = ydl.sanitize_info(info)
        
        record_success()
        _ssl_failures = 0  # Reset SSL failure counter on success
        return result
    except Exception as e:
        record_failure()
        err_str = str(e)
        
        # Track SSL failures specifically
        if _is_ssl_error(e):
            _ssl_failures += 1
            logger.warning(f"SSL error #{_ssl_failures}: {err_str[:200]}")
            
            # If too many SSL failures, force direct connection
            if _ssl_failures >= _max_ssl_failures:
                logger.error(f"Too many SSL failures ({_ssl_failures}), forcing direct connection")
                proxy = None  # Force direct
        
        # If proxy failed, try direct connection as fallback
        if proxy and ("proxy" in err_str.lower() or "407" in err_str or 
                      "tunnel" in err_str.lower() or "connect" in err_str.lower() or
                      _is_ssl_error(e)):
            logger.warning(f"Proxy failed ({err_str[:100]}), trying direct connection...")
            try:
                opts_direct = {**YDL_BASE_OPTS, **extra_opts}
                opts_direct.pop("proxy", None)
                with yt_dlp.YoutubeDL(opts_direct) as ydl:
                    info = ydl.extract_info(url, download=False)
                    result = ydl.sanitize_info(info)
                record_success()
                logger.info("✓ Direct connection succeeded as fallback")
                return result
            except Exception as e2:
                logger.warning(f"Direct fallback also failed: {e2}")
                raise e2
        raise

async def extract_info(url: str, extra_opts: dict = {}) -> dict:
    """Extract info with timeout protection and SSL error handling"""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _run_ytdlp, url, extra_opts),
            timeout=90.0  # 90 second timeout (increased for proxy+SSL retries)
        )
    except asyncio.TimeoutError:
        record_failure()
        raise HTTPException(status_code=504, detail="YouTube extraction timeout")
    except yt_dlp.utils.DownloadError as e:
        err_str = str(e)
        if _is_ssl_error(e):
            logger.error(f"SSL extraction error: {err_str[:200]}")
            raise HTTPException(
                status_code=502,
                detail=f"SSL connection error. Retrying may help. Error: {err_str[:200]}"
            )
        raise HTTPException(status_code=400, detail=f"Could not extract info: {str(e)}")
    except Exception as e:
        logger.error(f"Extraction error: {str(e)}")
        if _is_ssl_error(e):
            raise HTTPException(status_code=502, detail="SSL connection error. Please try again.")
        raise HTTPException(status_code=500, detail="Internal extraction error")

@retry(
    stop=stop_after_attempt(5),  # Increased from 3 to 5
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def _search_ytdlp(query: str, max_results: int) -> list:
    """Search with retry logic and proxy rotation"""
    check_circuit_breaker()
    
    try:
        # Get proxy for this request
        proxy = get_proxy_for_request()
        
        # Search-specific opts (remove sleep intervals for faster search)
        search_opts = {
            k: v for k, v in YDL_BASE_OPTS.items()
            if k not in ('sleep_requests', 'sleep_interval', 'max_sleep_interval')
        }
        search_opts.update({
            "extract_flat": True,
            "playlistend": max_results,
        })
        
        if proxy:
            search_opts["proxy"] = proxy
        
        search_url = f"ytsearch{max_results}:{query}"
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            results = ydl.extract_info(search_url, download=False)
            entries = results.get("entries", [])
        
        record_success()
        return entries
    except Exception as e:
        record_failure()
        # Try direct connection if proxy/SSL/connection error
        err_str = str(e).lower()
        if proxy and ("proxy" in err_str or "tunnel" in err_str or "connect" in err_str or
                      "503" in err_str or _is_ssl_error(e)):
            logger.warning(f"Search proxy error, trying direct...")
            try:
                opts_direct = {
                    k: v for k, v in YDL_BASE_OPTS.items()
                    if k not in ('sleep_requests', 'sleep_interval', 'max_sleep_interval')
                }
                opts_direct.update({
                    "extract_flat": True,
                    "playlistend": max_results,
                })
                opts_direct.pop("proxy", None)
                with yt_dlp.YoutubeDL(opts_direct) as ydl:
                    results = ydl.extract_info(search_url, download=False)
                    entries = results.get("entries", [])
                record_success()
                return entries
            except Exception:
                pass
        raise

async def search_yt(query: str, max_results: int = 5) -> list:
    """Search with timeout protection"""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _search_ytdlp, query, max_results),
            timeout=20.0  # 20 second timeout
        )
    except asyncio.TimeoutError:
        record_failure()
        raise HTTPException(status_code=504, detail="YouTube search timeout")

def pick_best_audio_url(info: dict, quality: str = "best") -> dict:
    """Pick best audio-only format and return its URL + meta.
    
    Returns dict with 'is_audio_only' flag to distinguish from combined streams.
    """
    formats = info.get("formats", [])
    
    # Step 1: Pure audio-only formats (vcodec=none, acodec present)
    audio_formats = [
        f for f in formats
        if f.get("vcodec") in ("none", None, "") and f.get("acodec") not in ("none", None, "")
        and f.get("url")
    ]
    
    if audio_formats:
        audio_formats.sort(key=lambda f: f.get("abr") or 0, reverse=(quality == "best"))
        chosen = audio_formats[0]
        return {
            "url": chosen["url"],
            "ext": chosen.get("ext", "webm"),
            "abr": chosen.get("abr"),
            "filesize": chosen.get("filesize"),
            "is_audio_only": True,
        }
    
    # Step 2: Fallback to main URL (combined video+audio)
    url = info.get("url") or (formats[-1]["url"] if formats else None)
    return {
        "url": url,
        "ext": info.get("ext", "mp4"),
        "abr": None,
        "filesize": None,
        "is_audio_only": False,
    }

def pick_best_video_url(info: dict, resolution: str = "best") -> dict:
    """Pick best video format at target resolution."""
    formats = info.get("formats", [])
    # Formats with both video and audio
    combined = [
        f for f in formats
        if f.get("vcodec") != "none" and f.get("acodec") != "none"
        and f.get("url")
    ]
    if not combined:
        combined = [f for f in formats if f.get("vcodec") != "none" and f.get("url")]

    if not combined:
        return {"url": info.get("url"), "ext": "mp4", "height": None}

    if resolution == "best":
        combined.sort(key=lambda f: f.get("height") or 0, reverse=True)
    elif resolution == "worst":
        combined.sort(key=lambda f: f.get("height") or 0)
    else:
        target = int(resolution.replace("p", ""))
        exact = [f for f in combined if f.get("height") == target]
        if exact:
            combined = exact
        else:
            combined.sort(key=lambda f: abs((f.get("height") or 0) - target))

    chosen = combined[0]
    return {
        "url": chosen["url"],
        "ext": chosen.get("ext", "mp4"),
        "height": chosen.get("height"),
        "width": chosen.get("width"),
        "fps": chosen.get("fps"),
        "filesize": chosen.get("filesize"),
    }

def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def build_video_info(info: dict) -> dict:
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "channel_url": info.get("channel_url"),
        "duration": info.get("duration"),
        "duration_string": format_duration(info.get("duration")),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "thumbnail": info.get("thumbnail"),
        "thumbnails": [
            {"url": t["url"], "width": t.get("width"), "height": t.get("height")}
            for t in info.get("thumbnails", [])[-3:]
        ],
        "description": (info.get("description") or "")[:500],
        "tags": (info.get("tags") or [])[:10],
        "upload_date": info.get("upload_date"),
        "webpage_url": info.get("webpage_url"),
        "available_formats": list({
            f"{f.get('height', '')}p" if f.get('height') else f.get('ext', '')
            for f in info.get("formats", [])
            if f.get("height") or f.get("ext")
        }),
    }

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "running",
        "api": "YT Download API v1.0",
        "endpoints": ["/api/info", "/api/audio", "/api/video", "/api/search", "/api/formats"],
        "docs": "/docs",
    }

@app.get("/health", tags=["Health"])
async def health():
    """Basic health check - for load balancers"""
    return {"status": "ok"}

@app.get("/health/live", tags=["Health"])
async def liveness():
    """Kubernetes liveness probe - is the app running?"""
    return {
        "status": "alive",
        "timestamp": time.time(),
    }

@app.get("/health/ready", tags=["Health"])
async def readiness():
    """Kubernetes readiness probe - can the app handle traffic?"""
    redis_ready = False
    circuit_breaker_ok = _circuit_breaker["state"] != "open"
    
    # Check Redis
    if REDIS_ENABLED:
        redis = await get_redis()
        if redis:
            try:
                await asyncio.wait_for(redis.ping(), timeout=2.0)
                redis_ready = True
            except:
                redis_ready = False
        else:
            redis_ready = False
    else:
        redis_ready = True  # Not required
    
    # Check system resources
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    memory_ok = memory.percent < 90
    cpu_ok = cpu_percent < 95
    
    is_ready = circuit_breaker_ok and memory_ok and cpu_ok
    
    status_code = 200 if is_ready else 503
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if is_ready else "not_ready",
            "timestamp": time.time(),
            "checks": {
                "redis": "ok" if redis_ready else "degraded",
                "circuit_breaker": "ok" if circuit_breaker_ok else "open",
                "memory": f"{memory.percent:.1f}%",
                "cpu": f"{cpu_percent:.1f}%",
                "memory_ok": memory_ok,
                "cpu_ok": cpu_ok,
            }
        }
    )

@app.get("/metrics", tags=["Health"])
async def metrics():
    """Detailed metrics endpoint for monitoring"""
    redis_status = "connected"
    if REDIS_ENABLED:
        redis = await get_redis()
        if redis:
            try:
                await redis.ping()
            except:
                redis_status = "error"
        else:
            redis_status = "disconnected"
    else:
        redis_status = "disabled"
    
    memory = psutil.virtual_memory()
    
    metrics_data = {
        "redis_status": redis_status,
        "memory_cache_entries": len(_mem_cache),
        "rate_limit_tracked_ips": len(_rate_store),
        "rate_limit_per_minute": RATE_LIMIT,
        "cache_ttl_seconds": CACHE_TTL,
        "max_cache_size": MAX_MEM_CACHE_SIZE,
        "circuit_breaker": {
            "state": _circuit_breaker["state"],
            "failures": _circuit_breaker["failures"],
            "threshold": _circuit_breaker["failure_threshold"],
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": memory.percent,
            "memory_available_mb": memory.available / (1024 * 1024),
        }
    }
    
    # Add proxy stats if enabled
    if USE_PROXIES and proxy_manager:
        metrics_data["proxies"] = proxy_manager.get_stats()
        metrics_data["proxies"]["current_proxy"] = _current_proxy
        metrics_data["proxies"]["proxy_failures"] = _proxy_failures
    
    return metrics_data


# ── /api/info ─────────────────────────────────────────────────────────────────
@app.get("/api/info", tags=["Info"])
async def get_info(
    url: str = Query(..., description="YouTube video URL"),
    _: None = Depends(rate_limit),
):
    """
    Get full metadata for a YouTube video.
    Fast path: InnerTube API (<500ms)
    Fallback: yt-dlp (slower but more reliable)
    """
    cache_key = make_cache_key("info", url)
    cached = await cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    # Fast path: Direct InnerTube API call (~300ms)
    t0 = time.time()
    try:
        raw = await get_video_info_fast(video_id, client="tv_embedded")
        if raw:
            result = parse_video_info(raw, video_id)
            elapsed = time.time() - t0
            result["cached"] = False
            result["method"] = "innertube"
            result["response_ms"] = int(elapsed * 1000)
            await cache_set(cache_key, result, ttl=1800)
            logger.info(f"✓ InnerTube info for {video_id} in {elapsed:.2f}s")
            return result
    except Exception as e:
        logger.warning(f"InnerTube failed for {video_id}: {e}, falling back to yt-dlp")

    # Fallback: yt-dlp (slower)
    try:
        info = await extract_info(url)
        result = build_video_info(info)
        result["method"] = "yt-dlp"
        await cache_set(cache_key, result)
        return {**result, "cached": False}
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Could not extract info: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── /api/audio ────────────────────────────────────────────────────────────────
@app.get("/api/audio", tags=["Download"])
async def get_audio(
    url: str = Query(..., description="YouTube video URL"),
    quality: str = Query("best", description="best | worst"),
    redirect: bool = Query(False, description="Redirect to stream URL instead of JSON"),
    _: None = Depends(rate_limit),
):
    """
    Get direct audio stream URL. Sub-second response with caching.
    Set redirect=true to go straight to the audio stream.
    """
    cache_key = make_cache_key("audio", url, quality)
    cached = await cache_get(cache_key)

    if not cached:
        video_id = extract_video_id(url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")

        # Step 1: Get metadata via InnerTube (fast, works from any IP)
        meta = None
        t0 = time.time()
        try:
            raw = await get_video_info_fast(video_id)
            if raw:
                meta = parse_video_info(raw, video_id)
                logger.info(f"InnerTube metadata for {video_id} in {time.time()-t0:.2f}s")
        except Exception as e:
            logger.warning(f"InnerTube metadata failed: {e}")

        # Step 2: Get streaming URL via yt-dlp with PO token + mweb (primary method)
        audio = None
        try:
            info = await extract_info(url)
            audio = pick_best_audio_url(info)
            if audio.get("url"):
                if not meta:
                    meta = build_video_info(info)
                logger.info(f"yt-dlp audio for {video_id} (audio_only=" + str(audio.get("is_audio_only")) + ")")
        except Exception as e:
            logger.warning(f"yt-dlp audio failed: {e}")

        # Step 3: Return result or error
        if not audio or not audio.get("url") or not meta:
            raise HTTPException(
                status_code=503,
                detail="Audio streaming unavailable. YouTube may be blocking this server's IP."
            )

        is_audio_only = audio.get("is_audio_only", False)

        cached = {
            "id": meta["id"],
            "title": meta["title"],
            "thumbnail": meta.get("thumbnail", ""),
            "duration": meta.get("duration"),
            "duration_string": meta.get("duration_string", ""),
            "uploader": meta.get("uploader", ""),
            "audio": audio,
            "format_type": "audio_only" if is_audio_only else "video_audio_combined",
            "note": "Audio-only stream" if is_audio_only else "Combined stream",
            "method": "yt-dlp",
        }
        await cache_set(cache_key, cached, ttl=1800)

    if redirect:
        stream_url = cached.get("audio", {}).get("url")
        if not stream_url:
            raise HTTPException(status_code=404, detail="No audio URL found")
        return RedirectResponse(url=stream_url, status_code=302)

    return {**cached, "cached": True if cached else False}


# ── /api/video ────────────────────────────────────────────────────────────────
@app.get("/api/video", tags=["Download"])
async def get_video(
    url: str = Query(..., description="YouTube video URL"),
    resolution: str = Query("best", description="best | worst | 360p | 480p | 720p | 1080p"),
    redirect: bool = Query(False, description="Redirect to stream URL"),
    _: None = Depends(rate_limit),
):
    """
    Get direct video stream URL at desired resolution.
    """
    cache_key = make_cache_key("video", url, resolution)
    cached = await cache_get(cache_key)

    if not cached:
        try:
            info = await extract_info(url)
        except yt_dlp.utils.DownloadError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        video = pick_best_video_url(info, resolution)
        meta = build_video_info(info)
        cached = {
            "id": meta["id"],
            "title": meta["title"],
            "thumbnail": meta["thumbnail"],
            "duration": meta["duration"],
            "duration_string": meta["duration_string"],
            "uploader": meta["uploader"],
            "video": video,
        }
        await cache_set(cache_key, cached, ttl=1800)

    if redirect:
        stream_url = cached.get("video", {}).get("url")
        if not stream_url:
            raise HTTPException(status_code=404, detail="No video URL found")
        return RedirectResponse(url=stream_url, status_code=302)

    return {**cached, "cached": True if cached else False}


# ── /api/formats ──────────────────────────────────────────────────────────────
@app.get("/api/formats", tags=["Info"])
async def get_formats(
    url: str = Query(..., description="YouTube video URL"),
    _: None = Depends(rate_limit),
):
    """
    List all available download formats for a video.
    """
    cache_key = make_cache_key("formats", url)
    cached = await cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    try:
        info = await extract_info(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    formats = []
    for f in info.get("formats", []):
        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution") or f"{f.get('height', '?')}p",
            "fps": f.get("fps"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "abr": f.get("abr"),
            "vbr": f.get("vbr"),
            "filesize": f.get("filesize"),
            "type": "audio" if f.get("vcodec") == "none" else ("video+audio" if f.get("acodec") != "none" else "video"),
        })

    result = {
        "id": info.get("id"),
        "title": info.get("title"),
        "format_count": len(formats),
        "formats": formats,
    }
    await cache_set(cache_key, result)
    return {**result, "cached": False}


# ── /api/search ───────────────────────────────────────────────────────────────
@app.get("/api/search", tags=["Search"])
async def search(
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, ge=1, le=20, description="Number of results (max 20)"),
    _: None = Depends(rate_limit),
):
    """
    Search YouTube and return video results.
    Fast path: InnerTube API (<500ms)
    Fallback: yt-dlp search
    """
    cache_key = make_cache_key("search", q, limit)
    cached = await cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    # Fast path: Direct InnerTube search (~300ms)
    t0 = time.time()
    try:
        results = await search_youtube_fast(q, limit)
        if results:
            elapsed = time.time() - t0
            result = {
                "query": q,
                "count": len(results),
                "results": results,
                "cached": False,
                "method": "innertube",
                "response_ms": int(elapsed * 1000),
            }
            await cache_set(cache_key, result, ttl=300)
            logger.info(f"✓ InnerTube search '{q}' in {elapsed:.2f}s, {len(results)} results")
            return result
    except Exception as e:
        logger.warning(f"InnerTube search failed: {e}, falling back to yt-dlp")

    # Fallback: yt-dlp search
    try:
        entries = await search_yt(q, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    results = []
    for entry in entries:
        if not entry:
            continue
        results.append({
            "id": entry.get("id"),
            "title": entry.get("title"),
            "url": entry.get("url") or f"https://youtube.com/watch?v={entry.get('id')}",
            "duration": entry.get("duration"),
            "duration_string": format_duration(entry.get("duration")),
            "thumbnail": entry.get("thumbnail") or f"https://i.ytimg.com/vi/{entry.get('id')}/hqdefault.jpg",
            "uploader": entry.get("uploader") or entry.get("channel"),
            "view_count": entry.get("view_count"),
        })

    result = {"query": q, "count": len(results), "results": results, "method": "yt-dlp"}
    await cache_set(cache_key, result, ttl=300)  # 5 min for search
    return {**result, "cached": False}


# ── /api/stream ──────────────────────────────────────────────────────────────
@app.get("/api/stream", tags=["Download"])
async def get_stream(
    url: str = Query(..., description="YouTube video URL"),
    redirect: bool = Query(True, description="Redirect to stream URL (default True)"),
    _: None = Depends(rate_limit),
):
    """
    Get direct stream URL via InnerTube (fast!).
    Default redirects directly to the stream.
    """
    cache_key = make_cache_key("stream", url)
    cached = await cache_get(cache_key)

    if not cached:
        video_id = extract_video_id(url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")

        try:
            streams = await get_stream_urls_fast(video_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Stream extraction failed: {e}")

        if not streams or not streams.get("audio"):
            raise HTTPException(status_code=404, detail="No audio stream found")

        cached = streams
        await cache_set(cache_key, cached, ttl=1800)  # 30 min (URLs expire)

    if redirect:
        stream_url = cached.get("audio", {}).get("url")
        if not stream_url:
            raise HTTPException(status_code=404, detail="No stream URL found")
        return RedirectResponse(url=stream_url, status_code=302)

    return {**cached, "cached": True if cached else False}


# ── /api/playlist ─────────────────────────────────────────────────────────────
@app.get("/api/playlist", tags=["Info"])
async def get_playlist(
    url: str = Query(..., description="YouTube playlist URL"),
    limit: int = Query(20, ge=1, le=100),
    _: None = Depends(rate_limit),
):
    """
    Get all videos in a YouTube playlist.
    """
    cache_key = make_cache_key("playlist", url, limit)
    cached = await cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    try:
        opts = {"extract_flat": True, "playlistend": limit}
        info = await extract_info(url, opts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    entries = []
    for entry in (info.get("entries") or []):
        if not entry:
            continue
        entries.append({
            "id": entry.get("id"),
            "title": entry.get("title"),
            "url": entry.get("url") or f"https://youtube.com/watch?v={entry.get('id')}",
            "duration": entry.get("duration"),
            "duration_string": format_duration(entry.get("duration")),
            "thumbnail": f"https://i.ytimg.com/vi/{entry.get('id')}/hqdefault.jpg",
            "uploader": entry.get("uploader"),
        })

    result = {
        "playlist_title": info.get("title"),
        "playlist_id": info.get("id"),
        "uploader": info.get("uploader"),
        "video_count": len(entries),
        "videos": entries,
    }
    await cache_set(cache_key, result, ttl=600)
    return {**result, "cached": False}


# ── Error Handlers ────────────────────────────────────────────────────────────
@app.exception_handler(404)
async def not_found(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": "Endpoint not found", "docs": "/docs", "path": str(request.url.path)}
    )

@app.exception_handler(500)
async def server_error(request: Request, exc):
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "message": "Please try again later"}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler"""
    logger.error(f"Unhandled exception: {type(exc).__name__}: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "An unexpected error occurred",
            "type": type(exc).__name__,
            "message": "Please try again later"
        }
    )


@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup"""
    logger.info("Starting YT Download API...")
    
    if REDIS_ENABLED:
        try:
            await get_redis()
            logger.info("✓ Redis connection initialized")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Using in-memory cache.")
    
    logger.info(f"✓ API started with {RATE_LIMIT} req/min rate limit")
    logger.info(f"✓ Cache TTL: {CACHE_TTL}s")
    logger.info(f"✓ Circuit breaker threshold: {_circuit_breaker['failure_threshold']} failures")
    
    # Start proxy checker in background if enabled
    if proxy_checker and ENABLE_PROXY_CHECKER:
        asyncio.create_task(proxy_checker.run_continuous())
        logger.info("✓ Background proxy checker started")
    
    # Self-ping to prevent platform sleep (Render, Railway, etc.)
    asyncio.create_task(_self_ping_loop())
    logger.info("✓ Self-ping started (prevents platform sleep)")

async def _self_ping_loop():
    """Background task that pings /health every 10 minutes to prevent platform sleep."""
    import httpx
    await asyncio.sleep(60)  # Wait 1 min before first ping
    while True:
        try:
            port = os.getenv("PORT", "8000")
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://127.0.0.1:{port}/health", timeout=5.0)
                if resp.status_code == 200:
                    logger.debug("Self-ping OK")
                else:
                    logger.warning(f"Self-ping returned {resp.status_code}")
        except Exception as e:
            logger.warning(f"Self-ping failed: {e}")
        await asyncio.sleep(600)  # Every 10 minutes

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global _redis_client
    logger.info("Shutting down YT Download API...")
    
    # Close InnerTube HTTP client
    try:
        await close_http_client()
        logger.info("✓ InnerTube HTTP client closed")
    except:
        pass
    
    # Stop proxy checker
    if proxy_checker:
        proxy_checker.stop()
    
    if _redis_client:
        try:
            await _redis_client.close()
            logger.info("✓ Redis connection closed")
        except:
            pass


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    workers = int(os.getenv("WORKERS", "4"))
    
    # Use uvloop for better async performance
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        logger.info("✓ Using uvloop for enhanced performance")
    except ImportError:
        logger.warning("uvloop not available, using default event loop")
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        workers=workers,
        reload=False,
        log_level="info",
        access_log=True,
        limit_concurrency=1000,
        limit_max_requests=10000,  # Restart workers after 10k requests
        timeout_keep_alive=5,
        backlog=2048,  # Connection backlog
    )
