#!/usr/bin/env python3
"""
Proxy Health Check — Test all EchoAPI proxies and mark dead ones
Run this before starting EchoAPI to ensure clean proxy pool
"""

import asyncio
import aiohttp
import aiohttp_socks
import json
import os
import sys
from pathlib import Path

# EchoAPI proxy files
PROXY_DIR = Path(r"C:\Users\NAMAN\Desktop\MAINTENANCE\API\echoapi-main\echoapi-main\proxies\working")
SOCKS5_FILE = PROXY_DIR / "socks5_working.txt"

async def test_proxy(proxy_str: str) -> dict:
    """Test a single proxy against YouTube"""
    # Parse proxy: socks5://user:pass@ip:port or socks5://ip:port
    if not proxy_str.startswith(("http://", "socks4://", "socks5://")):
        return {"proxy": proxy_str, "working": False, "error": "Invalid format"}
    
    connector = aiohttp_socks.ProxyConnector.from_url(proxy_str)
    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            start = asyncio.get_event_loop().time()
            async with session.get("https://www.youtube.com/embed/dQw4w9WgXcQ") as resp:
                text = await resp.text()
                elapsed = (asyncio.get_event_loop().time() - start) * 1000
                
                if resp.status == 200 and ("youtube" in text.lower() or "video" in text.lower()):
                    return {"proxy": proxy_str, "working": True, "latency_ms": round(elapsed, 1)}
                else:
                    return {"proxy": proxy_str, "working": False, "error": f"HTTP {resp.status}"}
    except asyncio.TimeoutError:
        return {"proxy": proxy_str, "working": False, "error": "Timeout"}
    except Exception as e:
        return {"proxy": proxy_str, "working": False, "error": str(e)[:100]}

async def main():
    print("=" * 60)
    print("EchoAPI Proxy Health Check")
    print("=" * 60)
    
    # Read proxies
    if not SOCKS5_FILE.exists():
        print(f"❌ {SOCKS5_FILE} not found")
        return
    
    with open(SOCKS5_FILE, 'r') as f:
        proxies = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    print(f"Testing {len(proxies)} SOCKS5 proxies...")
    print()
    
    # Test all proxies concurrently (limited)
    semaphore = asyncio.Semaphore(10)
    
    async def limited_test(p):
        async with semaphore:
            return await test_proxy(p)
    
    tasks = [limited_test(p) for p in proxies]
    results = await asyncio.gather(*tasks)
    
    # Separate working/dead
    working = [r for r in results if r["working"]]
    dead = [r for r in results if not r["working"]]
    
    # Sort working by latency
    working.sort(key=lambda x: x["latency_ms"])
    
    print(f"✅ WORKING: {len(working)}")
    print(f"❌ DEAD: {len(dead)}")
    print()
    
    if working:
        print("Top 10 fastest:")
        for i, w in enumerate(working[:10], 1):
            print(f"  {i}. {w['proxy']} — {w['latency_ms']}ms")
    print()
    
    if dead:
        print("Dead proxies (sample):")
        for d in dead[:5]:
            print(f"  {d['proxy']} — {d['error']}")
        if len(dead) > 5:
            print(f"  ... and {len(dead) - 5} more")
    print()
    
    # Update socks5_working.txt with only working proxies (fastest first)
    if working:
        with open(SOCKS5_FILE, 'w') as f:
            for w in working:
                f.write(w["proxy"] + "\n")
        print(f"✅ Updated {SOCKS5_FILE} with {len(working)} working proxies (speed-sorted)")
    
    # Also update speed.json
    speed_file = PROXY_DIR / "socks5_speed.json"
    speed_data = []
    for w in working:
        ip_port = w["proxy"].replace("socks5://", "")
        speed_data.append({
            "proxy": ip_port,
            "speed_seconds": round(w["latency_ms"] / 1000, 3),
            "protocol": "socks5"
        })
    speed_data.sort(key=lambda x: x["speed_seconds"])
    speed_data = speed_data[:30]  # Keep top 30
    
    with open(speed_file, 'w') as f:
        json.dump(speed_data, f, indent=2)
    print(f"✅ Updated {speed_file} with top {len(speed_data)} proxies")
    
    print()
    print("=" * 60)
    print("Health check complete. Restart EchoAPI to apply changes.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())