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
]
