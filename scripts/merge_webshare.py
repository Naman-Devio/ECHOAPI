import json

free_proxies = [
    {'proxy': 'socks5://45.194.33.12:30002', 'latency_ms': 937.0},
    {'proxy': 'socks5://45.194.33.12:30001', 'latency_ms': 1250.0},
    {'proxy': 'socks5://150.109.247.86:8443', 'latency_ms': 9141.0},
]

webshare_proxies = [
    {'proxy': 'socks5://bchnufst:gvxaz5liq56h@45.38.107.97:6014', 'latency_ms': 2125.0},
    {'proxy': 'socks5://bchnufst:gvxaz5liq56h@198.105.121.200:6462', 'latency_ms': 2406.0},
    {'proxy': 'socks5://bchnufst:gvxaz5liq56h@198.23.243.226:6361', 'latency_ms': 3218.0},
    {'proxy': 'socks5://bchnufst:gvxaz5liq56h@84.247.60.125:6095', 'latency_ms': 2406.0},
    {'proxy': 'socks5://bchnufst:gvxaz5liq56h@142.111.67.146:5611', 'latency_ms': 2109.0},
    {'proxy': 'socks5://bchnufst:gvxaz5liq56h@191.96.254.138:6185', 'latency_ms': 2968.0},
]

all_proxies = free_proxies + webshare_proxies
all_proxies.sort(key=lambda x: x['latency_ms'])

proxy_dir = 'C:/Users/NAMAN/Desktop/MAINTENANCE/API/echoapi-main/echoapi-main/proxies/working/'

with open(proxy_dir + 'socks5_working.txt', 'w') as f:
    for p in all_proxies:
        f.write(p['proxy'] + '\n')

print('Updated socks5_working.txt:', len(all_proxies))

speed_data = []
for p in all_proxies:
    ip_port = p['proxy'].replace('socks5://', '')
    speed_data.append({'proxy': ip_port, 'speed_seconds': round(p['latency_ms']/1000,3), 'protocol': 'socks5'})

speed_data.sort(key=lambda x: x['speed_seconds'])
speed_data = speed_data[:30]

with open(proxy_dir + 'socks5_speed.json', 'w') as f:
    json.dump(speed_data, f, indent=2)

print('Updated socks5_speed.json:', len(speed_data))
for i, s in enumerate(speed_data, 1):
    print(f'  {i}. {s["proxy"]} - {s["speed_seconds"]}s')