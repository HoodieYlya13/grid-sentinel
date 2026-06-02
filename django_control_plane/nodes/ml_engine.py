import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from .models import TelemetryMetric

def analyze_telemetry_anomaly(metric_instance):
    node = metric_instance.node
    curr_sm = getattr(metric_instance, 'stress_multiplier', 1.0)
    if not curr_sm or curr_sm <= 0:
        curr_sm = 1.0
    
    history = TelemetryMetric.objects.filter(
        node=node, 
        is_anomaly=False
    ).exclude(
        id=metric_instance.id
    ).order_by('-timestamp')[:200]
    
    if len(history) < 20:
        is_anomaly = (metric_instance.cpu_usage / curr_sm) > 95.0 or metric_instance.ram_usage > 90.0
        metric_instance.is_anomaly = is_anomaly
        metric_instance.save()
        return is_anomaly

    data_list = []
    for h in history:
        sm = getattr(h, 'stress_multiplier', 1.0)
        if not sm or sm <= 0:
            sm = 1.0
        data_list.append({
            'cpu_usage': h.cpu_usage / sm,
            'ram_usage': h.ram_usage,
            'network_rx': h.network_rx / sm,
            'network_tx': h.network_tx / sm,
            'active_jobs': h.active_jobs / sm
        })
    
    df = pd.DataFrame(data_list)
    
    X_train = df[['cpu_usage', 'ram_usage', 'network_rx', 'network_tx', 'active_jobs']].values
    
    model = IsolationForest(n_estimators=100, contamination='auto', random_state=42)
    model.fit(X_train)
    
    X_current = np.array([[
        metric_instance.cpu_usage / curr_sm,
        metric_instance.ram_usage,
        metric_instance.network_rx / curr_sm,
        metric_instance.network_tx / curr_sm,
        metric_instance.active_jobs / curr_sm
    ]])
    
    prediction = model.predict(X_current)
    
    is_anomaly = bool(prediction[0] == -1)
    
    baseline_history = TelemetryMetric.objects.filter(
        node=node, 
        is_anomaly=False
    ).exclude(
        id=metric_instance.id
    ).order_by('timestamp')[:50]
    
    if baseline_history.count() >= 20:
        cpu_norms = []
        for h in baseline_history:
            sm = getattr(h, 'stress_multiplier', 1.0)
            if not sm or sm <= 0:
                sm = 1.0
            cpu_norms.append(h.cpu_usage / sm)
        history_cpu_mean = np.mean(cpu_norms)
        history_ram_mean = np.mean([h.ram_usage for h in baseline_history])
    else:
        history_cpu_mean = df['cpu_usage'].mean()
        history_ram_mean = df['ram_usage'].mean()
    
    cpu_deviation = (metric_instance.cpu_usage / curr_sm) - history_cpu_mean
    ram_deviation = metric_instance.ram_usage - history_ram_mean
    
    if is_anomaly:
        significant_deviation = (cpu_deviation > 25.0) or (ram_deviation > 10.0)
        if not significant_deviation:
            is_anomaly = False
    
    if (metric_instance.cpu_usage / curr_sm) > 95.0 or metric_instance.ram_usage > 90.0:
        is_anomaly = True
    
    metric_instance.is_anomaly = is_anomaly
    metric_instance.save()
    
    return is_anomaly
