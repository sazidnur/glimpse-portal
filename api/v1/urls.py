from django.urls import path

from .resources import (
    NewsListView,
    NewsCreateView,
    NewsDeleteView,
    NewsCacheStatsView,
    NewsCacheWarmView,
    NewsCacheFlushView,
    VideoListView,
    VideoCreateView,
    VideoDeleteView,
    VideoCacheStatsView,
    VideoCacheWarmView,
    VideoCacheFlushView,
)

urlpatterns = [
    path("news/", NewsListView.as_view(), name="news_list"),
    path("news/create/", NewsCreateView.as_view(), name="news_create"),
    path("news/<int:pk>/delete/", NewsDeleteView.as_view(), name="news_delete"),
    path("news/delete/", NewsDeleteView.as_view(), name="news_delete_batch"),
    path("news/cache/", NewsCacheStatsView.as_view(), name="news_cache_stats"),
    path("news/cache/warm/", NewsCacheWarmView.as_view(), name="news_cache_warm"),
    path("news/cache/flush/", NewsCacheFlushView.as_view(), name="news_cache_flush"),

    path("videos/", VideoListView.as_view(), name="video_list"),
    path("videos/create/", VideoCreateView.as_view(), name="video_create"),
    path("videos/<int:pk>/delete/", VideoDeleteView.as_view(), name="video_delete"),
    path("videos/delete/", VideoDeleteView.as_view(), name="video_delete_batch"),
    path("videos/cache/", VideoCacheStatsView.as_view(), name="video_cache_stats"),
    path("videos/cache/warm/", VideoCacheWarmView.as_view(), name="video_cache_warm"),
    path("videos/cache/flush/", VideoCacheFlushView.as_view(), name="video_cache_flush"),
]
