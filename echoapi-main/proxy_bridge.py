#!/usr/bin/env python3
"""
Proxy Bridge — Transfers proxies from ProxyHarvester → YT API
=============================================================

Reads working_proxies.json from proxyscrap/proxy_pool/ and splits
by protocol into echoapi-main/proxies/:
  - proxies/http.txt     (IP:PORT)
  - proxies/socks4.txt   (IP:PORT)
  - proxies/socks5.txt   (IP:PORT)

Can run continuously to keep proxies fresh.
"""

import json
import os
import time
import logging
import argparse
import sys
import requests
from pathlib import Path
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ProxyBridge")

# ── Paths ─────────────────────────────────────────────────────────────────────
# Project root is where this script lives (echoapi-main/)
SCRIPT_DIR = Path(__file__).parent.resolve()

# ProxyHarvester output (sibling directory)
SCRAPER_JSON = SCRIPT_DIR.parent / "proxyscrap" / "proxy_pool" / "working_proxies.json"

# ── WebShare API Config ───────────────────────────────────────────────────────
WEBSHARE_API_TOKEN = os.getenv("WEBSHARE_API_TOKEN", "")
WEBSHARE_API_BASE = "https://proxy.webshare.io/api/v2"

# YT API proxy input directory
PROXIES_DIR = SCRIPT_DIR / "proxies"
WORKING_DIR = PROXIES_DIR / "working"

# Protocol → output filename mapping (working/ = what ProxyManager reads)
PROTOCOL_FILES: Dict[str, str] = {
    "http": "http_working.txt",
    "socks4": "socks4_working.txt",
    "socks5": "socks5_working.txt",
}


def ensure_dirs():
    """Create proxy directories if they don't exist."""
    PROXIES_DIR.mkdir(exist_ok=True)
    WORKING_DIR.mkdir(exist_ok=True)


def load_scraper_proxies(json_path: Path) -> List[dict]:
    """Load working proxies from ProxyHarvester's JSON export."""
    if not json_path.exists():
        logger.warning(f"Scraper JSON not found: {json_path}")
        return []

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.error(f"Unexpected JSON format in {json_path}: expected list")
            return []
        logger.info(f"Loaded {len(data)} proxies from {json_path}")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        return []
    except Exception as e:
        logger.error(f"Failed to read {json_path}: {e}")
        return []


def split_by_protocol(proxies: List[dict]) -> Dict[str, List[str]]:
    """Split proxies by protocol and return IP:PORT format."""
    grouped: Dict[str, List[str]] = {"http": [], "socks4": [], "socks5": []}

    for proxy in proxies:
        proto = proxy.get("protocol", "").lower()
        host = proxy.get("host", "")
        port = proxy.get("port", "")

        if not host or not port:
            continue

        ip_port = f"{host}:{port}"

        if proto in grouped:
            grouped[proto].append(ip_port)
        else:
            # Unknown protocol — try to infer
            if "socks5" in proto:
                logger.warning(f"Unknown protocol '{proxy.get('protocol')}' for {ip_port}, treating as SOCKS5")
                grouped["socks5"].append(ip_port)
            elif "socks4" in proto:
                logger.warning(f"Unknown protocol '{proxy.get('protocol')}' for {ip_port}, treating as SOCKS4")
                grouped["socks4"].append(ip_port)
            else:
                logger.warning(f"Unknown protocol '{proxy.get('protocol')}' for {ip_port}, treating as HTTP")
                grouped["http"].append(ip_port)

    return grouped


def write_proxy_files(grouped: Dict[str, List[str]], stats: dict, raw_proxy_data: List[dict] = None):
    """Write proxy files and log the results.

    Writes:
      - proxies/working/{protocol}_working.txt  (for ProxyManager)
      - proxies/working/{protocol}_speed.json   (for speed-weighted selection)
      - proxies/{protocol}.txt                  (fallback for ProxyManager)
      - proxies/bridge_summary.json             (freshness tracker)
    """
    total = 0

    # Build a lookup: host:port -> latency_ms from raw proxy data
    speed_lookup: Dict[str, float] = {}
    if raw_proxy_data:
        for p in raw_proxy_data:
            host = p.get("host", "")
            port = p.get("port", "")
            latency_ms = p.get("latency_ms", 0)
            if host and port:
                key = f"{host}:{port}"
                speed_lookup[key] = latency_ms

    for proto, filename in PROTOCOL_FILES.items():
        # Dedup while preserving order (dict.fromkeys)
        proxies = list(dict.fromkeys(grouped.get(proto, [])))
        filepath = WORKING_DIR / filename

        with open(filepath, "w") as f:
            for proxy in proxies:
                f.write(f"{proxy}\n")

        count = len(proxies)
        total += count

        if count > 0:
            logger.info(f"  ✍  {filename:20s} → {count:4d} proxies")

            # Write speed JSON for this protocol
            speed_data = []
            for proxy_str in proxies:
                latency_ms = speed_lookup.get(proxy_str, 0)
                speed_seconds = round(latency_ms / 1000.0, 3) if latency_ms > 0 else 0.1
                speed_data.append({
                    "proxy": proxy_str,
                    "speed_seconds": speed_seconds,
                    "protocol": proto,
                })
            # Sort by speed (fastest first)
            speed_data.sort(key=lambda x: x["speed_seconds"])

            speed_file = WORKING_DIR / f"{proto}_speed.json"
            with open(speed_file, "w") as f:
                json.dump(speed_data, f, indent=2)
            logger.info(f"  ✓  {proto}_speed.json  → {len(speed_data)} entries")

            # Also write raw fallback file (proxies/{proto}.txt)
            raw_filepath = PROXIES_DIR / f"{proto}.txt"
            with open(raw_filepath, "w") as f:
                for proxy in proxies:
                    f.write(f"{proxy}\n")
            logger.info(f"  ✍  {proto}.txt          → {count:4d} proxies (fallback)")
        else:
            # Remove empty files so proxy_manager doesn't load dead lists
            for fpath in [filepath, WORKING_DIR / f"{proto}_speed.json", PROXIES_DIR / f"{proto}.txt"]:
                if fpath.exists():
                    fpath.unlink()
            logger.info(f"  -  {filename:20s} → empty (removed)")

    # Write a summary file so other components can check freshness
    summary = {
        "total_proxies": total,
        "by_protocol": {proto: len(grouped.get(proto, [])) for proto in PROTOCOL_FILES},
        "last_sync": time.time(),
        "scraper_stats": stats,
    }
    summary_path = PROXIES_DIR / "bridge_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"  ─── Total: {total} proxies synced to {WORKING_DIR}/")
    return total


def fetch_webshare_proxies(api_token: str) -> List[dict]:
    """Fetch proxies from WebShare API.
    
    Steps:
      1. Get download token from /proxy/config/
      2. Download proxy list using the token
      3. Parse ip:port:username:password format
    
    Returns list of dicts with host, port, user, pass, protocol keys.
    """
    if not api_token:
        return []

    headers = {"Authorization": f"Token {api_token}"}

    # Step 1: Get download token
    try:
        resp = requests.get(f"{WEBSHARE_API_BASE}/proxy/config/", headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.error(f"WebShare config failed: HTTP {resp.status_code}")
            return []
        config = resp.json()
        download_token = config.get("proxy_list_download_token")
        if not download_token:
            logger.error("No download token found in WebShare config")
            return []
        logger.info(f"  WebShare download token: {download_token[:15]}...")
    except Exception as e:
        logger.error(f"WebShare config error: {e}")
        return []

    # Step 2: Download proxy list
    try:
        dl_url = f"{WEBSHARE_API_BASE}/proxy/list/download/{download_token}/-/any/username/direct/-/"
        resp = requests.get(dl_url, timeout=15)
        if resp.status_code != 200:
            logger.error(f"WebShare download failed: HTTP {resp.status_code}")
            return []
        lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
        logger.info(f"  Downloaded {len(lines)} proxies from WebShare")
    except Exception as e:
        logger.error(f"WebShare download error: {e}")
        return []

    # Step 3: Parse ip:port:username:password
    proxies = []
    for line in lines:
        parts = line.split(":")
        if len(parts) == 4:
            host, port, user, pwd = parts
            try:
                proxies.append({
                    "host": host,
                    "port": int(port),
                    "user": user,
                    "pass": pwd,
                    "protocol": "http",
                })
            except ValueError:
                continue

    logger.info(f"  Parsed {len(proxies)} WebShare proxies")
    return proxies


def get_scraper_stats(json_path: Path) -> dict:
    """Get stats from the harvester's stats.json if available."""
    stats_path = json_path.parent / "stats.json"
    if stats_path.exists():
        try:
            with open(stats_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def sync_once():
    """Single sync: fetch proxies from all sources → split → write API proxy files.
    
    Sources (in priority order):
      1. WebShare API (if WEBSHARE_API_TOKEN is set)
      2. ProxyScrap (if working_proxies.json exists)
    """
    ensure_dirs()

    all_proxies: List[dict] = []
    source_stats: dict = {}

    # ── Source 1: WebShare API ──
    if WEBSHARE_API_TOKEN:
        logger.info("Fetching from WebShare API...")
        ws_proxies = fetch_webshare_proxies(WEBSHARE_API_TOKEN)
        if ws_proxies:
            all_proxies.extend(ws_proxies)
            source_stats["webshare"] = len(ws_proxies)
            logger.info(f"  ✓ WebShare: {len(ws_proxies)} proxies")
        else:
            logger.warning("  WebShare returned 0 proxies")

    # ── Source 2: ProxyScrap ──
    scraper_proxies = load_scraper_proxies(SCRAPER_JSON)
    if scraper_proxies:
        all_proxies.extend(scraper_proxies)
        source_stats["proxyscrap"] = len(scraper_proxies)

    if not all_proxies:
        logger.warning("No proxies from any source")
        return 0

    # ── Dedup by host:port (WebShare first since they're higher quality) ──
    seen = set()
    deduped = []
    for p in all_proxies:
        key = f"{p.get('host', '')}:{p.get('port', '')}"
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    all_proxies = deduped

    logger.info(f"  Total unique: {len(all_proxies)} proxies")

    grouped = split_by_protocol(all_proxies)
    total = write_proxy_files(grouped, source_stats, raw_proxy_data=all_proxies)
    return total


def get_json_mtime() -> float:
    """Get the last modified time of the scraper JSON."""
    try:
        return SCRAPER_JSON.stat().st_mtime
    except OSError:
        return 0


def run_continuous(interval: int = 300):
    """
    Run the bridge in a loop, checking for updated proxy files.
    
    Args:
        interval: Seconds between sync checks (default 300 = 5 min)
    """
    logger.info("=" * 55)
    logger.info("  Proxy Bridge — Continuous Mode")
    logger.info(f"  Watching: {SCRAPER_JSON}")
    logger.info(f"  Writing:  {PROXIES_DIR}/")
    logger.info(f"  Interval: {interval}s")
    logger.info("=" * 55)
    logger.info("")

    last_mtime = get_json_mtime()

    # Initial sync
    logger.info("Initial sync...")
    total = sync_once()
    if total > 0:
        logger.info(f"✓ Initial sync complete: {total} proxies imported")
    else:
        logger.info("No proxies found — will retry on next cycle")
    logger.info("")

    # Continuous loop
    while True:
        try:
            time.sleep(interval)

            current_mtime = get_json_mtime()
            if current_mtime > last_mtime:
                logger.info(f"Detected updated proxy file (mtime changed), re-syncing...")
                total = sync_once()
                if total > 0:
                    logger.info(f"✓ Sync complete: {total} proxies")
                last_mtime = current_mtime
            else:
                logger.debug(f"No changes detected (check every {interval}s)")

        except KeyboardInterrupt:
            logger.info("Proxy Bridge stopped by user")
            break
        except Exception as e:
            logger.error(f"Sync error: {e}")
            logger.info(f"Retrying in {interval}s...")

    logger.info("Proxy Bridge shut down")


def main():
    parser = argparse.ArgumentParser(
        description="Proxy Bridge — Transfer proxies from ProxyHarvester to YT API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # One-time sync
  python proxy_bridge.py

  # Continuous sync every 5 minutes
  python proxy_bridge.py --continuous

  # Continuous sync every 60 seconds
  python proxy_bridge.py --continuous --interval 60

  # Show version
  python proxy_bridge.py --version
        """,
    )

    parser.add_argument(
        "--continuous", "-c",
        action="store_true",
        help="Run continuously, watching for changes",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=300,
        help="Check interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--webshare-token", "-w",
        type=str,
        default=None,
        help="WebShare API token (or set WEBSHARE_API_TOKEN env var)",
    )
    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="Show version",
    )

    args = parser.parse_args()

    if args.version:
        print("Proxy Bridge v2.0.0 — with WebShare API support")
        sys.exit(0)

    # Override env token if provided via CLI
    global WEBSHARE_API_TOKEN
    if args.webshare_token:
        WEBSHARE_API_TOKEN = args.webshare_token

    if not WEBSHARE_API_TOKEN and not SCRAPER_JSON.exists():
        logger.warning("No WebShare token AND no scraper JSON found")
        logger.warning("Set WEBSHARE_API_TOKEN or run --webshare-token <token>")
        logger.warning("Or make sure proxyscrap/ is a sibling directory")
        if not args.continuous:
            sys.exit(1)

    logger.info(f"  WebShare API: {'✅ enabled' if WEBSHARE_API_TOKEN else '❌ disabled'}")
    logger.info(f"  ProxyScrap:   {'✅ available' if SCRAPER_JSON.exists() else '❌ not found'}")

    if args.continuous:
        run_continuous(interval=args.interval)
    else:
        total = sync_once()
        if total > 0:
            logger.info(f"\n✓ Done: {total} proxies synced to {PROXIES_DIR}/")
        else:
            logger.warning("\nNo proxies synced.")
            sys.exit(1)


if __name__ == "__main__":
    main()
