from django.urls import path
from . import views

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('api/enc/<str:hostname>/', views.PuppetEncView.as_view(), name='puppet_enc'),
    path('api/metrics/', views.MetricsWebhookView.as_view(), name='metrics_webhook'),
    path('api/nodes/recover/', views.NodeRecoveryWebhookView.as_view(), name='node_recovery_webhook'),
    path('api/workload/status/', views.WorkloadStatusView.as_view(), name='workload_status'),
    path('api/workload/override/', views.WorkloadOverrideView.as_view(), name='workload_override'),
    path('api/dashboard/data/', views.DashboardDataView.as_view(), name='dashboard_data'),
]
