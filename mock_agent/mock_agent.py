import os
import sys
import time
import json
import random
import urllib.request
import urllib.error

CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://django:8000")
NODE_HOSTNAME = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NODE_HOSTNAME", "grid-worker-unknown")

print(f"--- Sentinel Mock Agent starting on node: {NODE_HOSTNAME} ---")
print(f"Connecting to Control Plane at: {CONTROL_PLANE_URL}")

def fetch_puppet_enc():
    url = f"{CONTROL_PLANE_URL}/api/enc/{NODE_HOSTNAME}/"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            content = response.read().decode("utf-8")
            print(f"[{NODE_HOSTNAME}] Puppet ENC Configuration Loaded.")
            return content
    except Exception as e:
        print(f"[{NODE_HOSTNAME}] Warning: Failed to fetch Puppet ENC config: {e}")
        return None

def send_telemetry(metrics):
    url = f"{CONTROL_PLANE_URL}/api/metrics/"
    data = json.dumps(metrics).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data
    except Exception as e:
        print(f"[{NODE_HOSTNAME}] Warning: Failed to post telemetry: {e}")
        return None

cpu_base = random.randint(15, 30)
ram_base = random.randint(30, 50)
has_memory_leak = False
loop_count = 0

if "worker-02" in NODE_HOSTNAME or "02" in NODE_HOSTNAME:
    print(f"[{NODE_HOSTNAME}] Initialized with latent anomaly vector (memory leak scheduler activated).")

while True:
    loop_count += 1
    
    if loop_count % 5 == 1:
        fetch_puppet_enc()

    try:
        req = urllib.request.Request(f"{CONTROL_PLANE_URL}/api/workload/status/", method="GET")
        with urllib.request.urlopen(req, timeout=2) as r:
            status = json.loads(r.read().decode("utf-8"))
            stress_multiplier = status.get("stress_multiplier", 1.0)
            active_workers = status.get("active_workers", 2)
    except Exception:
        stress_multiplier = 1.0
        active_workers = 2

    if loop_count > 10 and ("worker-02" in NODE_HOSTNAME or "02" in NODE_HOSTNAME):
        has_memory_leak = True
        
    scale_factor = 2.0 / max(1, active_workers)

    if has_memory_leak:
        ram_usage = min(98.5, ram_base + (loop_count - 10) * 4.5 + random.uniform(-1, 1))
        leak_severity = (ram_usage - ram_base) / 50.0
        cpu_usage = min(99.0, cpu_base + (5.0 + leak_severity * 15.0) * stress_multiplier * scale_factor + random.uniform(-2, 2))
    else:
        cpu_usage = min(95.0, (cpu_base + random.uniform(-5, 5)) * stress_multiplier * scale_factor)
        ram_usage = ram_base + random.uniform(-2, 2)

    network_rx = random.uniform(5.0, 15.0) * stress_multiplier * scale_factor
    network_tx = random.uniform(1.0, 5.0) * stress_multiplier * scale_factor

    telemetry_data = {
        "hostname": NODE_HOSTNAME,
        "cpu_usage": round(cpu_usage, 2),
        "ram_usage": round(ram_usage, 2),
        "network_rx": round(network_rx, 2),
        "network_tx": round(network_tx, 2),
        "active_jobs": int(10 * stress_multiplier * scale_factor) if not has_memory_leak else 1
    }

    print(f"[{NODE_HOSTNAME}] Telemetry: CPU={telemetry_data['cpu_usage']}% | RAM={telemetry_data['ram_usage']}% | Jobs={telemetry_data['active_jobs']}")
    
    resp = send_telemetry(telemetry_data)
    if resp and resp.get('reboot'):
        print(f"[{NODE_HOSTNAME}] RECEIVING REMEDIATION SIGNAL (ANSIBLE REBOOT). Simulating container reboot (going offline)...")
        has_memory_leak = False
        loop_count = 0
        time.sleep(12)

    if ram_usage > 95.0:
        print(f"[{NODE_HOSTNAME}] WARNING: Extreme memory pressure. System unresponsive.")
        
    time.sleep(1)
