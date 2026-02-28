import logging

from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

MAX_LIMIT = 100
MAX_ALL = 10000


def _parse_int(value, default=1, min_val=None, max_val=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if min_val is not None:
        result = max(result, min_val)
    if max_val is not None:
        result = min(result, max_val)
    return result


class CachedListView(APIView):
    permission_classes = [AllowAny]
    cache = None
    serializer_class = None
    model = None

    def get(self, request):
        try:
            if request.query_params.get("all", "").lower() == "true":
                result = self.cache.get_all(max_items=MAX_ALL)
                return Response(result)

            page = _parse_int(request.query_params.get("page"), default=1, min_val=1)
            limit = _parse_int(request.query_params.get("limit"), default=10, min_val=1, max_val=MAX_LIMIT)
            result = self.cache.get_paginated(page=page, limit=limit)
            return Response(result)

        except Exception:
            logger.exception("%s list failed, falling back to DB", self.model.__name__)
            return self._fallback(request)

    def _fallback(self, request):
        try:
            page = _parse_int(request.query_params.get("page"), default=1, min_val=1)
            limit = _parse_int(request.query_params.get("limit"), default=10, min_val=1, max_val=MAX_LIMIT)
            get_all = request.query_params.get("all", "").lower() == "true"

            qs = self.model.objects.order_by("-timestamp")
            total = qs.count()

            if get_all:
                qs = qs[:MAX_ALL]
            else:
                start = (page - 1) * limit
                qs = qs[start:start + limit]

            data = self.serializer_class(qs, many=True).data
            return Response({
                "items": data,
                "total": total,
                "page": page,
                "limit": limit,
                "pages": (total + limit - 1) // limit if limit > 0 else 0,
            })
        except Exception:
            logger.exception("DB fallback also failed")
            return Response({"error": "Service unavailable"}, status=503)


class CachedCreateView(APIView):
    permission_classes = [IsAuthenticated]
    cache = None
    serializer_class = None

    def post(self, request):
        many = isinstance(request.data, list)
        serializer = self.serializer_class(data=request.data, many=many)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)

        if many:
            objects = serializer.save()
            try:
                self.cache.add_many(objects)
            except Exception as e:
                logger.warning("Failed to push %d %s items to Redis: %s", len(objects), self.cache.member_prefix, e)
            return Response({"created": len(objects), "items": self.serializer_class(objects, many=True).data}, status=201)

        obj = serializer.save()
        try:
            self.cache.add(obj)
        except Exception as e:
            logger.warning("Failed to push %s:%d to Redis: %s", self.cache.member_prefix, obj.id, e)
        return Response(self.serializer_class(obj).data, status=201)


class CachedDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    cache = None
    model = None

    def delete(self, request, pk=None):
        if pk is not None:
            return self._delete_single(pk)
        return self._delete_batch(request)

    def _delete_single(self, pk):
        try:
            obj = self.model.objects.get(id=pk)
        except self.model.DoesNotExist:
            return Response({"error": f"{self.model.__name__} not found"}, status=404)

        obj.delete()
        try:
            self.cache.delete(pk)
        except Exception as e:
            logger.warning("Failed to remove %s:%d from Redis: %s", self.cache.member_prefix, pk, e)
        return Response({"deleted": pk}, status=200)

    def _delete_batch(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list) or not ids:
            return Response({"error": "Provide a non-empty 'ids' array"}, status=400)

        existing = self.model.objects.filter(id__in=ids)
        found_ids = list(existing.values_list("id", flat=True))
        not_found = [i for i in ids if i not in found_ids]

        existing.delete()
        try:
            self.cache.delete_many(found_ids)
        except Exception as e:
            logger.warning("Failed to remove %d %s items from Redis: %s", len(found_ids), self.cache.member_prefix, e)

        result = {"deleted": found_ids, "count": len(found_ids)}
        if not_found:
            result["not_found"] = not_found
        return Response(result, status=200)


class CacheStatsView(APIView):
    permission_classes = [IsAuthenticated]
    cache = None

    def get(self, request):
        try:
            return Response(self.cache.stats())
        except Exception as e:
            return Response({"error": str(e)}, status=500)


class CacheWarmView(APIView):
    permission_classes = [IsAuthenticated]
    cache = None

    def post(self, request):
        try:
            count = self.cache.warm()
            return Response({"warmed": count})
        except Exception as e:
            return Response({"error": str(e)}, status=500)


class CacheFlushView(APIView):
    permission_classes = [IsAuthenticated]
    cache = None

    def post(self, request):
        try:
            self.cache.flush()
            return Response({"flushed": True})
        except Exception as e:
            return Response({"error": str(e)}, status=500)
