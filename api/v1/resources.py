import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from supabase.models import (
    News, Videos, Categories, Topics, Divisions, Videopublishers, Sourcealias,
)
from .cache import SortedSetCache, MetadataCache
from .serializers import (
    NewsDetailSerializer, VideoDetailSerializer,
    CategorySerializer, TopicSerializer, DivisionSerializer, VideoPublisherSerializer,
    SourceAliasSerializer,
)
from .views import (
    CachedListView,
    CachedCreateView,
    CachedDeleteView,
    CacheStatsView,
    CacheWarmView,
    CacheFlushView,
)

logger = logging.getLogger(__name__)


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
        "division_id": obj.divisionid_id,
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
metadata_cache = MetadataCache()


def _using(model, using=None):
    return model.objects.using(using) if using else model.objects


def build_metadata_payload(using=None):
    return {
        "categories": CategorySerializer(
            _using(Categories, using).filter(enabled=True).order_by("order"),
            many=True,
        ).data,
        "topics": TopicSerializer(
            _using(Topics, using).filter(enabled=True).order_by("order"),
            many=True,
        ).data,
        "divisions": DivisionSerializer(
            _using(Divisions, using).all().order_by("order"),
            many=True,
        ).data,
        "publishers": VideoPublisherSerializer(
            _using(Videopublishers, using).all(),
            many=True,
        ).data,
        "source_aliases": SourceAliasSerializer(
            _using(Sourcealias, using).all(),
            many=True,
        ).data,
    }


def rebuild_metadata_cache(using=None):
    data = build_metadata_payload(using=using)
    metadata_cache.set(data)
    logger.info("Metadata cache rebuild completed (using=%s)", using or "default-router")
    return data


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


class MetadataListView(APIView):
    """Returns categories, topics, divisions, and video publishers in one call."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            cached = metadata_cache.get()
            if cached is not None:
                response = Response(cached)
                response["Cache-Control"] = "s-maxage=86400, stale-while-revalidate=3600"
                return response
        except Exception:
            logger.warning("Metadata Redis read failed, falling back to DB")

        return self._from_db()

    def _from_db(self):
        try:
            data = build_metadata_payload()

            try:
                metadata_cache.set(data)
                logger.info("Metadata API served from DB and cached")
            except Exception:
                logger.warning("Failed to write metadata to Redis cache")

            response = Response(data)
            response["Cache-Control"] = "s-maxage=86400, stale-while-revalidate=3600"
            return response
        except Exception:
            logger.exception("Metadata DB query failed")
            return Response({"error": "Service unavailable"}, status=503)
