"""
Background proxy checker - Tests proxies, measures speed, saves only the fastest
"""
import asyncio
import aiohttp
import json
import time
import logging
from pathlib import Path
from typing import List, Set, Dict, Tuple, Optional
import random

logger = logging.getLogger(__name__)


class ProxyChecker:
    def __init__(self, proxy_dir: str = "proxies", output_dir: str = "proxies/working"):
        self.proxy_dir = Path(proxy_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Test configuration
        self.test_url = "https://www.youtube.com"
        self.timeout = 10  # seconds per proxy
        self.batch_size = 50  # Test 50 proxies at a time
        self.check_interval = 3600  # Check every hour

        # Speed filtering
        self.max_proxies_per_type = 30  # Keep only top 30 fastest per type
        self.slow_threshold_seconds = 5.0  # Discard proxies slower than 5s

        self.working_proxies: Set[str] = set()
        self.is_running = False

    async def test_proxy_speed(self, proxy: str) -> Tuple[bool, float]:
        """Test if a proxy works and measure its response time in seconds.
        Returns (working, response_time_seconds)."""
        start = time.monotonic()
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=self.timeout)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(self.test_url, proxy=proxy) as response:
                    elapsed = time.monotonic() - start
                    if response.status == 200:
                        logger.debug(f"✓ Working proxy: {proxy} ({elapsed:.2f}s)")
                        return True, elapsed
                    else:
                        logger.debug(f"✗ Bad status {response.status}: {proxy}")
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.debug(f"✗ Failed proxy: {proxy} - {type(e).__name__} ({elapsed:.2f}s)")

        return False, 0.0

    async def test_batch(self, proxies: List[str]) -> List[Tuple[str, float]]:
        """Test a batch of proxies concurrently and return (proxy, speed) for working ones."""
        tasks = [self.test_proxy_speed(proxy) for proxy in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        working_with_speed = []
        for proxy, result in zip(proxies, results):
            if isinstance(result, tuple) and result[0] is True:
                working_with_speed.append((proxy, result[1]))

        return working_with_speed

    def load_proxies(self, filename: str) -> List[str]:
        """Load proxies from file"""
        filepath = self.proxy_dir / filename
        if not filepath.exists():
            return []

        proxies = []
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    proxies.append(line)

        return proxies

    def save_working_proxies_speed_ranked(self, proxies_with_speed: List[Tuple[str, float]], proxy_type: str):
        """Save working proxies ranked by speed (fastest first), keeping only the fastest."""
        if not proxies_with_speed:
            logger.warning(f"No working proxies for {proxy_type}")
            return

        # Sort by speed (fastest first)
        sorted_proxies = sorted(proxies_with_speed, key=lambda x: x[1])

        # Filter out slow proxies
        fast_proxies = [(p, s) for p, s in sorted_proxies if s <= self.slow_threshold_seconds]

        if not fast_proxies:
            logger.warning(f"All {proxy_type} proxies are slower than {self.slow_threshold_seconds}s threshold! "
                           f"Accepting top {self.max_proxies_per_type} anyway.")
            fast_proxies = sorted_proxies[:self.max_proxies_per_type]
        else:
            # Keep only top N fastest
            fast_proxies = fast_proxies[:self.max_proxies_per_type]

        # Save ranked text file (fastest first, no protocol prefix)
        clean_proxies = [p.split('://')[-1] for p, _ in fast_proxies]
        output_file = self.output_dir / f"{proxy_type}_working.txt"
        with open(output_file, 'w') as f:
            for proxy in clean_proxies:
                f.write(f"{proxy}\n")

        # Save speed data as JSON for the proxy manager
        speed_data = []
        for proxy, speed in fast_proxies:
            clean = proxy.split('://')[-1]
            speed_data.append({
                "proxy": clean,
                "speed_seconds": round(speed, 3),
                "protocol": proxy_type,
            })

        speed_file = self.output_dir / f"{proxy_type}_speed.json"
        with open(speed_file, 'w') as f:
            json.dump(speed_data, f, indent=2)

        logger.info(f"✓ Saved top {len(fast_proxies)} fastest {proxy_type} proxies (fastest: {fast_proxies[0][1]:.3f}s, "
                    f"slowest kept: {fast_proxies[-1][1]:.3f}s)")
        
        # Log the speed distribution
        speeds = [s for _, s in fast_proxies]
        if speeds:
            avg_speed = sum(speeds) / len(speeds)
            logger.info(f"  {proxy_type} speed stats — avg: {avg_speed:.3f}s, "
                        f"min: {min(speeds):.3f}s, max: {max(speeds):.3f}s, "
                        f"median: {sorted(speeds)[len(speeds)//2]:.3f}s")

    async def check_proxy_type(self, proxy_type: str, filename: str):
        """Check all proxies of a specific type, rank by speed, save fastest only."""
        logger.info(f"Checking {proxy_type} proxies from {filename}...")

        # Load raw proxies
        raw_proxies = self.load_proxies(filename)
        if not raw_proxies:
            logger.warning(f"No proxies found in {filename}")
            return

        logger.info(f"Loaded {len(raw_proxies)} {proxy_type} proxies, testing speed...")

        # Add protocol prefix
        if proxy_type == "http":
            proxies = [f"http://{p}" if not p.startswith('http') else p for p in raw_proxies]
        elif proxy_type == "socks4":
            proxies = [f"socks4://{p}" if not p.startswith('socks4') else p for p in raw_proxies]
        elif proxy_type == "socks5":
            proxies = [f"socks5://{p}" if not p.startswith('socks5') else p for p in raw_proxies]
        else:
            proxies = raw_proxies

        # Shuffle for random testing
        random.shuffle(proxies)

        # Test in batches, tracking speed
        all_working_with_speed: List[Tuple[str, float]] = []
        total = len(proxies)

        for i in range(0, total, self.batch_size):
            batch = proxies[i:i + self.batch_size]
            batch_results = await self.test_batch(batch)
            all_working_with_speed.extend(batch_results)

            progress = min(i + self.batch_size, total)
            logger.info(f"Progress: {progress}/{total} tested, {len(all_working_with_speed)} working so far...")

            # Small delay between batches
            await asyncio.sleep(0.5)

        # Save speed-ranked proxies (fastest only)
        self.save_working_proxies_speed_ranked(all_working_with_speed, proxy_type)

        logger.info(f"✓ {proxy_type}: {len(all_working_with_speed)}/{total} proxies working "
                    f"({len(all_working_with_speed)/total*100:.1f}% success rate)")

        return all_working_with_speed

    async def check_all_proxies(self):
        """Check all proxy types"""
        logger.info("=" * 50)
        logger.info("Starting speed-ranked proxy check...")
        logger.info("=" * 50)

        start_time = time.time()

        # Check each proxy type
        http_results = await self.check_proxy_type("http", "http.txt")
        socks4_results = await self.check_proxy_type("socks4", "socks4.txt")
        socks5_results = await self.check_proxy_type("socks5", "socks5.txt")

        elapsed = time.time() - start_time

        # Load the saved JSON speed files to report
        speed_files = {
            "http": self.output_dir / "http_speed.json",
            "socks4": self.output_dir / "socks4_speed.json",
            "socks5": self.output_dir / "socks5_speed.json",
        }

        total_kept = 0
        for ptype, sfile in speed_files.items():
            if sfile.exists():
                with open(sfile, 'r') as f:
                    data = json.load(f)
                    total_kept += len(data)

        total_working = len(http_results or []) + len(socks4_results or []) + len(socks5_results or [])

        logger.info("=" * 50)
        logger.info(f"✓ Speed-ranked proxy check completed in {elapsed:.1f}s")
        logger.info(f"  Total WORKING: {total_working} | FASTEST kept: {total_kept}")
        logger.info(f"  (Keeping only top {self.max_proxies_per_type} fastest per type, "
                    f"under {self.slow_threshold_seconds}s)")
        if total_working > 0:
            logger.info(f"  Filtered out {total_working - total_kept} slow proxies "
                        f"({(total_working - total_kept)/total_working*100:.0f}% reduction)")
        logger.info(f"  Speed data saved to: {self.output_dir}/*_speed.json")
        logger.info("=" * 50)

    async def run_continuous(self):
        """Run proxy checker continuously in background"""
        self.is_running = True
        logger.info(f"Proxy checker started (checking every {self.check_interval}s)")

        while self.is_running:
            try:
                await self.check_all_proxies()
                logger.info(f"Next check in {self.check_interval}s...")
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in proxy checker: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error

    def stop(self):
        """Stop the proxy checker"""
        self.is_running = False
        logger.info("Proxy checker stopped")


async def main():
    """Standalone proxy checker"""
    checker = ProxyChecker()
    await checker.check_all_proxies()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
