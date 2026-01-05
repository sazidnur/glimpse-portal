"""
API URL routing for WordPress integration.

Endpoints:
    GET /api/news/   - Latest 20 news (Token auth required)
    GET /api/health/ - Health check (no auth)
"""

from django.urls import path
from .api_views import news_list, health_check

urlpatterns = [
    path('health/', health_check, name='api_health'),
    path('news/', news_list, name='api_news_list'),
]
