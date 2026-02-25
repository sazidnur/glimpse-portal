"""API URL routing."""

from django.urls import path
from .api_views import news_list, health_check, youtube_fetch, youtube_fetch_api

urlpatterns = [
    path('health/', health_check, name='api_health'),
    path('news/', news_list, name='api_news_list'),
    path('youtube/fetch/', youtube_fetch, name='api_youtube_fetch'),
    path('youtube/add/', youtube_fetch_api, name='api_youtube_add'),
]
