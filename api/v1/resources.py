import logging

from django.db.models import F, Window
from django.db.models.functions import RowNumber
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from portal.models import (
    News, Videos, Categories, Topics, Divisions, Videopublishers, Sourcealias,
)
from .cache import SortedSetCache, MetadataCache
from .serializers import (
    NewsDetailSerializer, VideoDetailSerializer,
    CategorySerializer, TopicSerializer, DivisionSerializer, VideoPublisherSerializer,
    SourceAliasSerializer,
)
from .views import (
    LIST_CACHE_CONTROL,
    MAX_LIMIT,
    _parse_int,
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


def main_feed_news():
    """News for the main feed: division news and separate-feed categories have their own feeds."""
    return News.objects.filter(divisionid__isnull=True).exclude(categoryid__separate_feed=True)


news_cache = SortedSetCache(prefix="news", model=News, serialize_fn=_news_serializer, queryset=main_feed_news)
video_cache = SortedSetCache(prefix="video", model=Videos, serialize_fn=_video_serializer)
metadata_cache = MetadataCache()


def build_metadata_payload():
    return {
        "categories": CategorySerializer(
            Categories.objects.filter(enabled=True).order_by("order"),
            many=True,
        ).data,
        "topics": TopicSerializer(
            Topics.objects.filter(enabled=True).order_by("order"),
            many=True,
        ).data,
        "divisions": DivisionSerializer(
            Divisions.objects.all().order_by("order"),
            many=True,
        ).data,
        "publishers": VideoPublisherSerializer(
            Videopublishers.objects.all(),
            many=True,
        ).data,
        "source_aliases": SourceAliasSerializer(
            Sourcealias.objects.all(),
            many=True,
        ).data,
    }


def rebuild_metadata_cache():
    data = build_metadata_payload()
    metadata_cache.set(data)
    logger.info("Metadata cache rebuild completed")
    return data


class NewsListView(CachedListView):
    cache = news_cache
    model = News

    def get(self, request):
        filters = {}
        for param, field in (("category", "categoryid"), ("division", "divisionid")):
            raw = request.query_params.get(param)
            if raw is None:
                continue
            if not raw.isdigit():
                return Response({"error": f"{param} must be an integer"}, status=400)
            filters[field] = int(raw)

        if not filters:
            return super().get(request)

        response = self._fallback(request, News.objects.filter(**filters))
        response["Cache-Control"] = LIST_CACHE_CONTROL
        return response


class NewsByDivisionView(APIView):
    """Latest `limit` news of every division in one call, for the Divisions tab."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = _parse_int(request.query_params.get("limit"), default=10, min_val=1, max_val=MAX_LIMIT)
        latest_first = [F("timestamp").desc(), F("id").desc()]
        qs = (
            News.objects.filter(divisionid__isnull=False)
            .annotate(rank=Window(RowNumber(), partition_by=F("divisionid"), order_by=latest_first))
            .filter(rank__lte=limit)
            .order_by(*latest_first)
        )
        response = Response({"items": [_news_serializer(obj) for obj in qs]})
        response["Cache-Control"] = LIST_CACHE_CONTROL
        return response


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


