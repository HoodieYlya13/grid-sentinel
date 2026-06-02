from django.db import models
from django.utils import timezone

class GridNode(models.Model):
    STATUS_CHOICES = [
        ('Healthy', 'Healthy'),
        ('Degraded', 'Degraded'),
        ('Recovering', 'Recovering'),
        ('Dead', 'Dead'),
    ]
    ROLE_CHOICES = [
        ('worker', 'Compute Worker'),
        ('head', 'Cluster Head'),
        ('storage', 'SE Storage Element'),
    ]

    hostname = models.CharField(max_length=255, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='worker')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Healthy')
    thread_count = models.IntegerField(default=4)
    environment = models.CharField(max_length=50, default='production')
    last_seen = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.hostname} ({self.status})"

    class Meta:
        ordering = ['hostname']


class TelemetryMetric(models.Model):
    node = models.ForeignKey(GridNode, on_delete=models.CASCADE, related_name='telemetry')
    timestamp = models.DateTimeField(default=timezone.now)
    cpu_usage = models.FloatField(help_text="CPU utilization percentage")
    ram_usage = models.FloatField(help_text="RAM utilization percentage")
    network_rx = models.FloatField(help_text="Network download speed in MB/s")
    network_tx = models.FloatField(help_text="Network upload speed in MB/s")
    active_jobs = models.IntegerField(default=0, help_text="Number of running grid job tasks")
    stress_multiplier = models.FloatField(default=1.0, help_text="Workload stress multiplier when this metric was recorded")
    is_anomaly = models.BooleanField(default=False, help_text="Flagged by ML Anomaly Detection engine")

    def __str__(self):
        return f"{self.node.hostname} @ {self.timestamp.strftime('%H:%M:%S')} - CPU={self.cpu_usage}%"

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['node', '-timestamp']),
        ]


class SpaceWeatherWorkload(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    geomagnetic_kp_index = models.FloatField(default=3.0, help_text="Simulated or real geomagnetic index (0-9)")
    solar_wind_speed = models.FloatField(default=400.0, help_text="Solar wind speed in km/s")
    base_kp_index = models.FloatField(default=3.0, help_text="Raw baseline geomagnetic index")
    base_solar_wind_speed = models.FloatField(default=400.0, help_text="Raw baseline solar wind speed")
    stress_multiplier = models.FloatField(default=1.0, help_text="Computed stress scale factor for cluster load generation")
    is_live = models.BooleanField(default=True, help_text="Indicates if the metrics are pulled from NASA API vs simulated local cycle")

    def __str__(self):
        return f"Workload scale={self.stress_multiplier} @ {self.timestamp}"

    class Meta:
        ordering = ['-timestamp']


class SystemEvent(models.Model):
    LEVEL_CHOICES = [
        ('INFO', 'INFO'),
        ('WARNING', 'WARNING'),
        ('ERROR', 'ERROR'),
        ('SUCCESS', 'SUCCESS'),
    ]
    timestamp = models.DateTimeField(auto_now_add=True)
    hostname = models.CharField(max_length=255)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='INFO')
    message = models.TextField()

    def __str__(self):
        return f"[{self.level}] {self.hostname}: {self.message[:40]}"

    class Meta:
        ordering = ['-timestamp']
