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
    live_feed_publish,
    live_feed_token,
    live_feed_categories,
    live_feed_category_update,
    live_feed_category_delete,
    live_feed_items,
    live_feed_stats,
)

urlpatterns = [
    path('health/', health_check, name='api_health'),
    path('news/', news_data, name='api_news'),
    path('videos/', videos_data, name='api_videos'),
    path('categories/', categories_data, name='api_categories'),
    path('topics/', topics_data, name='api_topics'),
    path('youtube/fetch/', youtube_fetch, name='api_youtube_fetch'),
    path('youtube/add/', youtube_fetch_api, name='api_youtube_add'),
    path('live-feed/publish/', live_feed_publish, name='api_live_feed_publish'),
    path('live-feed/token/', live_feed_token, name='api_live_feed_token'),
    path('live-feed/categories/', live_feed_categories, name='api_live_feed_categories'),
    path('live-feed/categories/<int:category_id>/update/', live_feed_category_update, name='api_live_feed_category_update'),
    path('live-feed/categories/<int:category_id>/delete/', live_feed_category_delete, name='api_live_feed_category_delete'),
    path('live-feed/items/', live_feed_items, name='api_live_feed_items'),
    path('live-feed/stats/', live_feed_stats, name='api_live_feed_stats'),
]
