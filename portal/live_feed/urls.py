from django.urls import path
from . import views

app_name = 'live_feed'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('api/hubs/', views.api_hubs, name='api_hubs'),
    path('api/connect/', views.api_connect, name='api_connect'),
    path('api/disconnect/', views.api_disconnect, name='api_disconnect'),
    path('api/publish/', views.api_publish, name='api_publish'),
    path('api/logs/', views.api_logs, name='api_logs'),
    path('api/logs/clear/', views.api_clear_logs, name='api_clear_logs'),
    path('api/stream/', views.api_stream, name='api_stream'),
    path('api/costs/', views.api_costs, name='api_costs'),
    path('api/costs/reset/', views.api_reset_costs, name='api_reset_costs'),
    path('api/categories/', views.api_categories, name='api_categories'),
    path('api/pipeline/sources/', views.api_pipeline_sources, name='api_pipeline_sources'),
    path('api/pipeline/list/', views.api_pipelines, name='api_pipelines'),
    path('api/pipeline/logs/', views.api_pipeline_logs, name='api_pipeline_logs'),
    path('api/pipeline/run/', views.api_pipeline_run, name='api_pipeline_run'),
    path('api/pipeline/<int:pipeline_id>/update/', views.api_pipeline_update, name='api_pipeline_update'),
    path('api/pipeline/<int:pipeline_id>/start/', views.api_pipeline_start, name='api_pipeline_start'),
    path('api/pipeline/<int:pipeline_id>/stop/', views.api_pipeline_stop, name='api_pipeline_stop'),
    path('api/pipeline/<int:pipeline_id>/delete/', views.api_pipeline_delete, name='api_pipeline_delete'),
]
