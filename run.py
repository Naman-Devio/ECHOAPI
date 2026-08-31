#!/usr/bin/env python3
"""
UNIFIED LAUNCHER — ProxyHarvester + EchoAPI Integration
=====================================================

This script orchestrates both systems for maximum YouTube API performance:
  • ProxyHarvester (proxyscrap) - Continuously scrapes & validates fastest proxies
  • Proxy Bridge - Syncs fresh proxies from harvester → EchoAPI
  • EchoAPI (main.py) - High-performance YouTube API with proxy rotation

Features:
  • Auto-starts all three services in correct dependency order
  • Process monitoring with auto-restart on failure
  • Unified logging with colored output
  • Graceful shutdown handling (Ctrl+C)
  • Health checks and metrics endpoint
  • Configurable via environment variables or command line

Usage:
    python run.py                    # Start all services
    python run.py --api-only         # Start EchoAPI only (uses existing proxies)
    python run.py --harvester-only   # Start ProxyHarvester only
    python run.py --bridge-only      # Start proxy bridge only
    python run.py --help             # Show help

Environment Variables:
    PROXY_SCRAPE_INTERVAL    Seconds between proxy scraping (default: 300)
    API_PORT                 EchoAPI port (default: 8000)
    HARVESTER_API_PORT       ProxyHarvester API port (default: 8080)
    FORWARDER_PORT           Proxy forwarder port (default: 8081)
    USE_PROXIES              Enable/disable proxies in EchoAPI (default: true)
    LOG_LEVEL                Logging level (default: INFO)

Example:
    PROXY_SCRAPE_INTERVAL=60 API_PORT=8080 python run.py
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Dict, List, Optional
import subprocess
import threading

# Add project directories to path
BASE_DIR = Path(__file__).parent.resolve()
ECHOAPI_DIR = BASE_DIR / "echoapi-main"
PROXY_SCRAPE_DIR = BASE_DIR / "proxyscrap"

sys.path.insert(0, str(ECHOAPI_DIR))
sys.path.insert(0, str(PROXY_SCRAPE_DIR))

# Configure logging with colors
class ColorFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)

# Apply color formatter to console
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColorFormatter('%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s'))
logging.getLogger().handlers = [console_handler]

logger = logging.getLogger("UnifiedLauncher")

# Service configuration
SERVICES = {
    "harvester": {
        "name": "ProxyHarvester",
        "script": PROXY_SCRAPE_DIR / "main.py",
        "args": [],
        "env": {},
        "cwd": PROXY_SCRAPE_DIR,
        "process": None,
        "restart_count": 0,
        "max_restarts": 5,
    },
    "bridge": {
        "name": "Proxy Bridge",
        "script": ECHOAPI_DIR / "proxy_bridge.py",
        "args": ["--continuous"],
        "env": {},
        "cwd": ECHOAPI_DIR,
        "process": None,
        "restart_count": 0,
        "max_restarts": 5,
    },
    "api": {
        "name": "EchoAPI",
        "script": ECHOAPI_DIR / "main.py",
        "args": [],
        "env": {
            "USE_PROXIES": "true",
            "ENABLE_PROXY_CHECKER": "true",
        },
        "cwd": ECHOAPI_DIR,
        "process": None,
        "restart_count": 0,
        "max_restarts": 5,
    }
}

# Global state
shutdown_event = asyncio.Event()
service_tasks: Dict[str, asyncio.Task] = {}


def setup_service_env(service_key: str, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Setup environment variables for a service."""
    env = os.environ.copy()
    env.update(SERVICES[service_key]["env"])
    if extra_env:
        env.update(extra_env)
    return env


async def monitor_service(service_key: str):
    """Monitor a service process and auto-restart if needed."""
    service = SERVICES[service_key]
    logger.info(f"🔍 Starting monitor for {service['name']}")

    while not shutdown_event.is_set():
        try:
            # Check if process exists and is still running
            if service["process"] is None:
                await start_service(service_key)
            elif service["process"].poll() is not None:
                # Process has terminated
                return_code = service["process"].returncode
                logger.warning(f"⚠️  {service['name']} exited with code {return_code}")

                # Check if we should restart
                if service["restart_count"] < service["max_restarts"] and not shutdown_event.is_set():
                    service["restart_count"] += 1
                    delay = min(2 ** service["restart_count"], 30)  # Exponential backoff, max 30s
                    logger.info(f"🔄 Restarting {service['name']} in {delay}s (attempt {service['restart_count']}/{service['max_restarts']})")
                    await asyncio.sleep(delay)
                    await start_service(service_key)
                else:
                    logger.error(f"❌ {service['name']} failed permanently or shutdown requested")
                    break

            # Check every 5 seconds
            await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"💥 Error monitoring {service['name']}: {e}")
            await asyncio.sleep(5)


async def start_service(service_key: str):
    """Start a service process."""
    service = SERVICES[service_key]

    if not service["script"].exists():
        logger.error(f"❌ Script not found: {service['script']}")
        return

    # Build command
    cmd = [sys.executable, str(service["script"])] + service["args"]
    env = setup_service_env(service_key)

    logger.info(f"🚀 Starting {service['name']}: {' '.join(cmd)}")

    try:
        # Create process with pipes for output
        service["process"] = subprocess.Popen(
            cmd,
            cwd=str(service["cwd"]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Combine stderr with stdout
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Start output reader thread
        def read_output():
            for line in iter(service["process"].stdout.readline, ''):
                if line:
                    # Prefix with service name for clarity
                    prefix = f"[{service['name']}] "
                    print(prefix + line.rstrip())

                if shutdown_event.is_set():
                    break

        output_thread = threading.Thread(target=read_output, daemon=True)
        output_thread.start()

        logger.info(f"✅ {service['name']} started (PID: {service['process'].pid})")

    except Exception as e:
        logger.error(f"❌ Failed to start {service['name']}: {e}")
        service["process"] = None


async def stop_service(service_key: str):
    """Stop a service gracefully."""
    service = SERVICES[service_key]
    if service["process"] and service["process"].poll() is None:
        logger.info(f"🛑 Stopping {service['name']}...")
        service["process"].terminate()

        # Wait for graceful shutdown
        try:
            service["process"].wait(timeout=10)
            logger.info(f"✅ {service['name']} stopped")
        except subprocess.TimeoutExpired:
            logger.warning(f"⚠️  {service['name']} didn't stop gracefully, forcing...")
            service["process"].kill()
            service["process"].wait()
            logger.info(f"💥 {service['name']} force-killed")

    service["process"] = None


async def start_all_services(enabled_services: List[str]):
    """Start all specified services."""
    logger.info("🎯 Starting services...")

    for service_key in enabled_services:
        if service_key in SERVICES:
            await start_service(service_key)
            # Small delay between starts to avoid port conflicts
            await asyncio.sleep(2)

    # Start monitoring tasks
    for service_key in enabled_services:
        if service_key in SERVICES:
            task = asyncio.create_task(monitor_service(service_key))
            service_tasks[service_key] = task

    logger.info("✅ All services started and monitoring")


async def stop_all_services():
    """Stop all services."""
    logger.info("🛑 Stopping all services...")
    shutdown_event.set()

    # Stop monitoring tasks
    for task in service_tasks.values():
        if not task.done():
            task.cancel()

    # Wait for monitoring tasks to complete
    if service_tasks:
        await asyncio.gather(*service_tasks.values(), return_exceptions=True)

    # Stop services in reverse order (API first, then bridge, then harvester)
    for service_key in ["api", "bridge", "harvester"]:
        if service_key in SERVICES:
            await stop_service(service_key)

    logger.info("✅ All services stopped")


def print_banner():
    """Print startup banner."""
    banner = """
    ╔════════════════════════════════════════════════════════════════════════════╗
    ║                                                                              ║
    ║     ███╗   ███╗ █████╗ ████████╗██╗ ██████╗ ███╗   ██╗███████╗              ║
    ║     ████╗ ████║██╔══██╗╚══██╔══╝██║██╔═══██╗████╗  ██║██╔════╝              ║
    ║     ██╔████╔██║███████║   ██║   ██║██║   ██║██╔██╗ ██║█████╗               ║
    ║     ██║╚██╔╝██║██╔══██║   ██║   ██║██║   ██║██║╚██╗██║██╔══╝               ║
    ║     ██║ ╚═╝ ██║██║  ██║   ██║   ██║╚██████╔╝██║ ╚████║███████╗              ║
    ║     ╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝              ║
    ║                                                                              ║
    ║              ProxyHarvester + EchoAPI Unified Launcher                      ║
    ║                                                                              ║
    ║  🚀 Fastest proxies + YouTube API = Blazing fast downloads                  ║
    ║                                                                              ║
    ╚════════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_help():
    """Print help message."""
    print("""
UNIFIED LAUNCHER — ProxyHarvester + EchoAPI Integration

Usage:
    python run.py [OPTIONS]

Options:
    --api-only              Start EchoAPI only (uses existing proxies)
    --harvester-only        Start ProxyHarvester only
    --bridge-only           Start proxy bridge only
    --help, -h              Show this help message

Environment Variables:
    PROXY_SCRAPE_INTERVAL   Seconds between proxy scraping (default: 300)
    API_PORT                EchoAPI port (default: 8000)
    HARVESTER_API_PORT      ProxyHarvester API port (default: 8080)
    FORWARDER_PORT          Proxy forwarder port (default: 8081)
    USE_PROXIES             Enable/disable proxies in EchoAPI (default: true)
    LOG_LEVEL               Logging level (default: INFO)

Examples:
    python run.py                           # Start all services
    PROXY_SCRAPE_INTERVAL=60 python run.py  # Scrape proxies every 60s
    API_PORT=8080 python run.py             # Run EchoAPI on port 8080
""")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Unified Launcher for ProxyHarvester + EchoAPI", add_help=False)
    parser.add_argument("--api-only", action="store_true", help="Start EchoAPI only")
    parser.add_argument("--harvester-only", action="store_true", help="Start ProxyHarvester only")
    parser.add_argument("--bridge-only", action="store_true", help="Start proxy bridge only")
    parser.add_argument("-h", "--help", action="store_true", help="Show help")

    args = parser.parse_args()

    if args.help:
        print_help()
        return

    print_banner()

    # Determine which services to start
    if args.api_only:
        enabled_services = ["api"]
        logger.info("🎯 Mode: API only")
    elif args.harvester_only:
        enabled_services = ["harvester"]
        logger.info("🎯 Mode: Harvester only")
    elif args.bridge_only:
        enabled_services = ["bridge"]
        logger.info("🎯 Mode: Bridge only")
    else:
        enabled_services = ["harvester", "bridge", "api"]
        logger.info("🎯 Mode: Full stack (Harvester → Bridge → API)")

    # Apply environment overrides
    if "PROXY_SCRAPE_INTERVAL" in os.environ:
        interval = os.environ["PROXY_SCRAPE_INTERVAL"]
        SERVICES["harvester"]["args"].extend(["--interval", interval])
        logger.info(f"⚙️  Set proxy scrape interval to {interval}s")

    if "API_PORT" in os.environ:
        port = os.environ["API_PORT"]
        SERVICES["api"]["env"]["PORT"] = port
        logger.info(f"⚙️  Set EchoAPI port to {port}")

    if "HARVESTER_API_PORT" in os.environ:
        port = os.environ["HARVESTER_API_PORT"]
        SERVICES["harvester"]["args"].extend(["--api-port", port])
        logger.info(f"⚙️  Set Harvester API port to {port}")

    if "FORWARDER_PORT" in os.environ:
        port = os.environ["FORWARDER_PORT"]
        SERVICES["harvester"]["args"].extend(["--forwarder-port", port])
        logger.info(f"⚙️  Set forwarder port to {port}")

    if "USE_PROXIES" in os.environ:
        use_proxies = os.environ["USE_PROXIES"].lower()
        SERVICES["api"]["env"]["USE_PROXIES"] = use_proxies
        logger.info(f"⚙️  Set USE_PROXIES to {use_proxies}")

    if "LOG_LEVEL" in os.environ:
        log_level = os.environ["LOG_LEVEL"].upper()
        logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))
        logger.info(f"⚙️  Set log level to {log_level}")

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, _):
        logger.info(f"📡 Received signal {signum}, initiating shutdown...")
        asyncio.create_task(shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start all services
        await start_all_services(enabled_services)

        # Print connection info
        logger.info("")
        logger.info("🔗 Connection Information:")
        logger.info("   • EchoAPI:         http://localhost:8000")
        logger.info("   • API Docs:        http://localhost:8000/docs")
        logger.info("   • Metrics:         http://localhost:8000/metrics")
        logger.info("   • Harvester API:   http://localhost:8080")
        logger.info("   • Forwarder:       http://127.0.0.1:8081")
        logger.info("")
        logger.info("💡 Tips:")
        logger.info("   • Check logs above for service output")
        logger.info("   • Press Ctrl+C to shutdown all services")
        logger.info("   • Individual service logs are prefixed with [SERVICE_NAME]")
        logger.info("")

        # Wait for shutdown signal
        await shutdown_event.wait()

    except Exception as e:
        logger.error(f"💥 Fatal error in main loop: {e}")
    finally:
        await stop_all_services()


async def shutdown():
    """Initiate shutdown."""
    logger.info("🛑 Shutdown initiated...")
    shutdown_event.set()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Interrupted by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        sys.exit(1)