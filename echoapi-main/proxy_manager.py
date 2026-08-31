"""
Proxy Manager with automatic rotation, health checking, and speed-weighted selection
"""
import json
import random
import time
import logging
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


class ProxyManager:
    def __init__(self, proxy_dir: str = "proxies"):
        self.proxy_dir = Path(proxy_dir)
        self.working_dir = self.proxy_dir / "working"
        self.http_proxies: List[str] = []
        self.socks4_proxies: List[str] = []
        self.socks5_proxies: List[str] = []
        self.failed_proxies: set = set()
        self.last_load_time = 0
        self.reload_interval = 3600  # Reload proxies every hour

        # Speed data: proxy -> speed_seconds
        self.proxy_speeds: Dict[str, float] = {}

        self.load_proxies()

    def _load_speed_data(self) -> Dict[str, float]:
        """Load speed data from JSON files in the working directory."""
        speeds: Dict[str, float] = {}
        for ptype in ["http", "socks4", "socks5"]:
            speed_file = self.working_dir / f"{ptype}_speed.json"
            if speed_file.exists():
                try:
                    with open(speed_file, 'r') as f:
                        data = json.load(f)
                        for entry in data:
                            proxy_str = entry.get("proxy", "")
                            speed = entry.get("speed_seconds", 999)
                            if proxy_str:
                                # Store without protocol prefix for matching
                                speeds[proxy_str] = speed
                except Exception as e:
                    logger.warning(f"Failed to load speed data from {speed_file}: {e}")
        return speeds

    def _strip_protocol(self, proxy: str) -> str:
        """Strip protocol prefix for speed lookup."""
        for prefix in ["http://", "socks4://", "socks5://"]:
            if proxy.startswith(prefix):
                return proxy[len(prefix):]
        return proxy

    def _weighted_choice(self, proxies: List[str]) -> Optional[str]:
        """Pick a proxy using speed-weighted random selection.
        Faster proxies get picked more often."""
        if not proxies:
            return None

        # Filter out failed proxies
        available = [p for p in proxies if p not in self.failed_proxies]
        if not available:
            logger.warning("No available proxies, clearing failed list")
            self.failed_proxies.clear()
            available = proxies

        if not available:
            return None

        # If we have speed data, use weighted selection
        if self.proxy_speeds:
            weights = []
            for proxy in available:
                clean = self._strip_protocol(proxy)
                speed = self.proxy_speeds.get(clean)
                if speed is not None and speed > 0:
                    # Inverse weight: faster (lower time) = higher weight
                    # Use 1/speed^2 to heavily favor fast proxies
                    weight = 1.0 / (speed * speed)
                else:
                    # No speed data, give default medium weight
                    weight = 0.1
                weights.append(weight)

            return random.choices(available, weights=weights, k=1)[0]
        else:
            # No speed data, fall back to random
            return random.choice(available)

    def load_proxies(self):
        """Load proxies from files - prefer working proxies if available"""
        try:
            # Load speed data first (if available)
            self.proxy_speeds = self._load_speed_data()
            has_speed_data = bool(self.proxy_speeds)

            # Try to load from working directory first
            if self.working_dir.exists():
                http_file = self.working_dir / "http_working.txt"
                socks4_file = self.working_dir / "socks4_working.txt"
                socks5_file = self.working_dir / "socks5_working.txt"

                if http_file.exists() or socks4_file.exists() or socks5_file.exists():
                    logger.info("Loading TESTED working proxies...")

                    # Load working proxies
                    if http_file.exists():
                        with open(http_file, 'r') as f:
                            self.http_proxies = [
                                f"http://{line.strip()}"
                                for line in f
                                if line.strip() and not line.startswith('#')
                            ]

                    if socks4_file.exists():
                        with open(socks4_file, 'r') as f:
                            self.socks4_proxies = [
                                f"socks4://{line.strip()}"
                                for line in f
                                if line.strip() and not line.startswith('#')
                            ]

                    if socks5_file.exists():
                        with open(socks5_file, 'r') as f:
                            self.socks5_proxies = [
                                f"socks5://{line.strip()}"
                                for line in f
                                if line.strip() and not line.startswith('#')
                            ]

                    self.last_load_time = time.time()
                    total = len(self.http_proxies) + len(self.socks4_proxies) + len(self.socks5_proxies)

                    if total > 0:
                        logger.info(f"Loaded {total} WORKING speed-ranked proxies "
                                   f"(HTTP: {len(self.http_proxies)}, "
                                   f"SOCKS4: {len(self.socks4_proxies)}, "
                                   f"SOCKS5: {len(self.socks5_proxies)})")
                        if has_speed_data:
                            logger.info(f"✓ Speed data loaded for {len(self.proxy_speeds)} proxies "
                                       f"— will prefer fastest proxies")
                        return

            # Fallback to loading all proxies (untested)
            logger.warning("No working proxies found, loading ALL proxies (untested - may be slow!)")
            logger.warning("Run 'python proxy_checker.py' to test proxies first!")

            # Load HTTP proxies
            http_file = self.proxy_dir / "http.txt"
            if http_file.exists():
                with open(http_file, 'r') as f:
                    self.http_proxies = [
                        f"http://{line.strip()}"
                        for line in f
                        if line.strip() and not line.startswith('#')
                    ]

            # Load SOCKS4 proxies
            socks4_file = self.proxy_dir / "socks4.txt"
            if socks4_file.exists():
                with open(socks4_file, 'r') as f:
                    self.socks4_proxies = [
                        f"socks4://{line.strip()}"
                        for line in f
                        if line.strip() and not line.startswith('#')
                    ]

            # Load SOCKS5 proxies
            socks5_file = self.proxy_dir / "socks5.txt"
            if socks5_file.exists():
                with open(socks5_file, 'r') as f:
                    self.socks5_proxies = [
                        f"socks5://{line.strip()}"
                        for line in f
                        if line.strip() and not line.startswith('#')
                    ]

            self.last_load_time = time.time()
            total = len(self.http_proxies) + len(self.socks4_proxies) + len(self.socks5_proxies)
            logger.info(f"Loaded {total} proxies (HTTP: {len(self.http_proxies)}, "
                       f"SOCKS4: {len(self.socks4_proxies)}, SOCKS5: {len(self.socks5_proxies)})")

        except Exception as e:
            logger.error(f"Error loading proxies: {e}")

    def get_random_proxy(self, proxy_type: str = "any") -> Optional[str]:
        """Get a proxy using speed-weighted random selection (faster = more likely)."""
        # Reload proxies if needed
        if time.time() - self.last_load_time > self.reload_interval:
            self.load_proxies()

        # Select proxy pool
        if proxy_type == "http":
            pool = self.http_proxies
        elif proxy_type == "socks4":
            pool = self.socks4_proxies
        elif proxy_type == "socks5":
            pool = self.socks5_proxies
        else:  # any
            pool = self.http_proxies + self.socks4_proxies + self.socks5_proxies

        return self._weighted_choice(pool)

    def mark_failed(self, proxy: str):
        """Mark a proxy as failed"""
        self.failed_proxies.add(proxy)
        logger.debug(f"Marked proxy as failed: {proxy}")

        # If too many failed, clear the list
        if len(self.failed_proxies) > 100:
            logger.info("Clearing failed proxy list (too many failures)")
            self.failed_proxies.clear()

    def mark_success(self, proxy: str):
        """Mark a proxy as successful (remove from failed list)"""
        if proxy in self.failed_proxies:
            self.failed_proxies.remove(proxy)
            logger.debug(f"Proxy recovered: {proxy}")

    def get_stats(self) -> dict:
        """Get proxy statistics including speed data"""
        total = len(self.http_proxies) + len(self.socks4_proxies) + len(self.socks5_proxies)

        # Compute speed stats if available
        speed_stats = {}
        if self.proxy_speeds:
            speeds = list(self.proxy_speeds.values())
            if speeds:
                speed_stats = {
                    "min_speed_s": round(min(speeds), 3),
                    "avg_speed_s": round(sum(speeds) / len(speeds), 3),
                    "max_speed_s": round(max(speeds), 3),
                    "proxies_with_speed_data": len(speeds),
                }

        stats = {
            "total_proxies": total,
            "http_proxies": len(self.http_proxies),
            "socks4_proxies": len(self.socks4_proxies),
            "socks5_proxies": len(self.socks5_proxies),
            "failed_proxies": len(self.failed_proxies),
            "available_proxies": total - len(self.failed_proxies),
        }

        if speed_stats:
            stats["speed"] = speed_stats
            stats["selection_mode"] = "speed_weighted"
        else:
            stats["selection_mode"] = "random"

        return stats
