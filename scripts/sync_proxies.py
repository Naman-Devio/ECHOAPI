#!/usr/bin/env python3
"""
Proxy Sync Script — Automatically connects ProxyHarvester to EchoAPI

This script runs every 30 minutes (via cron) and:
1. Reads fresh proxies from ProxyHarvester's working_proxies.json
2. Re-ranks them by speed (fastest first, weighted like proxy_manager.py)
3. Writes all 6 EchoAPI proxy files
4. Ensures API stays responsive with fresh proxy pool

Usage:
    python sync_proxies.py       # One-shot run
    # Or add to cron: 0,30 * * * * python C:\path\sync_proxies.py

Author: Zero (Hermes Agent)
"""

import json
import os
import random
import time
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# ══════════════════════════════════════════════════════════
# CONFIGURATION — Adjust these paths for your setup
# ══════════════════════════════════════════════════════════

# ProxyHarvester output (where it saves working_proxies.json)
PROXY_HARVESTER_POOL = Path(
    r"C:\Users\NAMAN\Desktop\MAINTENANCE\API\echoapi-main\proxyscrap\proxy_pool\working_proxies.json"
)

# EchoAPI proxy input directory (where proxy_manager reads from)
ECHOAPI_PROXIES_DIR = Path(
    r"C:\Users\NAMAN\Desktop\MAINTENANCE\API\echoapi-main\echoapi-main\proxies\working"
)

# Output files to write (6 files total)
OUTPUT_FILES = {
    "http_speed": ECHOAPI_PROXIES_DIR / "http_speed.json",
    "http_working": ECHOAPI_PROXIES_DIR / "http_working.txt",
    "socks4_speed": ECHOAPI_PROXIES_DIR / "socks4_speed.json",
    "socks4_working": ECHOAPI_PROXIES_DIR / "socks4_working.txt",
    "socks5_speed": ECHOAPI_PROXIES_DIR / "socks5_speed.json",
    "socks5_working": ECHOAPI_PROXIES_DIR / "socks5_working.txt",
}

# Speed ranking config (must match proxy_manager.py: 1/speed² weighting)
MIN_LATENCY_MS = 100    # Minimum acceptable latency (proxies slower pruned)
MAX_LATENCY_MS = 15000  # Maximum acceptable latency before pruning
SPEED_WEIGHT_POWER = 2  # Weighting: 1/speed^power (2 = inverse square)


# ══════════════════════════════════════════════════════════
# CORE SYNC LOGIC
# ══════════════════════════════════════════════════════════

def load_harvester_proxies(pool_path: Path) -> List[Dict]:
    """Load working proxies from ProxyHarvester's working_proxies.json."""
    try:
        with open(pool_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "proxies" in data:
            return data["proxies"]
        else:
            print(f"⚠ Unexpected format in {pool_path}, expecting list or {{'proxies': [...]}}")
            return []
    except FileNotFoundError:
        print(f"❌ Error: ProxyHarvester pool not found at {pool_path}")
        print("   Run ProxyHarvester first, or check the path.")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ Error: Failed to parse JSON from {pool_path}: {e}")
        return []


def rank_by_speed(proxies: List[Dict], power: float = SPEED_WEIGHT_POWER) -> List[Dict]:
    """
    Rank proxies by speed using 1/speed^power weighting.
    Faster proxies get higher weight.
    Matches proxy_manager.py logic: weight = 1.0 / (speed * speed)
    """
    # Filter proxies within acceptable latency range
    valid_proxies = []
    for p in proxies:
        latency_ms = p.get("latency_ms", 9999)
        speed_seconds = latency_ms / 1000.0
        
        # Filter: prune proxies slower than MAX_LATENCY_MS
        if latency_ms > MAX_LATENCY_MS:
            continue  # Too slow - skip
        
        # Weighting: 1/speed^power (faster = higher weight)
        if latency_ms > 0:
            weight = 1.0 / (latency_ms ** power)
        else:
            weight = 999999  # Extremely fast, give max weight
        
        # Format proxy string: IP:PORT (no protocol prefix for proxy_manager working.txt)
        proxy_ip_port = f"{p.get('host', '')}:{p.get('port', '')}"
        
        valid_proxies.append({
            "host": p.get("host", ""),
            "port": p.get("port", 0),
            "protocol": p.get("protocol", "http").lower(),
            "_weight": weight,
            "_latency_ms": latency_ms,
            "_proxy_ip_port": proxy_ip_port,
        })
    
    # Group by protocol and cap each (like proxy_manager: max 30 per type)
    proto_groups = {"http": [], "socks4": [], "socks5": []}
    for p in valid_proxies:
        proto = p["protocol"]
        if proto in proto_groups:
            proto_groups[proto].append(p)
    
    # Take top 30 from each protocol (proxy_manager default)
    result = []
    for proto in ["http", "socks4", "socks5"]:
        group = proto_groups[proto]
        result.extend(group[:30])
    
    # Re-sort all selected by weight (fastest first)
    result.sort(key=lambda x: x["_weight"], reverse=True)
    
    return result


def write_proxy_files(ranked_proxies: List[Dict], output_dir: Path):
    """Write all 6 EchoAPI proxy files from ranked proxies."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Group by protocol
    proto_groups = {"http": [], "socks4": [], "socks5": []}
    for p in ranked_proxies:
        proto = p["protocol"]
        if proto in proto_groups:
            proto_groups[proto].append(p)
    
    # 1. http_speed.json - speed-ranked data for proxy_manager
    http_proxies = proto_groups["http"]
    speed_data = []
    for p in http_proxies:
        latency_ms = p["_latency_ms"]
        speed_data.append({
            "proxy": p["_proxy_ip_port"],
            "speed_seconds": round(p["_latency_ms"] / 1000.0, 3) if p["_latency_ms"] > 0 else 0.1,
            "protocol": "http",
        })
    speed_data.sort(key=lambda x: x["speed_seconds"])
    with open(OUTPUT_FILES["http_speed"], "w", encoding="utf-8") as f:
        json.dump(speed_data, f, indent=2)
    
    # 2. http_working.txt - IP:PORT format (for proxy_manager http_proxies)
    # proxy_manager prepends "http://" when loading, so just write IP:PORT
    with open(OUTPUT_FILES["http_working"], "w", encoding="utf-8") as f:
        for p in http_proxies:
            f.write(p["_proxy_ip_port"] + "\n")
    
    # 3. socks4_speed.json
    socks4_proxies = proto_groups["socks4"]
    speed_data = []
    for p in socks4_proxies:
        latency_ms = p["_latency_ms"]
        speed_data.append({
            "proxy": p["_proxy_ip_port"],
            "speed_seconds": round(p["_latency_ms"] / 1000.0, 3) if p["_latency_ms"] > 0 else 0.1,
            "protocol": "socks4",
        })
    speed_data.sort(key=lambda x: x["speed_seconds"])
    with open(OUTPUT_FILES["socks4_speed"], "w", encoding="utf-8") as f:
        json.dump(speed_data, f, indent=2)
    
    # 4. socks4_working.txt - socks4:// prefix format
    with open(OUTPUT_FILES["socks4_working"], "w", encoding="utf-8") as f:
        for p in socks4_proxies:
            f.write("socks4://" + p["_proxy_ip_port"] + "\n")
    
    # 5. socks5_speed.json
    socks5_proxies = proto_groups["socks5"]
    speed_data = []
    for p in socks5_proxies:
        latency_ms = p["_latency_ms"]
        speed_data.append({
            "proxy": p["_proxy_ip_port"],
            "speed_seconds": round(p["_latency_ms"] / 1000.0, 3) if p["_latency_ms"] > 0 else 0.1,
            "protocol": "socks5",
        })
    speed_data.sort(key=lambda x: x["speed_seconds"])
    with open(OUTPUT_FILES["socks5_speed"], "w", encoding="utf-8") as f:
        json.dump(speed_data, f, indent=2)
    
    # 6. socks5_working.txt - socks5:// prefix format
    with open(OUTPUT_FILES["socks5_working"], "w", encoding="utf-8") as f:
        for p in socks5_proxies:
            f.write("socks5://" + p["_proxy_ip_port"] + "\n")
    
    total_proxies = sum(len(g) for g in proto_groups.values())
    print(f"✅ Synced {total_proxies} proxies to EchoAPI")
    print(f"   HTTP: {len(http_proxies)} proxies")
    print(f"   SOCKS4: {len(socks4_proxies)} proxies")
    print(f"   SOCKS5: {len(socks5_proxies)} proxies")
    
    # Report speed stats per protocol
    for proto in ["http", "socks4", "socks5"]:
        proxies = proto_groups[proto]
        if proxies:
            speeds = [p["_latency_ms"] for p in proxies]
            print(f"   {proto.upper()} speed: avg {sum(speeds)/len(speeds):.1f}ms, "
                  f"fastest {min(speeds):.1f}ms, kept top {len(proxies)}")


# ══════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Proxy Sync — ProxyHarvester → EchoAPI")
    print("=" * 60)
    print()
    
    # Step 1: Load from ProxyHarvester
    print(f"📥 Loading proxies from ProxyHarvester pool...")
    proxies = load_harvester_proxies(PROXY_HARVESTER_POOL)
    if not proxies:
        print("❌ No proxies loaded. Aborting.")
        sys.exit(1)
    print(f"   Loaded {len(proxies)} proxies total")
    print()
    
    # Step 2: Rank by speed
    print(f"⚡ Ranking proxies by speed (1/speed^{SPEED_WEIGHT_POWER} weighting)...")
    ranked = rank_by_speed(proxies, SPEED_WEIGHT_POWER)
    passed = len(ranked)
    total = len(proxies)
    print(f"   {passed}/{total} proxies passed speed filter (< {MAX_LATENCY_MS}ms)")
    print()
    
    # Step 3: Write EchoAPI files
    print(f"📤 Writing {len(OUTPUT_FILES)} proxy files to EchoAPI...")
    print()
    write_proxy_files(ranked, ECHOAPI_PROXIES_DIR)
    print()
    
    # Step 4: Verification
    print(f"✅ Verification:")
    print(f"   Check EchoAPI metrics endpoint after restart:")
    print(f"   curl http://localhost:8000/metrics")
    print()
    print(f"   Set USE_PROXIES=true in .env to enable proxy rotation")
    print(f"   Proxy manager uses 1/speed² weighting - fastest proxies picked first")
    
    print()
    print("=" * 60)
    print("Sync complete! Run 'python main.py' to apply changes.")
    print("=" * 60)


if __name__ == "__main__":
    main()