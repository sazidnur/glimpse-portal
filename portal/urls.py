"""API URL routing."""

from django.urls import path
from .api_views import (
    health_check,
    news_data,
    videos_data,
    categories_data,
    topics_data,
    youtube_fetch,
    youtube_fetch_api,
)
from .push.api import (
    PushNotificationCancelView,
    PushNotificationDetailView,
    PushNotificationListCreateView,
    PushNotificationSendNowView,
)

urlpatterns = [
    path('health/', health_check, name='api_health'),
    path('news/', news_data, name='api_news'),
    path('videos/', videos_data, name='api_videos'),
    path('categories/', categories_data, name='api_categories'),
    path('topics/', topics_data, name='api_topics'),
    path('youtube/fetch/', youtube_fetch, name='api_youtube_fetch'),
    path('youtube/add/', youtube_fetch_api, name='api_youtube_add'),
    path('push/', PushNotificationListCreateView.as_view(), name='api_push_list'),
    path('push/<int:pk>/', PushNotificationDetailView.as_view(), name='api_push_detail'),
    path('push/<int:pk>/cancel/', PushNotificationCancelView.as_view(), name='api_push_cancel'),
    path('push/<int:pk>/send-now/', PushNotificationSendNowView.as_view(), name='api_push_send_now'),
]
