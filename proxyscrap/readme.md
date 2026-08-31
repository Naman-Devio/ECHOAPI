# Install dependencies
pip install -r requirements.txt

# Run interactively
python3 proxy_harvester.py

# Run with custom settings
python3 proxy_harvester.py --interval 300 --threads 100 --output /opt/proxy_pool

# Run as daemon
python3 proxy_harvester.py --daemon 

Systemd service (/etc/systemd/system/proxyharvester.service):

[Unit]
Description=ProxyHarvester - Continuous Proxy Scraper & Validator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/proxyharvester
ExecStart=/usr/bin/python3 /opt/proxyharvester/proxy_harvester.py --interval 300 --threads 100
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

# Enable and start the service
systemctl daemon-reload
systemctl enable proxyharvester
systemctl start proxyharvester
systemctl status proxyharvester


What this tool does:


Feature	Description
Multi-source scraping	Pulls from 12+ proxy sources (ProxyScrape, Free-Proxy-List, SSL Proxies, SOCKS proxies, Geonode, HideMy.name, etc.)
Protocol detection	Auto-detects HTTP, HTTPS, SOCKS4, and SOCKS5
Concurrent validation	Tests 50+ proxies simultaneously using asyncio
Quality scoring	Tracks success rate, latency, and failure streaks per proxy
Auto-pruning	Removes proxies that fail 3+ consecutive checks or drop below 60% success rate
Anonymity checking	Detects transparent vs anonymous proxies
Persistent storage	Saves working proxies to JSON, survives restarts
Stats & monitoring	Real-time stats output, protocol breakdown, fastest proxies
Graceful shutdown	Saves state on SIGINT/SIGTERM
Systemd integration	Runs as a production service with auto-restart
Output files (in ./proxy_pool/):

working_proxies.json — All proxies with full metadata (latency, protocol, success rate, anonymity status)
stats.json — Operational statistics
harvester.log — Full logging
You can consume the working proxies from working_proxies.json in your other pentesting tools for IP rotation, rate-limit evasion, and anonymized recon.