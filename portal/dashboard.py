"""
Dashboard callback for Unfold admin theme.
Provides data for the admin dashboard including content stats, cache status, and CF analytics summary.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from django.conf import settings
from django.urls import reverse

from api.v1.resources import news_cache, video_cache, metadata_cache
from .models import News, Videos, Videopublishers, Categories, Divisions, Topics

logger = logging.getLogger(__name__)


def environment_callback(request):
    """
    Unfold environment callback - returns environment info for header display.
    Returning None allows theme switching.
    """
    return None


def get_content_stats(days=None):
    """Get content statistics with optional time filtering."""
    news_qs = News.objects.all()
    videos_qs = Videos.objects.all()
    
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        news_qs = news_qs.filter(timestamp__gte=cutoff)
        videos_qs = videos_qs.filter(timestamp__gte=cutoff)
    
    return {
        "news": news_qs.count(),
        "videos": videos_qs.count(),
        "publishers": Videopublishers.objects.count(),
        "categories": Categories.objects.filter(live_feed_type=0).count(),
        "categories_active": Categories.objects.filter(enabled=True, live_feed_type=0).count(),
        "live_feed": Categories.objects.filter(live_feed_type__gt=0).count(),
        "live_feed_active": Categories.objects.filter(enabled=True, live_feed_type__gt=0).count(),
        "divisions": Divisions.objects.count(),
        "topics": Topics.objects.count(),
    }


def get_cache_status():
    """Get Redis cache status for all caches."""
    caches = []
    
    # News cache
    try:
        news_stats = news_cache.stats()
        news_db_total = News.objects.count()
        caches.append({
            "key": "news",
            "label": "News",
            "cached": news_stats["total_items"],
            "db_total": news_db_total,
            "synced": news_stats["total_items"] == news_db_total,
            "memory": news_stats["redis_used_memory"],
        })
    except Exception as e:
        logger.error("Failed to get news cache stats: %s", e)
        caches.append({
            "key": "news",
            "label": "News", 
            "cached": 0,
            "db_total": News.objects.count(),
            "synced": False,
            "memory": "N/A",
            "error": str(e),
        })
    
    # Video cache
    try:
        video_stats = video_cache.stats()
        video_db_total = Videos.objects.count()
        caches.append({
            "key": "video",
            "label": "Videos",
            "cached": video_stats["total_items"],
            "db_total": video_db_total,
            "synced": video_stats["total_items"] == video_db_total,
            "memory": video_stats["redis_used_memory"],
        })
    except Exception as e:
        logger.error("Failed to get video cache stats: %s", e)
        caches.append({
            "key": "video",
            "label": "Videos",
            "cached": 0,
            "db_total": Videos.objects.count(),
            "synced": False,
            "memory": "N/A",
            "error": str(e),
        })
    
    # Metadata cache
    try:
        meta_stats = metadata_cache.stats()
        caches.append({
            "key": "metadata",
            "label": "Metadata",
            "cached": 1 if meta_stats["cached"] else 0,
            "db_total": 1,
            "synced": meta_stats["cached"],
            "memory": "-",
            "ttl": meta_stats["ttl_seconds"],
            "last_sync": meta_stats["last_sync_at"],
        })
    except Exception as e:
        logger.error("Failed to get metadata cache stats: %s", e)
        caches.append({
            "key": "metadata",
            "label": "Metadata",
            "cached": 0,
            "db_total": 1,
            "synced": False,
            "memory": "-",
            "error": str(e),
        })
    
    return caches


def get_cf_credentials_configured():
    """Check if CF Analytics credentials are configured."""
    return bool(
        getattr(settings, "CF_ACCOUNT_ID", "") and
        getattr(settings, "CF_ANALYTICS_TOKEN", "")
    )


def get_content_trends():
    """Get daily content counts for the past 7 days."""
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    
    # Get news counts by day
    news_by_day = dict(
        News.objects.filter(timestamp__gte=seven_days_ago)
        .annotate(day=TruncDate('timestamp'))
        .values('day')
        .annotate(count=Count('id'))
        .values_list('day', 'count')
    )
    
    # Get video counts by day
    videos_by_day = dict(
        Videos.objects.filter(timestamp__gte=seven_days_ago)
        .annotate(day=TruncDate('timestamp'))
        .values('day')
        .annotate(count=Count('id'))
        .values_list('day', 'count')
    )
    
    # Build arrays for the past 7 days
    news_trend = []
    videos_trend = []
    labels = []
    
    for i in range(7, 0, -1):
        day = (now - timedelta(days=i)).date()
        labels.append(day.strftime('%a'))
        news_trend.append(news_by_day.get(day, 0))
        videos_trend.append(videos_by_day.get(day, 0))
    
    return {
        "labels": labels,
        "news": news_trend,
        "videos": videos_trend,
    }


def dashboard_callback(request, context):
    """
    Unfold dashboard callback - prepares variables for admin/index.html.
    """
    # Get time filter from query params (default: all time)
    time_filter = request.GET.get("period", "all")
    days_map = {
        "today": 1,
        "7d": 7,
        "30d": 30,
        "365d": 365,
        "all": None,
    }
    days = days_map.get(time_filter, None)
    
    # Content stats
    content_stats = get_content_stats(days)
    
    # Cache status
    cache_status = get_cache_status()
    
    # Cache URLs for AJAX operations
    cache_urls = {
        "stats_news": reverse("admin:cache_dashboard_stats", args=["news"]),
        "stats_video": reverse("admin:cache_dashboard_stats", args=["video"]),
        "warm_news": reverse("admin:cache_dashboard_warm", args=["news"]),
        "warm_video": reverse("admin:cache_dashboard_warm", args=["video"]),
        "flush_news": reverse("admin:cache_dashboard_flush", args=["news"]),
        "flush_video": reverse("admin:cache_dashboard_flush", args=["video"]),
        "metadata_stats": reverse("admin:cache_dashboard_metadata_stats"),
        "metadata_flush": reverse("admin:cache_dashboard_metadata_flush"),
        "metadata_rebuild": reverse("admin:cache_dashboard_metadata_rebuild"),
    }
    
    # CF Analytics info
    cf_configured = get_cf_credentials_configured()
    cf_data_url = reverse("admin:cf_analytics_data") if cf_configured else None
    
    # Content trends (7-day)
    content_trends = get_content_trends()
    
    # Quick links
    quick_links = [
        {"title": "Add News", "url": reverse("admin:data_news_add"), "icon": "add_circle"},
        {"title": "Add Video", "url": reverse("admin:data_videos_add"), "icon": "add_circle"},
        {"title": "CF Analytics", "url": reverse("admin:cf_analytics"), "icon": "insights"},
        {"title": "Live Feed", "url": reverse("live_feed:dashboard"), "icon": "stream"},
    ]
    
    context.update({
        "content_stats": content_stats,
        "content_trends": content_trends,
        "content_trends_json": json.dumps(content_trends),
        "cache_status": cache_status,
        "cache_status_json": json.dumps(cache_status),
        "cache_urls": cache_urls,
        "cache_urls_json": json.dumps(cache_urls),
        "cf_configured": cf_configured,
        "cf_data_url": cf_data_url,
        "quick_links": quick_links,
        "time_filter": time_filter,
        "time_filters": [
            {"key": "today", "label": "Today"},
            {"key": "7d", "label": "7 Days"},
            {"key": "30d", "label": "30 Days"},
            {"key": "365d", "label": "1 Year"},
            {"key": "all", "label": "All Time"},
        ],
    })
    
    return context
