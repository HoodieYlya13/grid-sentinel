import yaml
import json
import threading
import time
import subprocess
import datetime
import random
from django.utils import timezone
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from .models import GridNode, TelemetryMetric, SpaceWeatherWorkload, SystemEvent
from .ml_engine import analyze_telemetry_anomaly
from .tasks import sync_space_weather_workload

def pre_populate_healthy_history(node):
    now = timezone.now()
    metrics = []
    
    cpu_base = random.randint(15, 30)
    ram_base = random.randint(30, 50)
    
    for i in range(50):
        timestamp = now - datetime.timedelta(seconds=(50 - i) * 5)
        metrics.append(TelemetryMetric(
            node=node,
            timestamp=timestamp,
            cpu_usage=round(cpu_base + random.uniform(-2, 2), 2),
            ram_usage=round(ram_base + random.uniform(-1, 1), 2),
            network_rx=round(random.uniform(5.0, 15.0), 2),
            network_tx=round(random.uniform(1.0, 5.0), 2),
            active_jobs=10,
            is_anomaly=False
        ))
    TelemetryMetric.objects.bulk_create(metrics)

class DashboardView(View):
    def get(self, request):
        latest_workload = SpaceWeatherWorkload.objects.first()
        if not latest_workload or (time.time() - latest_workload.timestamp.timestamp() > 10):
            latest_workload = sync_space_weather_workload()
        
        from .tasks import get_dynamic_workload
        jittered_workload = get_dynamic_workload(latest_workload)

        nodes = GridNode.objects.all()
        node_data = []
        healthy_count = 0
        total_jobs = 0
        
        for node in nodes:
            latest_telemetry = node.telemetry.first()
            if node.status == 'Healthy':
                healthy_count += 1
            if latest_telemetry:
                total_jobs += latest_telemetry.active_jobs
            node_data.append({
                'node': node,
                'telemetry': latest_telemetry
            })

        events = SystemEvent.objects.all()[:20]
            
        context = {
            'nodes': node_data,
            'workload': jittered_workload,
            'healthy_count': healthy_count,
            'total_jobs': total_jobs,
            'events': events,
        }
        return render(request, 'dashboard.html', context)


@method_decorator(csrf_exempt, name='dispatch')
class PuppetEncView(View):
    def get(self, request, hostname):
        node, created = GridNode.objects.get_or_create(
            hostname=hostname,
            defaults={
                'ip_address': request.META.get('REMOTE_ADDR'),
                'role': 'worker',
                'thread_count': 8,
                'status': 'Healthy'
            }
        )
        
        if created:
            SystemEvent.objects.create(
                hostname=hostname,
                level='INFO',
                message="New grid node registered in Control Plane database."
            )
            pre_populate_healthy_history(node)
        else:
            SystemEvent.objects.create(
                hostname=hostname,
                level='INFO',
                message="Queried Puppet dynamic catalog parameters via ENC endpoint."
            )
        
        enc_data = {
            'classes': {
                'grid_node': {
                    'role': node.role,
                    'thread_count': node.thread_count,
                    'metrics_server': f"http://django:8000/api/metrics/",
                    'environment': node.environment
                }
            },
            'environment': node.environment
        }
        
        yaml_content = yaml.dump(enc_data, default_flow_style=False)
        return HttpResponse(yaml_content, content_type='text/yaml')


@method_decorator(csrf_exempt, name='dispatch')
class MetricsWebhookView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            hostname = data.get('hostname')
            
            node, created = GridNode.objects.get_or_create(
                hostname=hostname,
                defaults={'status': 'Healthy'}
            )
            if created:
                pre_populate_healthy_history(node)
            else:
                node.refresh_from_db()
            
            from .tasks import get_dynamic_workload
            latest_workload = SpaceWeatherWorkload.objects.first()
            if latest_workload:
                jittered = get_dynamic_workload(latest_workload)
                stress_mult = jittered.get('stress_multiplier', 1.0)
            else:
                stress_mult = 1.0

            metric = TelemetryMetric.objects.create(
                node=node,
                cpu_usage=data.get('cpu_usage'),
                ram_usage=data.get('ram_usage'),
                network_rx=data.get('network_rx'),
                network_tx=data.get('network_tx'),
                active_jobs=data.get('active_jobs'),
                stress_multiplier=stress_mult
            )
            
            is_anomaly = analyze_telemetry_anomaly(metric)
            
            telemetry_ids_to_keep = TelemetryMetric.objects.filter(node=node).order_by('-timestamp')[:300].values_list('id', flat=True)
            TelemetryMetric.objects.filter(node=node).exclude(id__in=list(telemetry_ids_to_keep)).delete()
            
            node.refresh_from_db()
            
            if is_anomaly:
                from django.db import transaction
                with transaction.atomic():
                    locked_node = GridNode.objects.select_for_update().get(id=node.id)
                    if locked_node.status == 'Healthy':
                        locked_node.status = 'Degraded'
                        locked_node.save()
                        
                        node.status = 'Degraded'
                        
                        SystemEvent.objects.create(
                            hostname=hostname,
                            level='WARNING',
                            message=f"ML Outlier detected (CPU: {metric.cpu_usage}%, RAM: {metric.ram_usage}%). Node state set to DEGRADED."
                        )
                        
                        import sys
                        if 'test' not in sys.argv:
                            threading.Thread(
                                target=trigger_ansible_recovery, 
                                args=(node.hostname,)
                            ).start()
                
            return JsonResponse({
                'status': 'success', 
                'is_anomaly': is_anomaly,
                'reboot': node.status == 'Recovering'
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class NodeRecoveryWebhookView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            hostname = data.get('hostname')
            status = data.get('status')
            message = data.get('message')
            
            node = GridNode.objects.get(hostname=hostname)
            node.status = status
            node.save()
            
            level = 'SUCCESS' if status == 'Healthy' else ('ERROR' if status == 'Dead' else 'INFO')
            SystemEvent.objects.create(
                hostname=hostname,
                level=level,
                message=f"Ansible playbook notification: {message}"
            )
            
            print(f"[Remediation Node: {hostname}] Status updated to: {status}. Msg: {message}")
            return JsonResponse({'status': 'acknowledged'})
        except GridNode.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Node not found'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


class WorkloadStatusView(View):
    def get(self, request):
        latest_workload = SpaceWeatherWorkload.objects.first()
        if not latest_workload or (time.time() - latest_workload.timestamp.timestamp() > 10):
            latest_workload = sync_space_weather_workload()
            
        from .tasks import get_dynamic_workload
        jittered_workload = get_dynamic_workload(latest_workload)
        
        active_workers = GridNode.objects.exclude(status='Dead').count()
        
        return JsonResponse({
            'stress_multiplier': jittered_workload['stress_multiplier'],
            'geomagnetic_kp_index': jittered_workload['geomagnetic_kp_index'],
            'spike_active': jittered_workload.get('spike_active', False),
            'active_workers': max(1, active_workers)
        })


@method_decorator(csrf_exempt, name='dispatch')
class WorkloadOverrideView(View):
    def post(self, request):
        from django.core.cache import cache
        from .models import SystemEvent, SpaceWeatherWorkload
        
        kp_val = None
        if request.body:
            try:
                data = json.loads(request.body)
                if 'kp' in data:
                    kp_val = float(data['kp'])
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        if kp_val is not None:
            kp_val = max(0.0, min(9.0, kp_val))
            wind_val = round(300.0 + (kp_val / 9.0) * 600.0, 1)
            override_type = 'spike' if kp_val > 5.0 else 'drop'
            
            override_data = {'type': override_type, 'kp': kp_val, 'wind': wind_val}
            cache.set('space_weather_override', override_data, 30)
            
            msg = f"Operator simulation: Space weather override adjusted to Kp={kp_val:.1f} ({override_type.upper()})."
            level = 'WARNING' if kp_val > 5.0 else 'INFO'
            
            SystemEvent.objects.create(
                hostname='Control Plane',
                level=level,
                message=msg
            )
            
            return JsonResponse({
                'status': 'success',
                'override_active': True,
                'override_type': override_type
            })

        active_override = cache.get('space_weather_override')
        if active_override:
            cache.delete('space_weather_override')
            SystemEvent.objects.create(
                hostname='Control Plane',
                level='INFO',
                message="Operator simulation: Solar weather override cancelled. Returning to NASA baseline."
            )
            return JsonResponse({'status': 'success', 'override_active': False})
            
        latest_workload = SpaceWeatherWorkload.objects.first()
        base_kp = latest_workload.base_kp_index if latest_workload else 3.0
        
        if base_kp > 5.0:
            override_data = {'type': 'drop', 'kp': 1.0, 'wind': 300.0}
            msg = "Operator simulation: Space weather override (DROP) injected! Calming conditions to 1.0x Load."
            level = 'INFO'
        else:
            override_data = {'type': 'spike', 'kp': 8.5, 'wind': 850.0}
            msg = "Operator simulation: Space weather override (SPIKE) injected! Scaling stress factor to 3.0x."
            level = 'WARNING'
            
        cache.set('space_weather_override', override_data, 30)
        
        SystemEvent.objects.create(
            hostname='Control Plane',
            level=level,
            message=msg
        )
        
        return JsonResponse({
            'status': 'success', 
            'override_active': True, 
            'override_type': override_data['type']
        })


class DashboardDataView(View):
    def get(self, request):
        latest_workload = SpaceWeatherWorkload.objects.first()
        if not latest_workload or (time.time() - latest_workload.timestamp.timestamp() > 10):
            latest_workload = sync_space_weather_workload()

        from .tasks import get_dynamic_workload, handle_cluster_autoscaling
        jittered_workload = get_dynamic_workload(latest_workload)

        handle_cluster_autoscaling(jittered_workload['stress_multiplier'])

        nodes = GridNode.objects.all()
        node_data = []
        healthy_count = 0
        total_jobs = 0
        
        for node in nodes:
            try:
                node_num = int(node.hostname.split('-')[-1])
            except ValueError:
                node_num = 1
                
            latest_telemetry = node.telemetry.first()
            
            if node_num > 2 and (not latest_telemetry or (timezone.now() - latest_telemetry.timestamp).total_seconds() > 3):
                latest_telemetry = TelemetryMetric.objects.create(
                    node=node,
                    cpu_usage=round(random.uniform(15.0, 25.0), 2),
                    ram_usage=round(random.uniform(30.0, 40.0), 2),
                    network_rx=round(random.uniform(3.0, 6.0), 2),
                    network_tx=round(random.uniform(1.0, 2.0), 2),
                    active_jobs=10,
                    stress_multiplier=1.0
                )

            if node.status == 'Healthy':
                healthy_count += 1
            if latest_telemetry:
                total_jobs += latest_telemetry.active_jobs
            node_data.append({
                'hostname': node.hostname,
                'status': node.status,
                'role': node.get_role_display(),
                'thread_count': node.thread_count,
                'cpu_usage': latest_telemetry.cpu_usage if latest_telemetry else 0.0,
                'ram_usage': latest_telemetry.ram_usage if latest_telemetry else 0.0,
                'network_rx': latest_telemetry.network_rx if latest_telemetry else 0.0,
                'network_tx': latest_telemetry.network_tx if latest_telemetry else 0.0,
                'active_jobs': latest_telemetry.active_jobs if latest_telemetry else 0,
                'is_anomaly': latest_telemetry.is_anomaly if latest_telemetry else False
            })

        events = SystemEvent.objects.all().order_by('-timestamp')[:50]
        event_list = [{
            'id': event.id,
            'timestamp': event.timestamp.strftime("%H:%M:%S"),
            'level': event.level,
            'hostname': event.hostname,
            'message': event.message
        } for event in events]

        return JsonResponse({
            'nodes': node_data,
            'healthy_count': healthy_count,
            'total_jobs': total_jobs,
            'events': event_list,
            'workload': jittered_workload
        })


def trigger_ansible_recovery(hostname):
    print(f"[Control Plane] Anomaly detected on {hostname}. Triggering Ansible recovery playbook...")
    
    SystemEvent.objects.create(
        hostname=hostname,
        level='INFO',
        message="Self-healing trigger: Executing Ansible recovery playbook 'recover_node.yml'."
    )
    
    time.sleep(2)
    try:
        node = GridNode.objects.get(hostname=hostname)
        node.status = 'Recovering'
        node.save()
        
        SystemEvent.objects.create(
            hostname=hostname,
            level='INFO',
            message="Ansible [Task 2]: Gracefully draining compute workloads on container to prevent job corruption."
        )
        
        time.sleep(12)
        
        node.status = 'Healthy'
        node.save()
        
        SystemEvent.objects.create(
            hostname=hostname,
            level='SUCCESS',
            message="Ansible [Task 5]: Restarted node container services. Health check verified. State reset to HEALTHY."
        )
        
        print(f"[Control Plane] Ansible simulation complete. Node {hostname} restored to Healthy state.")
    except Exception as e:
        print(f"[Control Plane] Anomaly Simulation error: {e}")
