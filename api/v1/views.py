import logging

from rest_framework.permissions import IsAuthenticated
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
    # Require DRF token auth for reads as well as writes.
    permission_classes = [IsAuthenticated]
    cache = None
    serializer_class = None
    model = None

    def get(self, request):
        try:
            if request.query_params.get("all", "").lower() == "true":
                result = self.cache.get_all(max_items=MAX_ALL)
                response = Response(result)
            else:
                page = _parse_int(request.query_params.get("page"), default=1, min_val=1)
                limit = _parse_int(request.query_params.get("limit"), default=10, min_val=1, max_val=MAX_LIMIT)
                result = self.cache.get_paginated(page=page, limit=limit)
                response = Response(result)

            # CDN cache directive: s-maxage=1800 tells CF to cache for 30 min.
            # stale-while-revalidate=120 gives CF a 2 min grace period to serve stale
            # while revalidating in background. This works alongside cf.cacheTtl=1800
            # set in the Worker's fetchOriginGET cf options.
            response["Cache-Control"] = "s-maxage=1800, stale-while-revalidate=120"
            return response

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

        if not many:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return Response({"errors": serializer.errors}, status=400)
            obj = serializer.save()
            return Response(self.serializer_class(obj).data, status=201)

        saved, errors = [], []
        for idx, item in enumerate(request.data):
            s = self.serializer_class(data=item)
            if s.is_valid():
                saved.append(s.save())
            else:
                errors.append({"index": idx, "errors": s.errors})

        result = {
            "created": len(saved),
            "failed": len(errors),
            "items": self.serializer_class(saved, many=True).data,
        }
        if errors:
            result["errors"] = errors
        status = 201 if saved else 400
        return Response(result, status=status)


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
        return Response({"deleted": pk}, status=200)

    def _delete_batch(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list) or not ids:
            return Response({"error": "Provide a non-empty 'ids' array"}, status=400)

        existing = self.model.objects.filter(id__in=ids)
        found_ids = list(existing.values_list("id", flat=True))
        not_found = [i for i in ids if i not in found_ids]

        existing.delete()

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
