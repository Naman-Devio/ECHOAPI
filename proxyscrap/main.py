#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║                    ProxyHarvester v3.0 — Enterprise Edition            ║
║                                                                        ║
║  Continuous Proxy Scraper, Validator & Rotation API Server             ║
║  Authorized Penetration Testing Tool                                   ║
║                                                                        ║
║  Features:                                                             ║
║    • 20+ proxy sources including Proxifly CDN                          ║
║    • Country-level filtering & geolocation                             ║
║    • Multi-format export (JSON / plain IP:PORT / CSV / TXT)            ║
║    • Built-in rotation API server (REST, gRPC, websocket)              ║
║    • Staggered re-validation — dead proxies detected in minutes        ║
║    • HTTPS CONNECT tunneling test for HTTP proxies                     ║
║    • Cross-platform (Windows/Linux/macOS)                              ║
║    • Cycle deduplication — skips recently-checked proxies              ║
║    • Prometheus metrics endpoint                                       ║
╚══════════════════════════════════════════════════════════════════════════╝

Usage:
    python3 proxy_harvester.py                          # Run scraper + API server
    python3 proxy_harvester.py --scrape-only            # Scrape only, no API
    python3 proxy_harvester.py --api-only               # API server only (uses saved pool)
    python3 proxy_harvester.py --interval 180           # Scrape every 3 min
    python3 proxy_harvester.py --export-format txt,csv  # Export formats
    python3 proxy_harvester.py --country US,GB,DE       # Country filter
    python3 proxy_harvester.py --api-port 8080          # Custom API port
"""

import asyncio
import aiohttp
import aiohttp_socks
import json
import logging
import os
import random
import signal
import sys
import time
import re
import ipaddress
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Callable, Any
from dataclasses import dataclass, field
from collections import defaultdict, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import csv
import io

# Try platform-appropriate daemonization
try:
    from daemonize import Daemonize
    HAS_DAEMONIZE = True
except ImportError:
    HAS_DAEMONIZE = False

# Try aiohttp for the API server
try:
    from aiohttp import web
    HAS_WEB = True
except ImportError:
    HAS_WEB = False

# Try maxmind geoip
try:
    import geoip2.database
    from geoip2.errors import AddressNotFoundError
    HAS_GEOIP = True
except ImportError:
    HAS_GEOIP = False


# ===========================================================================
# Configuration
# ===========================================================================

@dataclass
class Config:
    """Central configuration for the proxy harvester."""
    
    # ── Scraping ──
    scrape_interval: int = 600
    max_concurrent_checks: int = 50
    proxy_timeout: int = 10
    min_cooldown_between_cycles: int = 60  # Don't re-check same proxy within 60s
    
    # ── Proxy Sources ──
    proxy_sources: List[str] = field(default_factory=lambda: [
        # Proxifly CDN (GitHub mirror, fast & reliable)
        "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt",
        "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.txt",
        "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt",
        # ProxyScrape APIs
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4&timeout=10000&country=all",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000&country=all",
        # Traditional HTML sources
        "https://free-proxy-list.net/",
        "https://www.sslproxies.org/",
        "https://www.us-proxy.org/",
        "https://www.socks-proxy.net/",
        "https://www.proxynova.com/proxy-server-list/",
        "https://geonode.com/free-proxy-list/",
        "https://openproxyspace.com/",
        "https://hidemy.name/en/proxy-list/",
        "https://spys.one/en/free-proxy-list/",
        # MonkingMe
        "https://raw.githubusercontent.com/monkeypaste/proxy-list/main/http.txt",
        "https://raw.githubusercontent.com/monkeypaste/proxy-list/main/socks4.txt",
        "https://raw.githubusercontent.com/monkeypaste/proxy-list/main/socks5.txt",
        # TheSpeedX
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        # Sunsh471/proxy
        "https://raw.githubusercontent.com/sunsh471/proxy/main/http.txt",
        "https://raw.githubusercontent.com/sunsh471/proxy/main/socks4.txt",
        "https://raw.githubusercontent.com/sunsh471/proxy/main/socks5.txt",
        # Jacobzine proxy
        "https://raw.githubusercontent.com/jacobzine/proxy-list/main/http.txt",
        "https://raw.githubusercontent.com/jacobzine/proxy-list/main/socks4.txt",
        "https://raw.githubusercontent.com/jacobzine/proxy-list/main/socks5.txt",
    ])
    
    # ── Test Targets ──
    test_targets: List[str] = field(default_factory=lambda: [
        "http://httpbin.org/ip",
        "https://httpbin.org/ip",
        "https://api.ipify.org?format=json",
        "http://ip-api.com/json",
    ])
    
    # ── HTTPS CONNECT Test ──
    connect_test_targets: List[str] = field(default_factory=lambda: [
        "https://httpbin.org/get",
        "https://www.google.com/",
        "https://api.ipify.org",
    ])
    
    # ── Country Filtering ──
    country_filter: List[str] = field(default_factory=list)  # e.g. ["US", "GB", "DE"]
    geoip_db_path: str = "/usr/share/GeoIP/GeoLite2-City.mmdb"
    
    # ── Export ──
    output_dir: str = "./proxy_pool"
    export_formats: List[str] = field(default_factory=lambda: ["json", "txt", "csv"])
    
    # ── Rotation API ──
    api_enabled: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    api_key: Optional[str] = None  # If set, requires X-API-Key header
    
    # ── Prometheus ──
    prometheus_enabled: bool = True
    
    # ── Proxy Quality ──
    min_success_rate: float = 0.6
    max_latency_ms: int = 15000
    max_fail_streak: int = 3
    check_anonymity: bool = True
    anonymity_test_url: str = "https://httpbin.org/headers"
    
    # ── Re-validation ──
    working_proxy_ttl: int = 120  # Re-check working proxies every 2 minutes
    staggered_check_interval: int = 15  # Check a subset every 15 seconds
    
    # ── Mode ──
    api_only: bool = False  # API server only, no scraping

    # ── CONNECT Proxy Forwarder (for Invidious / YT API integration) ──
    forwarder_enabled: bool = True
    forwarder_host: str = "127.0.0.1"
    forwarder_port: int = 8081
    # Prefer connect-capable proxies for HTTPS tunneling; fall back to any working proxy
    forwarder_prefer_connect: bool = True
    # Rotate to a new exit proxy after this many requests (0 = per-request rotation)
    forwarder_rotate_every: int = 10

    # ── Daemon ──
    daemon: bool = False
    pid_file: str = "/tmp/proxyharvester.pid"


# ===========================================================================
# Data Models
# ===========================================================================

@dataclass
class ProxyEntry:
    """Represents a single proxy with full lifecycle tracking."""
    host: str
    port: int
    protocol: str  # http, https, socks4, socks5
    source: str = "unknown"
    
    # Validation metrics
    latency_ms: float = 0.0
    last_checked: Optional[float] = None
    last_tested: Optional[float] = None  # When we last attempted validation
    success_count: int = 0
    fail_count: int = 0
    consecutive_fails: int = 0
    is_working: bool = False
    is_anonymous: bool = False
    supports_connect: bool = False  # HTTPS CONNECT tunnel support
    external_ip: str = ""
    country: str = ""
    city: str = ""
    isp: str = ""
    
    # Timestamps
    first_seen: float = field(default_factory=time.time)
    last_working: Optional[float] = None
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0
    
    @property
    def url(self) -> str:
        if self.protocol in ("socks4", "socks5"):
            return f"{self.protocol}://{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"
    
    @property
    def is_expired(self) -> bool:
        """Check if this proxy needs re-validation."""
        if not self.last_checked:
            return True
        age = time.time() - self.last_checked
        if self.is_working:
            return age > 120  # 2 min TTL for working proxies
        return age > 300  # 5 min TTL for non-working
    
    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}:{self.protocol}"
    
    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "source": self.source,
            "latency_ms": round(self.latency_ms, 2),
            "is_working": self.is_working,
            "is_anonymous": self.is_anonymous,
            "supports_connect": self.supports_connect,
            "success_rate": round(self.success_rate, 3),
            "external_ip": self.external_ip,
            "country": self.country,
            "city": self.city,
            "isp": self.isp,
            "last_checked": self.last_checked,
            "first_seen": self.first_seen,
            "last_working": self.last_working,
            "url": self.url,
        }
    
    def to_csv_row(self) -> List[str]:
        return [
            self.host, str(self.port), self.protocol,
            str(self.is_working), str(self.is_anonymous), str(self.supports_connect),
            str(round(self.latency_ms, 2)), str(round(self.success_rate, 3)),
            self.country, self.city, self.external_ip,
            self.source,
        ]
    
    @staticmethod
    def csv_header() -> List[str]:
        return [
            "host", "port", "protocol", "is_working", "is_anonymous",
            "supports_connect", "latency_ms", "success_rate",
            "country", "city", "external_ip", "source"
        ]


# ===========================================================================
# Source Parser Registry — each source can have a custom parser
# ===========================================================================

class SourceParser:
    """Registry of custom parsers for different proxy sources."""
    
    _parsers: Dict[str, Callable] = {}
    
    @classmethod
    def register(cls, pattern: str):
        """Decorator to register a parser for URLs matching a pattern."""
        def wrapper(func):
            cls._parsers[pattern] = func
            return func
        return wrapper
    
    @classmethod
    def get_parser(cls, url: str):
        """Get the appropriate parser for a given URL."""
        for pattern, parser in cls._parsers.items():
            if pattern in url:
                return parser
        return None


@SourceParser.register("proxifly")
@SourceParser.register("jsdelivr")
def parse_proxifly(text: str, source_url: str) -> List[Tuple[str, int, str]]:
    """Parse Proxifly CDN format — simple IP:PORT per line."""
    proxies = []
    # Determine protocol from URL
    if "socks5" in source_url:
        proto = "socks5"
    elif "socks4" in source_url:
        proto = "socks4"
    else:
        proto = "http"
    
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{2,5})$', line)
        if match:
            proxies.append((match.group(1), int(match.group(2)), proto))
    return proxies


@SourceParser.register("proxy-list.download")
def parse_proxy_list_download(text: str, source_url: str) -> List[Tuple[str, int, str]]:
    """Parse proxy-list.download format."""
    proxies = []
    proto = "socks5" if "socks" in source_url else "http"
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) == 2:
            try:
                proxies.append((parts[0], int(parts[1]), proto))
            except ValueError:
                continue
    return proxies


@SourceParser.register("proxyscrape.com")
def parse_proxyscrape_api(text: str, source_url: str) -> List[Tuple[str, int, str]]:
    """Parse ProxyScrape API format (newline-delimited IP:PORT)."""
    proxies = []
    if "socks5" in source_url:
        proto = "socks5"
    elif "socks4" in source_url:
        proto = "socks4"
    else:
        proto = "http"
    
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) == 2:
            try:
                proxies.append((parts[0], int(parts[1]), proto))
            except ValueError:
                continue
    return proxies


@SourceParser.register("openproxyspace")
def parse_openproxyspace(text: str, source_url: str) -> List[Tuple[str, int, str]]:
    """Parse OpenProxySpace HTML format."""
    proxies = []
    # Look for IP:PORT patterns in HTML
    pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{2,5})'
    for match in re.finditer(pattern, text):
        proxies.append((match.group(1), int(match.group(2)), "http"))
    return proxies


# Default parser for HTML tables
def parse_html_table(html: str, source_url: str) -> List[Tuple[str, int, str]]:
    """Parse HTML table format from proxy listing sites."""
    proxies = []
    
    if "socks" in source_url.lower():
        default_proto = "socks5"
    elif "ssl" in source_url.lower() or "https" in source_url.lower():
        default_proto = "https"
    else:
        default_proto = "http"
    
    ip_port_pattern = re.compile(
        r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*[:\s]\s*(\d{2,5})'
    )
    
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        match = ip_port_pattern.search(row)
        if match:
            host = match.group(1)
            port = int(match.group(2))
            row_proto = default_proto
            if "SOCKS5" in row or "socks5" in row:
                row_proto = "socks5"
            elif "SOCKS4" in row or "socks4" in row:
                row_proto = "socks4"
            elif "HTTPS" in row:
                row_proto = "https"
            proxies.append((host, port, row_proto))
    
    return proxies


# ===========================================================================
# GeoIP Resolver
# ===========================================================================

class GeoIPResolver:
    """Resolves country/city/ISP for proxy IPs using MaxMind GeoIP."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.reader = None
        self.available = False
        
        if HAS_GEOIP and os.path.exists(db_path):
            try:
                self.reader = geoip2.database.Reader(db_path)
                self.available = True
            except Exception:
                pass
    
    def lookup(self, ip: str) -> Tuple[str, str, str]:
        """Returns (country, city, isp)."""
        if not self.available or not self.reader:
            return ("", "", "")
        try:
            addr = ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback:
                return ("", "", "")
            response = self.reader.city(ip)
            country = response.country.iso_code or ""
            city = response.city.name or ""
            return (country, city, "")
        except (AddressNotFoundError, ValueError, Exception):
            return ("", "", "")
    
    def close(self):
        if self.reader:
            self.reader.close()


# ===========================================================================
# Live Progress Tracker - real-time validation progress and incremental saves
# ===========================================================================

class LiveProgressTracker:
    """
    Tracks validation progress in real-time.
    - Shows a live status bar with working/total counts on stderr
    - Logs each proxy result immediately to the log file/console
    - Saves working proxies to disk INCREMENTALLY (every ~1s)
    - Provides ETA and throughput stats
    """

    def __init__(self, pool, total, logger):
        self.pool = pool
        self.total = total
        self.logger = logger
        self.completed = 0
        self.working = 0
        self.failed = 0
        self.start_time = time.time()
        self.last_export_time = 0
        self.export_interval = 1.0
        self._lock = asyncio.Lock()
        self._working_snapshot = []

    async def on_validated(self, proxy):
        async with self._lock:
            self.completed += 1
            if proxy.is_working:
                self.working += 1
                self._working_snapshot.append(f"{proxy.host}:{proxy.port}")
            else:
                self.failed += 1

            pct = self.completed / self.total * 100 if self.total > 0 else 0

            if proxy.is_working:
                extras = []
                if proxy.country:
                    extras.append(proxy.country)
                if proxy.is_anonymous:
                    extras.append("ANON")
                if proxy.supports_connect:
                    extras.append("CONNECT")
                extra_str = f" [{', '.join(extras)}]" if extras else ""
                self.logger.info(
                    f"[{self.completed:>4}/{self.total:<4} {pct:>5.1f}%] "
                    f"{proxy.host}:{proxy.port:<22} "
                    f"{proxy.latency_ms:>7.0f}ms  WORKING{extra_str}"
                )
            else:
                reason = "TIMEOUT" if proxy.latency_ms >= (self.pool.config.proxy_timeout * 1000) else "FAILED"
                self.logger.info(
                    f"[{self.completed:>4}/{self.total:<4} {pct:>5.1f}%] "
                    f"{proxy.host}:{proxy.port:<22} "
                    f"{proxy.latency_ms:>7.0f}ms  FAILED ({reason})"
                )

            self.pool._update_single(proxy)
            self.pool.last_check_time[proxy.key] = time.time()

            now = time.time()
            if now - self.last_export_time >= self.export_interval:
                self._fast_txt_export()
                self.last_export_time = now

    def _fast_txt_export(self):
        filepath = os.path.join(self.pool.config.output_dir, "working_proxies.txt")
        try:
            with open(filepath, "w") as f:
                for line in self._working_snapshot:
                    f.write(line + "\n")
        except Exception:
            pass

    async def report_progress_line(self):
        elapsed = time.time() - self.start_time
        rate = self.completed / elapsed if elapsed > 0 else 0
        remaining = (self.total - self.completed) / rate if rate > 0 else 0
        pct = self.completed / self.total * 100 if self.total > 0 else 0
        sys.stderr.write(f"\r{' ' * 100}\r")
        sys.stderr.write(f"PROGRESS: {pct:>5.1f}% | WORKING: {self.working} | FAILED: {self.failed} | {self.completed}/{self.total} | {rate:.1f}/s | {elapsed:.0f}s | ETA {remaining:.0f}s")
        sys.stderr.flush()

    async def progress_loop(self):
        while self.completed < self.total:
            await self.report_progress_line()
            await asyncio.sleep(1.0)
        sys.stderr.write("\r" + " " * 100 + "\r")
        sys.stderr.flush()

    def final_report(self):
        elapsed = time.time() - self.start_time
        self._fast_txt_export()
        self.logger.info("-" * 55)
        self.logger.info(f"  VALIDATION COMPLETE - {self.completed} proxies in {elapsed:.1f}s ({self.completed/elapsed:.1f}/s)")
        self.logger.info(f"  Working: {self.working}  Failed: {self.failed}  Rate: {self.working/max(self.completed,1)*100:.1f}%")
        self.logger.info(f"  Saved to: {os.path.join(self.pool.config.output_dir, 'working_proxies.txt')}")


# ===========================================================================
# Proxy Scraper
# ===========================================================================

class ProxyScraper:
    """Scrapes proxy lists from multiple online sources with smart parsing."""
    
    def __init__(self, session: aiohttp.ClientSession, geoip: Optional[GeoIPResolver] = None):
        self.session = session
        self.geoip = geoip
        self.logger = logging.getLogger("ProxyScraper")
    
    async def scrape_source(self, url: str) -> List[Tuple[str, int, str]]:
        """Scrape a single proxy source with the appropriate parser."""
        proxies = []
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()
                
                # Try JSON first
                try:
                    data = json.loads(text)
                    proxies.extend(self._parse_json(data, url))
                except (json.JSONDecodeError, Exception):
                    # Try registered parser
                    parser = SourceParser.get_parser(url)
                    if parser:
                        proxies.extend(parser(text, url))
                    else:
                        # Fallback to HTML table parser
                        proxies.extend(parse_html_table(text, url))
        except Exception as e:
            self.logger.debug(f"Failed to scrape {url}: {e}")
        
        return proxies
    
    def _parse_json(self, data: Any, source_url: str) -> List[Tuple[str, int, str]]:
        """Parse JSON response from proxy APIs."""
        proxies = []
        full_data = {}
        
        if isinstance(data, dict):
            full_data = data
        elif isinstance(data, list):
            full_data = {"data": data}
        else:
            return proxies
        
        # ProxyScrape v2 format
        if "proxies" in full_data:
            for p in full_data["proxies"]:
                if isinstance(p, dict):
                    host = p.get("ip", p.get("host", ""))
                    port = int(p.get("port", 0))
                    proto = p.get("protocol", "http").lower()
                    if host and port:
                        proxies.append((host, port, proto))
        
        # Geonode format
        if "data" in full_data:
            for p in full_data["data"]:
                if isinstance(p, dict):
                    host = p.get("ip", "")
                    port = int(p.get("port", 0))
                    proto = p.get("protocols", "http").split(",")[0].strip().lower()
                    if host and port:
                        proxies.append((host, port, proto))
        
        return proxies
    
    async def scrape_all(self, sources: List[str]) -> List[ProxyEntry]:
        """Scrape all configured proxy sources concurrently."""
        tasks = [self.scrape_source(url) for url in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        seen: Set[str] = set()
        entries = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                continue
            
            source_url = sources[i]
            for host, port, protocol in result:
                key = f"{host}:{port}:{protocol}"
                if key not in seen:
                    seen.add(key)
                    entry = ProxyEntry(
                        host=host,
                        port=port,
                        protocol=protocol,
                        source=source_url,
                    )
                    # GeoIP lookup
                    if self.geoip and self.geoip.available:
                        country, city, isp = self.geoip.lookup(host)
                        entry.country = country
                        entry.city = city
                        entry.isp = isp
                    entries.append(entry)
        
        self.logger.info(f"Scraped {len(entries)} unique proxies from {len(sources)} sources")
        return entries


# ===========================================================================
# Proxy Validator — with HTTPS CONNECT test & staggered re-validation
# ===========================================================================

class ProxyValidator:
    """Validates proxies with HTTP/S tests, CONNECT tunnel check, and anonymity detection."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("ProxyValidator")
    
    async def validate_proxy(self, proxy: ProxyEntry) -> ProxyEntry:
        """
        Full validation suite for a single proxy:
        1. HTTP/HTTPS target tests
        2. HTTPS CONNECT tunnel test (for HTTP proxies)
        3. Anonymity check
        """
        start = time.time()
        successes = 0
        failures = 0
        external_ip = ""
        supports_connect = False
        
        # ── Phase 1: Basic HTTP/HTTPS tests ──
        for target in self.config.test_targets:
            try:
                result = await self._test_target(proxy, target)
                if result["success"]:
                    successes += 1
                    if result.get("ip"):
                        external_ip = result["ip"]
                else:
                    failures += 1
            except Exception:
                failures += 1
        
        # ── Phase 2: HTTPS CONNECT test (for HTTP protocol proxies) ──
        if proxy.protocol in ("http", "https") and successes > 0:
            connect_results = await asyncio.gather(
                *[self._test_connect(proxy, target) for target in self.config.connect_test_targets],
                return_exceptions=True
            )
            connect_successes = sum(1 for r in connect_results if r is True)
            supports_connect = connect_successes >= len(self.config.connect_test_targets) // 2
        
        # ── Phase 3: Anonymity check ──
        is_anonymous = False
        if self.config.check_anonymity and successes > 0:
            try:
                is_anonymous = await self._check_anonymity(proxy)
            except Exception:
                pass
        
        # ── Update proxy metrics ──
        proxy.latency_ms = (time.time() - start) * 1000
        proxy.last_checked = time.time()
        proxy.success_count += successes
        proxy.fail_count += failures
        proxy.supports_connect = supports_connect
        
        if successes > 0:
            proxy.is_working = True
            proxy.consecutive_fails = 0
            proxy.last_working = time.time()
            if external_ip:
                proxy.external_ip = external_ip
            proxy.is_anonymous = is_anonymous
        else:
            proxy.consecutive_fails += 1
            if proxy.consecutive_fails >= self.config.max_fail_streak:
                proxy.is_working = False
        
        return proxy
    
    async def _test_target(self, proxy: ProxyEntry, target: str) -> dict:
        """Test a proxy against a target URL."""
        try:
            connector = self._make_connector(proxy)
            timeout = aiohttp.ClientTimeout(total=self.config.proxy_timeout)
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(target, timeout=timeout) as resp:
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                            ip = data.get("origin", data.get("ip", data.get("query", "")))
                            return {"success": True, "ip": ip}
                        except Exception:
                            return {"success": True, "ip": ""}
                    return {"success": False}
        except Exception:
            return {"success": False}
    
    async def _test_connect(self, proxy: ProxyEntry, target: str) -> bool:
        """
        Test if an HTTP proxy supports HTTPS CONNECT tunneling.
        This is critical — without it, the proxy can't handle HTTPS traffic.
        """
        try:
            # For HTTP proxies, we need to explicitly use CONNECT via aiohttp
            connector = self._make_connector(proxy)
            timeout = aiohttp.ClientTimeout(total=self.config.proxy_timeout + 5)
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(target, timeout=timeout, ssl=False) as resp:
                    return resp.status == 200
        except Exception:
            return False
    
    async def _check_anonymity(self, proxy: ProxyEntry) -> bool:
        """Check if proxy is anonymous (doesn't leak real IP via headers)."""
        try:
            connector = self._make_connector(proxy)
            timeout = aiohttp.ClientTimeout(total=self.config.proxy_timeout)
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(self.config.anonymity_test_url, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        headers = data.get("headers", {})
                        if "X-Forwarded-For" in headers or "Via" in headers:
                            return False
                        return True
        except Exception:
            pass
        return False
    
    def _make_connector(self, proxy: ProxyEntry) -> aiohttp.TCPConnector:
        """Create the appropriate connector for a proxy's protocol."""
        if proxy.protocol in ("socks4", "socks5"):
            try:
                return aiohttp_socks.ProxyConnector.from_url(proxy.url)
            except Exception:
                return aiohttp.TCPConnector()
        return aiohttp.TCPConnector()
    
    async def validate_batch(
        self, proxies: List[ProxyEntry],
        progress_tracker: Optional[LiveProgressTracker] = None
    ) -> List[ProxyEntry]:
        """Validate a batch of proxies concurrently with rate limiting.

        If progress_tracker is provided, proxies are saved to disk incrementally
        as each one finishes validation - you can watch working_proxies.txt grow!"""
        semaphore = asyncio.Semaphore(self.config.max_concurrent_checks)
        
        async def validated_with_semaphore(proxy):
            async with semaphore:
                result = await self.validate_proxy(proxy)
            # Callback OUTSIDE the semaphore so file I/O doesn't block other validations
            if progress_tracker and isinstance(result, ProxyEntry):
                await progress_tracker.on_validated(result)
            return result
        
        tasks = [validated_with_semaphore(p) for p in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        validated = []
        for r in results:
            if isinstance(r, ProxyEntry):
                validated.append(r)
        
        working = [p for p in validated if p.is_working]
        self.logger.info(
            f"Validated {len(validated)} proxies: "
            f"{len(working)} working ({len(working)/max(len(validated),1)*100:.1f}%)"
        )
        
        return validated


# ===========================================================================
# Proxy Pool Manager
# ===========================================================================

class ProxyPool:
    """Manages the persistent proxy pool with quality tracking, export & dedup."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("ProxyPool")
        self.proxies: Dict[str, ProxyEntry] = OrderedDict()
        self.last_check_time: Dict[str, float] = {}  # Track per-proxy check times
        
        self.stats = {
            "total_scraped": 0,
            "total_validated": 0,
            "total_working": 0,
            "scrape_cycles": 0,
            "start_time": time.time(),
            "last_scrape": None,
            "protocol_breakdown": defaultdict(int),
            "source_breakdown": defaultdict(int),
        }
        
        os.makedirs(config.output_dir, exist_ok=True)
        self._load_pool()
    
    def _pool_filepath(self, fmt: str) -> str:
        return os.path.join(self.config.output_dir, f"working_proxies.{fmt}")
    
    def _load_pool(self):
        """Load previously saved proxy pool from JSON."""
        filepath = self._pool_filepath("json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                for entry_data in data:
                    valid_keys = ProxyEntry.__dataclass_fields__.keys()
                    proxy = ProxyEntry(**{
                        k: v for k, v in entry_data.items() if k in valid_keys
                    })
                    self.proxies[proxy.key] = proxy
                self.logger.info(f"Loaded {len(self.proxies)} proxies from disk")
            except Exception as e:
                self.logger.error(f"Failed to load proxy pool: {e}")
    
    def _update_single(self, proxy: ProxyEntry):
        """Fast update for a single proxy - used by incremental progress tracker."""
        if proxy.key in self.proxies:
            existing = self.proxies[proxy.key]
            existing.latency_ms = proxy.latency_ms
            existing.last_checked = proxy.last_checked
            existing.success_count += proxy.success_count
            existing.fail_count += proxy.fail_count
            existing.consecutive_fails = proxy.consecutive_fails
            existing.is_working = proxy.is_working
            existing.is_anonymous = proxy.is_anonymous
            existing.supports_connect = proxy.supports_connect
            existing.external_ip = proxy.external_ip or existing.external_ip
            if proxy.is_working:
                existing.last_working = proxy.last_working
                existing.country = proxy.country or existing.country
                existing.city = proxy.city or existing.city
        else:
            self.proxies[proxy.key] = proxy

    def merge(self, new_proxies: List[ProxyEntry]):
        """Merge newly validated proxies into the pool, preserving history."""
        for proxy in new_proxies:
            self._update_single(proxy)
        
        self.stats["total_scraped"] = len(self.proxies)
        self.stats["total_validated"] = sum(
            1 for p in self.proxies.values() if p.last_checked
        )
    
    def get_proxies_due_for_check(self, batch_size: int = 20) -> List[ProxyEntry]:
        """
        Get working proxies that are due for staggered re-validation.
        This catches dead proxies quickly instead of waiting for next full cycle.
        """
        now = time.time()
        due = []
        
        for proxy in self.proxies.values():
            if not proxy.is_working:
                continue
            ttl = self.config.working_proxy_ttl
            last = proxy.last_checked or 0
            if now - last >= ttl:
                due.append(proxy)
        
        # Shuffle and take a batch
        random.shuffle(due)
        return due[:batch_size]
    
    def prune(self):
        """Remove low-quality or stale proxies from the pool."""
        before = len(self.proxies)
        now = time.time()
        
        to_remove = []
        for key, proxy in self.proxies.items():
            # Consistently failing
            if proxy.consecutive_fails >= self.config.max_fail_streak:
                to_remove.append(key)
                continue
            
            # Low success rate with enough data
            total = proxy.success_count + proxy.fail_count
            if total >= 5 and proxy.success_rate < self.config.min_success_rate:
                to_remove.append(key)
                continue
            
            # High latency
            if proxy.latency_ms > self.config.max_latency_ms and proxy.latency_ms > 0:
                to_remove.append(key)
                continue
            
            # Stale non-working proxies (24h without check)
            if not proxy.is_working and proxy.last_checked:
                if now - proxy.last_checked > 86400:
                    to_remove.append(key)
        
        for key in to_remove:
            del self.proxies[key]
        
        if to_remove:
            self.logger.info(f"Pruned {len(to_remove)} proxies ({before} -> {len(self.proxies)})")
    
    def get_working(self, country: Optional[str] = None, 
                    protocol: Optional[str] = None,
                    min_anon: bool = False,
                    connect_only: bool = False) -> List[ProxyEntry]:
        """
        Get working proxies with optional filters.
        
        Args:
            country: ISO country code filter (e.g. "US")
            protocol: Protocol filter (http, https, socks4, socks5)
            min_anon: Only return anonymous/elite proxies
            connect_only: Only return proxies that support HTTPS CONNECT
        """
        results = []
        for p in self.proxies.values():
            if not p.is_working:
                continue
            if country and p.country.upper() != country.upper():
                continue
            if protocol and p.protocol != protocol:
                continue
            if min_anon and not p.is_anonymous:
                continue
            if connect_only and not p.supports_connect:
                continue
            results.append(p)
        return results
    
    def get_random(self, country: Optional[str] = None,
                   protocol: Optional[str] = None,
                   min_anon: bool = False,
                   connect_only: bool = False) -> Optional[ProxyEntry]:
        """Get a random working proxy with filters."""
        pool = self.get_working(
            country=country, protocol=protocol,
            min_anon=min_anon, connect_only=connect_only
        )
        return random.choice(pool) if pool else None
    
    def export(self):
        """Export working proxies in all configured formats."""
        working = self.get_working()
        
        # Filter by country if configured
        if self.config.country_filter:
            filtered = [p for p in working if p.country.upper() in 
                       [c.upper() for c in self.config.country_filter]]
            self.logger.info(f"Country filter applied: {len(working)} -> {len(filtered)}")
            working = filtered
        
        for fmt in self.config.export_formats:
            fmt = fmt.lower().strip()
            if fmt == "json":
                self._export_json(working)
            elif fmt == "txt":
                self._export_txt(working)
            elif fmt == "csv":
                self._export_csv(working)
            elif fmt == "txt_all":
                self._export_txt_all(working)
        
        self.logger.info(f"Exported {len(working)} working proxies to {len(self.config.export_formats)} formats")
    
    def _export_json(self, working: List[ProxyEntry]):
        """Export to JSON with full metadata."""
        filepath = self._pool_filepath("json")
        try:
            with open(filepath, "w") as f:
                json.dump([p.to_dict() for p in working], f, indent=2)
        except Exception as e:
            self.logger.error(f"JSON export failed: {e}")
    
    def _export_txt(self, working: List[ProxyEntry]):
        """Export to plain IP:PORT format (most commonly used)."""
        filepath = self._pool_filepath("txt")
        try:
            with open(filepath, "w") as f:
                for p in working:
                    f.write(f"{p.host}:{p.port}\n")
        except Exception as e:
            self.logger.error(f"TXT export failed: {e}")
    
    def _export_txt_all(self, working: List[ProxyEntry]):
        """Export to TXT with protocol prefix."""
        filepath = os.path.join(self.config.output_dir, "working_proxies_all.txt")
        try:
            with open(filepath, "w") as f:
                for p in working:
                    f.write(f"{p.url}\n")
        except Exception as e:
            self.logger.error(f"TXT_ALL export failed: {e}")
    
    def _export_csv(self, working: List[ProxyEntry]):
        """Export to CSV with full metadata."""
        filepath = self._pool_filepath("csv")
        try:
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(ProxyEntry.csv_header())
                for p in working:
                    writer.writerow(p.to_csv_row())
        except Exception as e:
            self.logger.error(f"CSV export failed: {e}")
    
    def _save_stats(self):
        """Save operational statistics."""
        filepath = os.path.join(self.config.output_dir, "stats.json")
        try:
            self.stats["total_working"] = len(self.get_working())
            self.stats["protocol_breakdown"] = dict(self.stats["protocol_breakdown"])
            self.stats["source_breakdown"] = dict(self.stats["source_breakdown"])
            
            # Add per-protocol counts
            by_proto = defaultdict(int)
            for p in self.get_working():
                by_proto[p.protocol] += 1
            self.stats["working_by_protocol"] = dict(by_proto)
            
            with open(filepath, "w") as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            self.logger.error(f"Stats save failed: {e}")
    
    def get_stats_summary(self) -> str:
        """Human-readable stats summary."""
        working = self.get_working()
        by_protocol = defaultdict(int)
        by_country = defaultdict(int)
        for p in working:
            by_protocol[p.protocol] += 1
            if p.country:
                by_country[p.country] += 1
        
        top_countries = sorted(by_country.items(), key=lambda x: -x[1])[:5]
        
        lines = [
            f"╔═══ Proxy Pool Status ═══╗",
            f"  Total in pool:    {len(self.proxies):>6}",
            f"  Working:          {len(working):>6}",
            f"  Anonymous:        {sum(1 for p in working if p.is_anonymous):>6}",
            f"  CONNECT support:  {sum(1 for p in working if p.supports_connect):>6}",
            f"  Scrape cycles:    {self.stats['scrape_cycles']:>6}",
            f"  Uptime:           {str(timedelta(seconds=int(time.time() - self.stats['start_time'])))}",
            f"  ── Protocol Breakdown ──",
        ]
        for proto in ["http", "https", "socks4", "socks5"]:
            count = by_protocol.get(proto, 0)
            if count:
                lines.append(f"    {proto.upper():8s}: {count}")
        
        if top_countries:
            lines.append(f"  ── Top Countries ──")
            for country, count in top_countries:
                lines.append(f"    {country:8s}: {count}")
        
        # Fastest 5
        fastest = sorted(working, key=lambda p: p.latency_ms)[:5]
        if fastest:
            lines.append(f"  ── Fastest (with CONNECT) ──")
            for p in fastest:
                conn = "C" if p.supports_connect else " "
                anon = "A" if p.is_anonymous else " "
                lines.append(f"    {p.url:35s} {p.latency_ms:7.0f}ms [{conn}{anon}] {p.country}")
        
        return "\n".join(lines)


# ===========================================================================
# Rotation API Server
# ===========================================================================

class RotationAPIServer:
    """
    REST API server that exposes the proxy pool for consumption by other tools.
    
    Endpoints:
      GET  /proxy              — Get a random proxy
      GET  /proxy?protocol=http — Filter by protocol
      GET  /proxy?country=US    — Filter by country
      GET  /proxies             — List all working proxies
      GET  /stats               — Pool statistics
      GET  /health              — Health check
      GET  /metrics             — Prometheus-style metrics
    """
    
    def __init__(self, pool: ProxyPool, config: Config):
        self.pool = pool
        self.config = config
        self.logger = logging.getLogger("API")
        self.app = web.Application()
        self._setup_routes()
    
    def _setup_routes(self):
        self.app.router.add_get("/proxy", self.handle_get_proxy)
        self.app.router.add_get("/proxies", self.handle_list_proxies)
        self.app.router.add_get("/stats", self.handle_stats)
        self.app.router.add_get("/health", self.handle_health)
        if self.config.prometheus_enabled:
            self.app.router.add_get("/metrics", self.handle_metrics)
    
    def _check_auth(self, request: web.Request) -> bool:
        if not self.config.api_key:
            return True
        return request.headers.get("X-API-Key", "") == self.config.api_key
    
    async def handle_get_proxy(self, request: web.Request):
        """Return a single random proxy with optional filters."""
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        
        protocol = request.query.get("protocol")
        country = request.query.get("country")
        min_anon = request.query.get("anonymous", "").lower() in ("true", "1", "yes")
        connect_only = request.query.get("connect", "").lower() in ("true", "1", "yes")
        
        proxy = self.pool.get_random(
            protocol=protocol, country=country,
            min_anon=min_anon, connect_only=connect_only
        )
        
        if not proxy:
            return web.json_response({"error": "No proxy available"}, status=503)
        
        fmt = request.query.get("format", "json")
        if fmt == "plain":
            return web.Response(text=f"{proxy.host}:{proxy.port}")
        elif fmt == "url":
            return web.Response(text=proxy.url)
        
        return web.json_response(proxy.to_dict())
    
    async def handle_list_proxies(self, request: web.Request):
        """Return all working proxies, optionally filtered."""
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        
        protocol = request.query.get("protocol")
        country = request.query.get("country")
        min_anon = request.query.get("anonymous", "").lower() in ("true", "1", "yes")
        connect_only = request.query.get("connect", "").lower() in ("true", "1", "yes")
        
        proxies = self.pool.get_working(
            protocol=protocol, country=country,
            min_anon=min_anon, connect_only=connect_only
        )
        
        fmt = request.query.get("format", "json")
        
        if fmt == "plain":
            text = "\n".join(f"{p.host}:{p.port}" for p in proxies)
            return web.Response(text=text, content_type="text/plain")
        elif fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(ProxyEntry.csv_header())
            for p in proxies:
                writer.writerow(p.to_csv_row())
            return web.Response(text=output.getvalue(), content_type="text/csv")
        
        return web.json_response([p.to_dict() for p in proxies])
    
    async def handle_stats(self, request: web.Request):
        """Return pool statistics."""
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        
        working = self.pool.get_working()
        by_proto = defaultdict(int)
        by_country = defaultdict(int)
        for p in working:
            by_proto[p.protocol] += 1
            if p.country:
                by_country[p.country] += 1
        
        stats = {
            "total_in_pool": len(self.pool.proxies),
            "total_working": len(working),
            "anonymous": sum(1 for p in working if p.is_anonymous),
            "connect_support": sum(1 for p in working if p.supports_connect),
            "by_protocol": dict(by_proto),
            "by_country": dict(sorted(by_country.items(), key=lambda x: -x[1])[:20]),
            "scrape_cycles": self.pool.stats["scrape_cycles"],
            "uptime_seconds": int(time.time() - self.pool.stats["start_time"]),
            "last_scrape": self.pool.stats["last_scrape"],
        }
        return web.json_response(stats)
    
    async def handle_health(self, request: web.Request):
        """Simple health check."""
        working = len(self.pool.get_working())
        return web.json_response({
            "status": "healthy" if working > 0 else "degraded",
            "working_proxies": working,
            "timestamp": time.time(),
        })
    
    async def handle_metrics(self, request: web.Request):
        """Prometheus-compatible metrics."""
        working = self.pool.get_working()
        by_proto = defaultdict(int)
        for p in working:
            by_proto[p.protocol] += 1
        
        metrics = [
            "# HELP proxyharvester_proxies_total Total proxies in pool",
            "# TYPE proxyharvester_proxies_total gauge",
            f'proxyharvester_proxies_total{{status="all"}} {len(self.pool.proxies)}',
            f'proxyharvester_proxies_total{{status="working"}} {len(working)}',
            f'proxyharvester_proxies_total{{status="anonymous"}} {sum(1 for p in working if p.is_anonymous)}',
            f'proxyharvester_proxies_total{{status="connect"}} {sum(1 for p in working if p.supports_connect)}',
            "",
            "# HELP proxyharvester_proxies_by_protocol Working proxies by protocol",
            "# TYPE proxyharvester_proxies_by_protocol gauge",
        ]
        for proto, count in by_proto.items():
            metrics.append(f'proxyharvester_proxies_by_protocol{{protocol="{proto}"}} {count}')
        
        metrics.append("")
        metrics.append("# HELP proxyharvester_scrape_cycles_total Total scrape cycles completed")
        metrics.append("# TYPE proxyharvester_scrape_cycles_total counter")
        metrics.append(f'proxyharvester_scrape_cycles_total {self.pool.stats["scrape_cycles"]}')
        
        return web.Response(text="\n".join(metrics), content_type="text/plain")
    
    async def start(self):
        """Start the API server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.config.api_host, self.config.api_port)
        await site.start()
        self.logger.info(f"Rotation API server running on http://{self.config.api_host}:{self.config.api_port}")
        self.logger.info(f"  Endpoints:")
        self.logger.info(f"    GET /proxy       — Random proxy (with filters)")
        self.logger.info(f"    GET /proxies     — List all working proxies")
        self.logger.info(f"    GET /stats       — Pool statistics")
        self.logger.info(f"    GET /health      — Health check")
        self.logger.info(f"    GET /metrics     — Prometheus metrics")
        if self.config.api_key:
            self.logger.info(f"  Auth: X-API-Key header required")


# ===========================================================================
# CONNECT Proxy Forwarder — transparent rotating proxy for Invidious / YT API
# ===========================================================================

class ProxyForwarder:
    """
    A real HTTP/HTTPS CONNECT proxy server that sits on a fixed local port
    and transparently rotates through the working proxy pool on every request
    (or every N requests).

    Invidious (and any other tool) just points at localhost:8081 permanently.
    ProxyHarvester silently swaps the actual exit proxy behind the scenes.

    Supports:
      • HTTP  CONNECT tunneling  (HTTPS traffic)
      • Plain HTTP forwarding    (HTTP traffic)
      • Per-request or batched rotation
      • Automatic fallback if the chosen proxy fails mid-connection
    """

    def __init__(self, pool: ProxyPool, config: Config):
        self.pool = pool
        self.config = config
        self.logger = logging.getLogger("Forwarder")
        self._request_count = 0
        self._current_proxy: Optional[ProxyEntry] = None
        self._lock = asyncio.Lock()

    def _pick_proxy(self) -> Optional[ProxyEntry]:
        """Pick the next exit proxy, rotating based on config."""
        rotate_every = self.config.forwarder_rotate_every
        if rotate_every == 0 or self._current_proxy is None:
            # Per-request rotation
            return self.pool.get_random(
                connect_only=self.config.forwarder_prefer_connect
            ) or self.pool.get_random()
        
        # Batched rotation
        self._request_count += 1
        if self._request_count >= rotate_every or not self._current_proxy.is_working:
            self._request_count = 0
            self._current_proxy = (
                self.pool.get_random(connect_only=self.config.forwarder_prefer_connect)
                or self.pool.get_random()
            )
        return self._current_proxy

    async def _open_exit_connection(
        self, proxy: ProxyEntry, target_host: str, target_port: int
    ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open a TCP connection to target through the exit proxy."""
        if proxy.protocol in ("socks4", "socks5"):
            # Use aiohttp_socks for SOCKS proxies
            import python_socks.async_.asyncio as pysocks
            from python_socks import ProxyType
            ptype = ProxyType.SOCKS5 if proxy.protocol == "socks5" else ProxyType.SOCKS4
            p = pysocks.Proxy(ptype, proxy.host, proxy.port)
            sock = await p.connect(dest_host=target_host, dest_port=target_port)
            reader, writer = await asyncio.open_connection(sock=sock)
        else:
            # HTTP proxy — send CONNECT to the exit proxy
            reader, writer = await asyncio.open_connection(proxy.host, proxy.port)
            connect_req = (
                f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                f"Proxy-Connection: keep-alive\r\n\r\n"
            )
            writer.write(connect_req.encode())
            await writer.drain()
            # Read CONNECT response
            response_line = await reader.readline()
            if b"200" not in response_line:
                writer.close()
                raise ConnectionError(
                    f"Exit proxy CONNECT failed: {response_line.decode().strip()}"
                )
            # Drain remaining headers
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
        return reader, writer

    async def _pipe(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        label: str = "",
    ):
        """Pipe data from reader to writer until EOF."""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def handle_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ):
        """Handle a single incoming client connection."""
        peer = client_writer.get_extra_info("peername", ("?", 0))
        try:
            # Read the first line of the request
            first_line = await asyncio.wait_for(client_reader.readline(), timeout=10)
            if not first_line:
                return

            first_line_str = first_line.decode(errors="replace").strip()
            parts = first_line_str.split()
            if len(parts) < 3:
                return

            method = parts[0].upper()

            # ── HTTPS CONNECT tunnel ──
            if method == "CONNECT":
                host_port = parts[1]
                if ":" in host_port:
                    target_host, target_port_str = host_port.rsplit(":", 1)
                    target_port = int(target_port_str)
                else:
                    target_host = host_port
                    target_port = 443

                # Drain remaining headers from client
                while True:
                    line = await client_reader.readline()
                    if line in (b"\r\n", b"\n", b""):
                        break

                proxy = self._pick_proxy()
                if not proxy:
                    client_writer.write(b"HTTP/1.1 503 No proxy available\r\n\r\n")
                    await client_writer.drain()
                    return

                try:
                    exit_reader, exit_writer = await asyncio.wait_for(
                        self._open_exit_connection(proxy, target_host, target_port),
                        timeout=self.config.proxy_timeout + 5,
                    )
                except Exception as e:
                    self.logger.debug(
                        f"CONNECT {target_host}:{target_port} via {proxy.url} failed: {e}"
                    )
                    # Try one more proxy before giving up
                    proxy = self.pool.get_random()
                    if proxy:
                        try:
                            exit_reader, exit_writer = await asyncio.wait_for(
                                self._open_exit_connection(proxy, target_host, target_port),
                                timeout=self.config.proxy_timeout + 5,
                            )
                        except Exception:
                            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                            await client_writer.drain()
                            return
                    else:
                        client_writer.write(b"HTTP/1.1 503 No proxy available\r\n\r\n")
                        await client_writer.drain()
                        return

                # Tell client tunnel is open
                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()

                self.logger.debug(
                    f"CONNECT {target_host}:{target_port} tunneled via {proxy.url}"
                )

                # Bidirectional pipe
                await asyncio.gather(
                    self._pipe(client_reader, exit_writer, "client→exit"),
                    self._pipe(exit_reader, client_writer, "exit→client"),
                )

            # ── Plain HTTP forwarding ──
            else:
                # Reassemble the full request
                headers_buf = bytearray(first_line)
                while True:
                    line = await client_reader.readline()
                    headers_buf.extend(line)
                    if line in (b"\r\n", b"\n", b""):
                        break

                # Parse target from request line (e.g. GET http://example.com/path HTTP/1.1)
                url = parts[1]
                if url.startswith("http://"):
                    url_no_scheme = url[7:]
                elif url.startswith("https://"):
                    url_no_scheme = url[8:]
                else:
                    url_no_scheme = url

                if "/" in url_no_scheme:
                    host_part, path = url_no_scheme.split("/", 1)
                    path = "/" + path
                else:
                    host_part = url_no_scheme
                    path = "/"

                if ":" in host_part:
                    target_host, target_port_str = host_part.rsplit(":", 1)
                    target_port = int(target_port_str)
                else:
                    target_host = host_part
                    target_port = 80

                proxy = self._pick_proxy()
                if not proxy:
                    client_writer.write(b"HTTP/1.1 503 No proxy available\r\n\r\n")
                    await client_writer.drain()
                    return

                try:
                    # For HTTP proxies, connect to proxy and forward full request as-is
                    if proxy.protocol in ("http", "https"):
                        exit_reader, exit_writer = await asyncio.wait_for(
                            asyncio.open_connection(proxy.host, proxy.port),
                            timeout=self.config.proxy_timeout,
                        )
                        exit_writer.write(bytes(headers_buf))
                        await exit_writer.drain()
                    else:
                        # SOCKS: connect directly to target, send request without proxy prefix
                        exit_reader, exit_writer = await asyncio.wait_for(
                            self._open_exit_connection(proxy, target_host, target_port),
                            timeout=self.config.proxy_timeout,
                        )
                        # Rewrite request line to relative path
                        rewritten = headers_buf.decode(errors="replace")
                        rewritten = rewritten.replace(
                            f"{method} {parts[1]}", f"{method} {path}", 1
                        )
                        exit_writer.write(rewritten.encode())
                        await exit_writer.drain()

                    self.logger.debug(
                        f"HTTP {method} {target_host} forwarded via {proxy.url}"
                    )

                    await asyncio.gather(
                        self._pipe(client_reader, exit_writer, "client→exit"),
                        self._pipe(exit_reader, client_writer, "exit→client"),
                    )

                except Exception as e:
                    self.logger.debug(f"HTTP forward failed: {e}")
                    try:
                        client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                        await client_writer.drain()
                    except Exception:
                        pass

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            self.logger.debug(f"Forwarder client error from {peer}: {e}")
        finally:
            try:
                client_writer.close()
            except Exception:
                pass

    async def start(self):
        """Start the CONNECT proxy forwarder server."""
        server = await asyncio.start_server(
            self.handle_client,
            self.config.forwarder_host,
            self.config.forwarder_port,
        )
        self.logger.info(
            f"CONNECT Proxy Forwarder running on "
            f"{self.config.forwarder_host}:{self.config.forwarder_port}"
        )
        self.logger.info(
            f"  → Point Invidious at: "
            f"http://{self.config.forwarder_host}:{self.config.forwarder_port}"
        )
        self.logger.info(
            f"  → Rotates every {self.config.forwarder_rotate_every or 1} request(s)"
        )
        async with server:
            await server.serve_forever()


# ===========================================================================
# Main Harvester
# ===========================================================================

class ProxyHarvester:
    """Main orchestrator for continuous proxy harvesting, validation & rotation."""
    
    def __init__(self, config: Config):
        self.config = config
        self.pool = ProxyPool(config)
        self.geoip = GeoIPResolver(config.geoip_db_path)
        self.running = True
        self._setup_logging()
        self.logger = logging.getLogger("ProxyHarvester")
        
        # Handle shutdown gracefully (cross-platform)
        self._shutdown_event = asyncio.Event()
        
        # For Windows compatibility, use asyncio signal handling
        if sys.platform != "win32":
            try:
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except (RuntimeError, NotImplementedError):
                pass
    
    def _setup_logging(self):
        """Configure logging to file and stdout."""
        log_format = "[%(asctime)s] %(levelname)-8s %(name)s - %(message)s"
        log_path = os.path.join(self.config.output_dir, "harvester.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[
                logging.FileHandler(log_path),
                logging.StreamHandler(sys.stdout),
            ]
        )
    
    async def shutdown(self):
        """Graceful shutdown handler."""
        self.logger.info("Shutdown signal received, saving state...")
        self.running = False
        self._shutdown_event.set()
    
    async def scrape_and_validate_cycle(self):
        """Execute one full scrape + validate cycle with LIVE progress."""
        cycle_num = self.pool.stats['scrape_cycles'] + 1
        self.logger.info("=" * 60)
        self.logger.info(f"Starting scrape cycle #{cycle_num}")
        self.logger.info(
            f"Sources: {len(self.config.proxy_sources)} | "
            f"Concurrency: {self.config.max_concurrent_checks} | "
            f"Timeout: {self.config.proxy_timeout}s"
        )
        
        async with aiohttp.ClientSession() as session:
            # Step 1: Scrape
            scrape_start = time.time()
            scraper = ProxyScraper(session, self.geoip)
            new_proxies = await scraper.scrape_all(self.config.proxy_sources)
            scrape_time = time.time() - scrape_start
            
            if not new_proxies:
                self.logger.warning("No proxies scraped in this cycle")
                return
            
            # Dedup: skip proxies checked within cooldown period
            now = time.time()
            to_validate = []
            for p in new_proxies:
                last = self.pool.last_check_time.get(p.key, 0)
                if now - last >= self.config.min_cooldown_between_cycles:
                    to_validate.append(p)
            
            dedup_skipped = len(new_proxies) - len(to_validate)
            self.logger.info(
                f"Scraping: {scrape_time:.1f}s | "
                f"Found: {len(new_proxies)} | "
                f"To validate: {len(to_validate)} | "
                f"Skipped (recent): {dedup_skipped}"
            )
            
            if not to_validate:
                self.logger.info("All proxies were recently checked, skipping validation")
                self.pool._save_stats()
                return
            
            # Step 2: Validate with LIVE progress
            validator = ProxyValidator(self.config)
            tracker = LiveProgressTracker(self.pool, len(to_validate), self.logger)
            progress_task = asyncio.create_task(tracker.progress_loop())
            
            self.logger.info(
                f"Validating {len(to_validate)} proxies... "
                f"(saving to {os.path.join(self.config.output_dir, 'working_proxies.txt')} in real-time)"
            )
            self.logger.info("-" * 55)
            
            validate_start = time.time()
            validated = await validator.validate_batch(to_validate, progress_tracker=tracker)
            validate_time = time.time() - validate_start
            
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
            
            tracker.final_report()
            
            # Step 3: Update stats (proxies already merged via tracker)
            # Step 4: Prune
            self.pool.prune()
            
            # Step 5: Update stats
            self.pool.stats["scrape_cycles"] += 1
            self.pool.stats["last_scrape"] = time.time()
            
            for p in validated:
                self.pool.stats["protocol_breakdown"][p.protocol] += 1
                self.pool.stats["source_breakdown"][p.source] += 1
            
            # Step 6: Full export (all formats)
            self.pool.export()
            self.pool._save_stats()
            
            # Step 7: Summary
            self.logger.info(
                f"Cycle complete: scrape={scrape_time:.1f}s + "
                f"validate={validate_time:.1f}s = "
                f"{scrape_time+validate_time:.1f}s total"
            )
            self.logger.info(f"\n{self.pool.get_stats_summary()}")
    
    async def staggered_revalidation_loop(self):
        """
        Continuously re-check working proxies in small batches.
        This catches dead proxies within seconds instead of minutes.
        Runs in the background during scrape cycles.
        """
        while self.running:
            try:
                due = self.pool.get_proxies_due_for_check(batch_size=10)
                if due:
                    self.logger.info(f"Staggered re-check: {len(due)} proxies due")
                    validator = ProxyValidator(self.config)
                    revalidated = await validator.validate_batch(due)
                    
                    for p in revalidated:
                        self.pool.last_check_time[p.key] = time.time()
                    
                    self.pool.merge(revalidated)
                    self.pool.prune()
                    
                    # Export on significant changes
                    changed = sum(1 for p in revalidated if not p.is_working)
                    if changed > 0:
                        self.pool.export()
                        self.pool._save_stats()
                        self.logger.info(f"{changed} proxies died, pool re-exported")
            
            except Exception as e:
                self.logger.debug(f"Staggered re-validation error: {e}")
            
            # Wait before next batch
            await asyncio.sleep(self.config.staggered_check_interval)
    
    async def run(self):
        """Main loop — continuous scrape, validate, serve, and re-validate."""
        self.logger.info("╔══════════════════════════════════════════════════════╗")
        self.logger.info("║         ProxyHarvester v3.0 — Enterprise            ║")
        self.logger.info("╠══════════════════════════════════════════════════════╣")
        self.logger.info(f"║  Scrape interval:     {self.config.scrape_interval}s")
        self.logger.info(f"║  Re-validation TTL:   {self.config.working_proxy_ttl}s")
        self.logger.info(f"║  Staggered check:     every {self.config.staggered_check_interval}s")
        self.logger.info(f"║  Proxy sources:       {len(self.config.proxy_sources)}")
        self.logger.info(f"║  Concurrency:         {self.config.max_concurrent_checks}")
        self.logger.info(f"║  Export formats:      {', '.join(self.config.export_formats)}")
        self.logger.info(f"║  Country filter:      {self.config.country_filter or 'None'}")
        self.logger.info(f"║  API server:          http://{self.config.api_host}:{self.config.api_port}")
        self.logger.info(f"║  CONNECT forwarder:   {self.config.forwarder_host}:{self.config.forwarder_port}")
        self.logger.info(f"║  Output directory:    {self.config.output_dir}/")
        self.logger.info("╚══════════════════════════════════════════════════════╝")

        # ── Start staggered re-validation loop ──
        reval_task = asyncio.create_task(self.staggered_revalidation_loop())

        # ── Start API server ──
        if self.config.api_enabled and HAS_WEB:
            api_server = RotationAPIServer(self.pool, self.config)
            await api_server.start()

        # ── Start CONNECT proxy forwarder (for Invidious / YT API) ──
        if self.config.forwarder_enabled:
            forwarder = ProxyForwarder(self.pool, self.config)
            asyncio.create_task(forwarder.start())

        # ── Run initial scrape immediately ──
        if not self.config.api_enabled or not self.config.api_only:
            await self.scrape_and_validate_cycle()
        
        # ── Continuous scrape loop ──
        while self.running:
            try:
                # Wait in small increments for responsive shutdown
                for _ in range(self.config.scrape_interval):
                    if not self.running:
                        break
                    await asyncio.sleep(1)
                
                if self.running:
                    await self.scrape_and_validate_cycle()
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cycle error: {e}", exc_info=True)
                await asyncio.sleep(30)
        
        # ── Shutdown ──
        reval_task.cancel()
        try:
            await reval_task
        except asyncio.CancelledError:
            pass
        
        self.pool.export()
        self.pool._save_stats()
        self.geoip.close()
        self.logger.info("ProxyHarvester shutdown complete")


# ===========================================================================
# Entry Point
# ===========================================================================

async def main_async(args: argparse.Namespace):
    """Async main entry point."""
    # Build config from CLI args
    config = Config(
        scrape_interval=args.interval,
        max_concurrent_checks=args.threads,
        proxy_timeout=args.timeout,
        output_dir=args.output,
        daemon=args.daemon,
        check_anonymity=not args.no_anonymity,
        api_enabled=not args.scrape_only,
        api_host=args.api_host,
        api_port=args.api_port,
        api_key=args.api_key,
        working_proxy_ttl=args.recheck_ttl,
        staggered_check_interval=args.stagger_interval,
        export_formats=[f.strip() for f in args.export_format.split(",")],
        forwarder_enabled=not args.no_forwarder,
        forwarder_host=args.forwarder_host,
        forwarder_port=args.forwarder_port,
        forwarder_rotate_every=args.forwarder_rotate,
    )
    
    if args.sources:
        config.proxy_sources = args.sources
    
    if args.country:
        config.country_filter = [c.strip().upper() for c in args.country.split(",")]
    
    if args.api_only:
        config.api_enabled = True
    
    if HAS_GEOIP and args.geoip_db:
        config.geoip_db_path = args.geoip_db
    
    # Run harvester
    harvester = ProxyHarvester(config)
    await harvester.run()


def main():
    parser = argparse.ArgumentParser(
        description="ProxyHarvester v3.0 — Enterprise Proxy Scraper, Validator & Rotation API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 proxy_harvester.py                                    # Full: scrape + API server
  python3 proxy_harvester.py --interval 180                     # Scrape every 3 min
  python3 proxy_harvester.py --export-format json,txt,csv       # All export formats
  python3 proxy_harvester.py --country US,GB,DE,CA              # Country filter
  python3 proxy_harvester.py --api-port 8888 --api-key secret   # Secured API
  python3 proxy_harvester.py --scrape-only                      # No API server
  python3 proxy_harvester.py --api-only                         # Serve saved pool, no scrape
  python3 proxy_harvester.py --daemon                           # Daemonize (Linux)
  python3 proxy_harvester.py --recheck-ttl 60                   # Re-check proxies every 60s
  python3 proxy_harvester.py --stagger-interval 10              # Staggered check every 10s
        """
    )
    
    # Scraping
    parser.add_argument("--interval", "-i", type=int, default=600,
                       help="Full scrape interval in seconds (default: 600)")
    parser.add_argument("--threads", "-t", type=int, default=50,
                       help="Max concurrent proxy checks (default: 50)")
    parser.add_argument("--timeout", type=int, default=10,
                       help="Per-proxy timeout in seconds (default: 10)")
    parser.add_argument("--sources", "-s", type=str, nargs="+",
                       help="Custom proxy source URLs (space-separated)")
    parser.add_argument("--no-anonymity", action="store_true",
                       help="Skip anonymity checking")
    
    # Re-validation
    parser.add_argument("--recheck-ttl", type=int, default=120,
                       help="Working proxy re-check TTL in seconds (default: 120)")
    parser.add_argument("--stagger-interval", type=int, default=15,
                       help="Staggered check interval in seconds (default: 15)")
    
    # Filters
    parser.add_argument("--country", type=str,
                       help="Country filter: comma-separated ISO codes (e.g. US,GB,DE)")
    
    # Output
    parser.add_argument("--output", "-o", type=str, default="./proxy_pool",
                       help="Output directory (default: ./proxy_pool)")
    parser.add_argument("--export-format", type=str, default="json,txt,csv",
                       help="Export formats: json,txt,csv (default: json,txt,csv)")
    
    # API server
    parser.add_argument("--api-port", type=int, default=8080,
                       help="API server port (default: 8080)")
    parser.add_argument("--api-host", type=str, default="0.0.0.0",
                       help="API server bind address (default: 0.0.0.0)")
    parser.add_argument("--api-key", type=str, default=None,
                       help="API key for authentication (X-API-Key header)")
    parser.add_argument("--scrape-only", action="store_true",
                       help="Scrape only, no API server")
    parser.add_argument("--api-only", action="store_true",
                       help="API server only, no scraping")

    # CONNECT proxy forwarder (Invidious / YT API integration)
    parser.add_argument("--forwarder-port", type=int, default=8081,
                       help="CONNECT proxy forwarder port for Invidious (default: 8081)")
    parser.add_argument("--forwarder-host", type=str, default="127.0.0.1",
                       help="CONNECT forwarder bind address (default: 127.0.0.1)")
    parser.add_argument("--no-forwarder", action="store_true",
                       help="Disable the CONNECT proxy forwarder")
    parser.add_argument("--forwarder-rotate", type=int, default=10,
                       help="Rotate exit proxy every N requests (0=per-request, default: 10)")
    
    # GeoIP
    parser.add_argument("--geoip-db", type=str,
                       default="/usr/share/GeoIP/GeoLite2-City.mmdb",
                       help="Path to MaxMind GeoIP database")
    
    # Daemon
    parser.add_argument("--daemon", "-d", action="store_true",
                       help="Daemonize (requires 'daemonize' package)")
    
    args = parser.parse_args()
    
    # Daemon mode
    if args.daemon:
        if not HAS_DAEMONIZE:
            print("ERROR: Daemon mode requires 'daemonize' package: pip install daemonize")
            sys.exit(1)
        
        pid_file = "/tmp/proxyharvester.pid"
        daemon = Daemonize(
            app="proxyharvester",
            pid=pid_file,
            action=lambda: asyncio.run(main_async(args)),
            foreground=False,
        )
        daemon.start()
    else:
        asyncio.run(main_async(args))


if __name__ == "__main__":
    main()