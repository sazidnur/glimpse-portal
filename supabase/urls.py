"""API URL routing."""

from django.urls import path
from .api_views import health_check, youtube_fetch, youtube_fetch_api

urlpatterns = [
    path('health/', health_check, name='api_health'),
    path('youtube/fetch/', youtube_fetch, name='api_youtube_fetch'),
    path('youtube/add/', youtube_fetch_api, name='api_youtube_add'),
]
