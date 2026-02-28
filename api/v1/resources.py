from supabase.models import News, Videos
from .cache import SortedSetCache
from .serializers import NewsDetailSerializer, VideoDetailSerializer
from .views import (
    CachedListView,
    CachedCreateView,
    CachedDeleteView,
    CacheStatsView,
    CacheWarmView,
    CacheFlushView,
)


def _news_serializer(obj):
    return {
        "id": obj.id,
        "title": obj.title,
        "summary": obj.summary,
        "source": obj.source,
        "imageurl": obj.imageurl,
        "timestamp": obj.timestamp.isoformat() if obj.timestamp else None,
        "score": obj.score,
        "topic_id": obj.topic_id,
        "category_id": obj.categoryid_id,
    }


def _video_serializer(obj):
    return {
        "id": obj.id,
        "title": obj.title,
        "videourl": obj.videourl,
        "source": obj.source,
        "publisher_id": obj.publisher_id,
        "timestamp": obj.timestamp.isoformat() if obj.timestamp else None,
        "score": obj.score,
        "thumbnailurl": obj.thumbnailurl,
    }


news_cache = SortedSetCache(prefix="news", model=News, serialize_fn=_news_serializer)
video_cache = SortedSetCache(prefix="video", model=Videos, serialize_fn=_video_serializer)


class NewsListView(CachedListView):
    cache = news_cache
    serializer_class = NewsDetailSerializer
    model = News


class NewsCreateView(CachedCreateView):
    cache = news_cache
    serializer_class = NewsDetailSerializer


class NewsDeleteView(CachedDeleteView):
    cache = news_cache
    model = News


class NewsCacheStatsView(CacheStatsView):
    cache = news_cache


class NewsCacheWarmView(CacheWarmView):
    cache = news_cache


class NewsCacheFlushView(CacheFlushView):
    cache = news_cache


class VideoListView(CachedListView):
    cache = video_cache
    serializer_class = VideoDetailSerializer
    model = Videos


class VideoCreateView(CachedCreateView):
    cache = video_cache
    serializer_class = VideoDetailSerializer


class VideoDeleteView(CachedDeleteView):
    cache = video_cache
    model = Videos


class VideoCacheStatsView(CacheStatsView):
    cache = video_cache


class VideoCacheWarmView(CacheWarmView):
    cache = video_cache


class VideoCacheFlushView(CacheFlushView):
    cache = video_cache
