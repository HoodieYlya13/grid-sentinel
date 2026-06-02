import time
from django.test import TestCase
from django.utils import timezone
from django.core.cache import cache
from .models import GridNode, TelemetryMetric, SpaceWeatherWorkload, SystemEvent
from .tasks import sync_space_weather_workload, get_dynamic_workload
from .ml_engine import analyze_telemetry_anomaly
from .views import pre_populate_healthy_history

class GridSentinelTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.node = GridNode.objects.create(
            hostname='test-worker-01',
            ip_address='127.0.0.1',
            role='worker',
            status='Healthy'
        )

    def test_space_weather_caching_and_db_pollution(self):
        initial_count = SpaceWeatherWorkload.objects.count()
        
        workload1 = sync_space_weather_workload()
        self.assertEqual(SpaceWeatherWorkload.objects.count(), initial_count + 1)
        
        workload2 = sync_space_weather_workload()
        self.assertEqual(SpaceWeatherWorkload.objects.count(), initial_count + 1)
        self.assertEqual(workload1.base_kp_index, workload2.base_kp_index)
        
        dyn1 = get_dynamic_workload(workload1)
        dyn2 = get_dynamic_workload(workload1)
        
        self.assertEqual(dyn1['base_kp_index'], workload1.base_kp_index)
        self.assertEqual(dyn2['base_kp_index'], workload1.base_kp_index)
        self.assertEqual(SpaceWeatherWorkload.objects.count(), initial_count + 1)

    def test_telemetry_pruning(self):
        now = timezone.now()
        for i in range(350):
            TelemetryMetric.objects.create(
                node=self.node,
                timestamp=now + timezone.timedelta(seconds=i),
                cpu_usage=20.0,
                ram_usage=40.0,
                network_rx=10.0,
                network_tx=2.0,
                active_jobs=5,
                is_anomaly=False
            )
            
        payload = {
            'hostname': 'test-worker-01',
            'cpu_usage': 25.0,
            'ram_usage': 42.0,
            'network_rx': 12.0,
            'network_tx': 3.0,
            'active_jobs': 6
        }
        response = self.client.post('/api/metrics/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        telemetry_count = TelemetryMetric.objects.filter(node=self.node).count()
        self.assertEqual(telemetry_count, 300)

    def test_ml_data_leakage_prevention(self):
        pre_populate_healthy_history(self.node)
        
        metric = TelemetryMetric.objects.create(
            node=self.node,
            cpu_usage=20.0,
            ram_usage=40.0,
            network_rx=10.0,
            network_tx=2.0,
            active_jobs=5
        )
        
        is_anomaly = analyze_telemetry_anomaly(metric)
        self.assertFalse(is_anomaly)
        
        history = TelemetryMetric.objects.filter(node=self.node, is_anomaly=False).exclude(id=metric.id)
        self.assertFalse(any(h.id == metric.id for h in history))

    def test_ml_baseline_drift_prevention(self):
        pre_populate_healthy_history(self.node)
        
        baseline_ram_mean = sum(x.ram_usage for x in TelemetryMetric.objects.all()) / TelemetryMetric.objects.count()
        
        metric11 = TelemetryMetric.objects.create(
            node=self.node,
            cpu_usage=25.0,
            ram_usage=baseline_ram_mean + 4.5,
            network_rx=10.0,
            network_tx=2.0,
            active_jobs=5
        )
        is_anomaly11 = analyze_telemetry_anomaly(metric11)
        self.assertFalse(is_anomaly11)
        
        metric12 = TelemetryMetric.objects.create(
            node=self.node,
            cpu_usage=25.0,
            ram_usage=baseline_ram_mean + 12.0,
            network_rx=10.0,
            network_tx=2.0,
            active_jobs=5
        )
        is_anomaly12 = analyze_telemetry_anomaly(metric12)
        
        self.assertTrue(is_anomaly12)

    def test_recovery_thread_concurrency_lock(self):
        pre_populate_healthy_history(self.node)
        
        payload = {
            'hostname': 'test-worker-01',
            'cpu_usage': 98.0,
            'ram_usage': 95.0,
            'network_rx': 10.0,
            'network_tx': 2.0,
            'active_jobs': 5
        }
        
        response1 = self.client.post('/api/metrics/', data=payload, content_type='application/json')
        self.assertEqual(response1.status_code, 200)
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, 'Degraded')
        
        response2 = self.client.post('/api/metrics/', data=payload, content_type='application/json')
        self.assertEqual(response2.status_code, 200)
        
        warning_events = SystemEvent.objects.filter(hostname='test-worker-01', level='WARNING').count()
        self.assertEqual(warning_events, 1)

    def test_space_weather_override(self):
        SpaceWeatherWorkload.objects.create(
            base_kp_index=3.0,
            base_solar_wind_speed=380.0,
            geomagnetic_kp_index=3.0,
            solar_wind_speed=380.0,
            stress_multiplier=1.0,
            is_live=True
        )

        response = self.client.post('/api/workload/override/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['override_active'])
        self.assertEqual(data['override_type'], 'spike')

        workload = SpaceWeatherWorkload.objects.first()
        dyn = get_dynamic_workload(workload)
        self.assertTrue(dyn['override_active'])
        self.assertEqual(dyn['override_type'], 'spike')
        self.assertAlmostEqual(dyn['base_kp_index'], 8.5)
        self.assertGreaterEqual(dyn['stress_multiplier'], 2.5)

        response = self.client.post('/api/workload/override/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['override_active'])

        dyn = get_dynamic_workload(workload)
        self.assertFalse(dyn['override_active'])
        self.assertAlmostEqual(dyn['base_kp_index'], 3.0)

    def test_custom_space_weather_override_value(self):
        SpaceWeatherWorkload.objects.create(
            base_kp_index=3.0,
            base_solar_wind_speed=380.0,
            geomagnetic_kp_index=3.0,
            solar_wind_speed=380.0,
            stress_multiplier=1.0,
            is_live=True
        )

        response = self.client.post(
            '/api/workload/override/',
            data={'kp': 6.5},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['override_active'])
        self.assertEqual(data['override_type'], 'spike')

        workload = SpaceWeatherWorkload.objects.first()
        dyn = get_dynamic_workload(workload)
        self.assertTrue(dyn['override_active'])
        self.assertEqual(dyn['override_type'], 'spike')
        self.assertAlmostEqual(dyn['base_kp_index'], 6.5)
        self.assertAlmostEqual(dyn['base_solar_wind_speed'], 733.3, places=1)

        response = self.client.post(
            '/api/workload/override/',
            data={'kp': 2.0},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['override_active'])
        self.assertEqual(data['override_type'], 'drop')

        dyn = get_dynamic_workload(workload)
        self.assertTrue(dyn['override_active'])
        self.assertEqual(dyn['override_type'], 'drop')
        self.assertAlmostEqual(dyn['base_kp_index'], 2.0)
        self.assertAlmostEqual(dyn['base_solar_wind_speed'], 433.3, places=1)

    def test_telemetry_normalization_under_storm_spike(self):
        pre_populate_healthy_history(self.node)
        
        SpaceWeatherWorkload.objects.create(
            base_kp_index=8.5,
            base_solar_wind_speed=700.0,
            geomagnetic_kp_index=8.5,
            solar_wind_speed=700.0,
            stress_multiplier=3.0,
            is_live=True
        )
        
        payload = {
            'hostname': 'test-worker-01',
            'cpu_usage': 65.0,
            'ram_usage': 40.0,
            'network_rx': 30.0,
            'network_tx': 6.0,
            'active_jobs': 30
        }
        
        response = self.client.post('/api/metrics/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, 'Healthy')
        
    def test_cluster_autoscaling_under_storm(self):
        from .tasks import handle_cluster_autoscaling
        
        GridNode.objects.all().delete()
        GridNode.objects.create(hostname='grid-worker-01', role='worker', status='Healthy')
        GridNode.objects.create(hostname='grid-worker-02', role='worker', status='Healthy')
        
        handle_cluster_autoscaling(1.0)
        self.assertEqual(GridNode.objects.exclude(status='Dead').count(), 2)
        
        handle_cluster_autoscaling(2.925)
        self.assertEqual(GridNode.objects.exclude(status='Dead').count(), 6)
        self.assertTrue(GridNode.objects.filter(hostname='grid-worker-06').exists())
        
        handle_cluster_autoscaling(1.0)
        self.assertEqual(GridNode.objects.exclude(status='Dead').count(), 2)
