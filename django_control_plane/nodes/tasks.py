import json
import random
import urllib.request
import os
import time
from datetime import datetime, timedelta
from django.core.cache import cache
from .models import SpaceWeatherWorkload

import math

NASA_DONKI_URL = "https://api.nasa.gov/DONKI/GST"

def get_dynamic_workload(base_workload):
    override = cache.get('space_weather_override')
    
    if override:
        base_kp = override['kp']
        base_wind = override['wind']
        is_live = True
        override_active = True
        override_type = override['type']
    else:
        base_kp = base_workload.base_kp_index if base_workload else 3.0
        base_wind = base_workload.base_solar_wind_speed if base_workload else 400.0
        is_live = base_workload.is_live if base_workload else True
        override_active = False
        override_type = None

    t = time.time()
    kp_jitter = math.sin(t * 1.5) * 0.12 + math.cos(t * 2.8) * 0.08
    wind_jitter = math.sin(t * 1.2) * 4.5 + math.cos(t * 2.3) * 2.5
    
    kp_index = round(max(0.0, min(9.0, base_kp + kp_jitter)), 1)
    wind_speed = round(max(100.0, min(1000.0, base_wind + wind_jitter)), 1)
    stress_multiplier = round(max(1.0, 1.0 + (kp_index - 3.0) * 0.35), 2)
    
    return {
        'geomagnetic_kp_index': kp_index,
        'solar_wind_speed': wind_speed,
        'base_kp_index': base_kp,
        'base_solar_wind_speed': base_wind,
        'stress_multiplier': stress_multiplier,
        'is_live': is_live,
        'override_active': override_active,
        'override_type': override_type
    }

def sync_space_weather_workload():
    cached_data = cache.get('nasa_space_weather_base')
    
    nasa_api_key = os.environ.get("NASA_API_KEY") or "DEMO_KEY"
    
    if cached_data is None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        last_week = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        url = f"{NASA_DONKI_URL}?startDate={last_week}&endDate={today}&api_key={nasa_api_key}"
        
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                
                if isinstance(data, list) and len(data) > 0:
                    print(f"[NASA Sync] Found {len(data)} active geomagnetic solar events.")
                    kp_index = min(9.0, 3.0 + len(data) * 1.5)
                    wind_speed = min(900.0, 400.0 + len(data) * 80.0)
                else:
                    print("[NASA Sync] No active solar storms this week. Defaulting to baseline parameters.")
                    kp_index = 3.0
                    wind_speed = 380.0
                is_live = True
                
        except Exception as e:
            print(f"[NASA Sync] Warning: Failed to query NASA API ({e}). Executing solar-cycle simulator fallback.")
            kp_index = round(random.uniform(1.0, 8.5), 1)
            wind_speed = round(random.uniform(300.0, 850.0), 1)
            is_live = False

        cached_data = {
            'kp_index': kp_index,
            'wind_speed': wind_speed,
            'is_live': is_live
        }
        cache.set('nasa_space_weather_base', cached_data, 900)
        
        workload = SpaceWeatherWorkload.objects.create(
            geomagnetic_kp_index=kp_index,
            solar_wind_speed=wind_speed,
            base_kp_index=kp_index,
            base_solar_wind_speed=wind_speed,
            stress_multiplier=round(max(1.0, 1.0 + (kp_index - 3.0) * 0.35), 2),
            is_live=is_live
        )
        print(f"[NASA Sync] Cached and saved new space weather baseline: Kp={kp_index}, Wind={wind_speed} km/s, Live={is_live}")
    else:
        workload = SpaceWeatherWorkload.objects.first()
        if not workload:
            kp_index = cached_data['kp_index']
            wind_speed = cached_data['wind_speed']
            is_live = cached_data['is_live']
            workload = SpaceWeatherWorkload.objects.create(
                geomagnetic_kp_index=kp_index,
                solar_wind_speed=wind_speed,
                base_kp_index=kp_index,
                base_solar_wind_speed=wind_speed,
                stress_multiplier=round(max(1.0, 1.0 + (kp_index - 3.0) * 0.35), 2),
                is_live=is_live
            )
            print(f"[NASA Sync] Recreated baseline record in database from cache.")
        else:
            print(f"[NASA Sync] Cache hit! Reusing baseline Kp={workload.base_kp_index}, Wind={workload.base_solar_wind_speed} km/s")
            
    return workload

def handle_cluster_autoscaling(stress_multiplier):
    from .models import GridNode, SystemEvent
    from .views import pre_populate_healthy_history
    import math

    if stress_multiplier <= 1.2:
        target_node_count = 2
    else:
        target_node_count = max(2, math.ceil(2 * stress_multiplier))
    
    active_nodes = list(GridNode.objects.exclude(status='Dead').order_by('hostname'))
    current_count = len(active_nodes)
    
    if current_count < target_node_count:
        for i in range(current_count + 1, target_node_count + 1):
            hostname = f"grid-worker-{i:02d}"
            node, created = GridNode.objects.get_or_create(
                hostname=hostname,
                defaults={
                    'role': 'worker',
                    'status': 'Healthy',
                    'ip_address': f"172.18.0.{10+i}"
                }
            )
            if created or node.status == 'Dead':
                node.status = 'Healthy'
                node.save()
                pre_populate_healthy_history(node)
                SystemEvent.objects.create(
                    hostname='Control Plane',
                    level='SUCCESS',
                    message=f"Horizontal Autoscaler: Provisioned and bootstrapped new node {hostname} to handle load spike."
                )
    elif current_count > target_node_count:
        for node in active_nodes:
            try:
                node_num = int(node.hostname.split('-')[-1])
            except ValueError:
                node_num = 1
                
            if node_num > 2 and node_num > target_node_count:
                node.delete()
                SystemEvent.objects.create(
                    hostname='Control Plane',
                    level='INFO',
                    message=f"Horizontal Autoscaler: Terminated and de-provisioned node {node.hostname} (load stabilized)."
                )
