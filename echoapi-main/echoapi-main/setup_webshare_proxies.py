#!/usr/bin/env python3
"""
Process WebShare proxies into the Echo API format.

WebShare format:  ip:port:username:password
API format:       proxies/working/http_working.txt  → user:pass@host:port
                  proxies/working/http_speed.json   → {"proxy": "user:pass@host:port", "speed_seconds": ..., "protocol": "http"}
"""
import json
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
WORKING_DIR = SCRIPT_DIR / "proxies" / "working"
RAW_DIR = SCRIPT_DIR / "proxies"

# WebShare proxy data (test results with actual speeds)
PROXIES = [
    {"host": "198.105.121.200", "port": 6462, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 4829},
    {"host": "45.38.107.97",    "port": 6014, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 5359},
    {"host": "31.58.9.4",       "port": 6077, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 5375},
    {"host": "142.111.67.146",  "port": 5611, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 5375},
    {"host": "64.137.96.74",    "port": 6641, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 5468},
    {"host": "84.247.60.125",   "port": 6095, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 5719},
    {"host": "198.23.243.226",  "port": 6361, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 6937},
    {"host": "191.96.254.138",  "port": 6185, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 7297},
    {"host": "38.154.185.97",   "port": 6370, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 8047},
    {"host": "31.59.20.176",    "port": 6754, "user": "ntkyocsk", "pass": "1ojbl8d6jcam", "speed_ms": 8375},
]


def proxy_auth_str(p: dict) -> str:
    """Build user:pass@host:port for ProxyManager"""
    return f"{p['user']}:{p['pass']}@{p['host']}:{p['port']}"


def proxy_plain_str(p: dict) -> str:
    """Build host:port for fallback"""
    return f"{p['host']}:{p['port']}"


def main():
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Sort by speed (fastest first)
    proxies = sorted(PROXIES, key=lambda p: p["speed_ms"])

    # ── Write http_working.txt (auth format for ProxyManager) ──
    working_file = WORKING_DIR / "http_working.txt"
    with open(working_file, "w") as f:
        for p in proxies:
            f.write(f"{proxy_auth_str(p)}\n")
    print(f"✅ {working_file.name} → {len(proxies)} proxies (auth format)")

    # ── Write http_speed.json ──
    speed_data = []
    for p in proxies:
        speed_data.append({
            "proxy": proxy_auth_str(p),
            "speed_seconds": round(p["speed_ms"] / 1000.0, 3),
            "protocol": "http",
        })

    speed_file = WORKING_DIR / "http_speed.json"
    with open(speed_file, "w") as f:
        json.dump(speed_data, f, indent=2)
    print(f"✅ {speed_file.name} → {len(speed_data)} entries")

    # ── Write http.txt (raw fallback) ──
    raw_file = RAW_DIR / "http.txt"
    with open(raw_file, "w") as f:
        for p in proxies:
            f.write(f"{proxy_auth_str(p)}\n")
    print(f"✅ {raw_file.name} → {len(proxies)} proxies (raw fallback)")

    # ── Remove socks files if any exist (WebShare only has HTTP) ──
    for fname in ["socks4_working.txt", "socks5_working.txt",
                   "socks4_speed.json", "socks5_speed.json",
                   "socks4.txt", "socks5.txt"]:
        for d in [WORKING_DIR, RAW_DIR]:
            fpath = d / fname
            if fpath.exists():
                fpath.unlink()
                print(f"🗑  Removed {fpath}")

    # ── Summary ──
    print()
    print("=" * 60)
    print(f"  ✅ Done! {len(proxies)} WebShare proxies synced")
    print(f"  📁 Output: {WORKING_DIR}/")
    print(f"  ⚡ Fastest: {proxies[0]['host']}:{proxies[0]['port']} ({proxies[0]['speed_ms']}ms)")
    print(f"  🐌 Slowest: {proxies[-1]['host']}:{proxies[-1]['port']} ({proxies[-1]['speed_ms']}ms)")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Set USE_PROXIES=true in your .env or environment")
    print("  2. Restart your Echo API")
    print("  3. Test: curl http://13.204.45.5:8000/metrics")


if __name__ == "__main__":
    main()
