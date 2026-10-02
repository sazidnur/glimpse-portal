from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from portal.search import news_index

from .views import _parse_int

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_PAGE = 50


class NewsSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = ' '.join(request.query_params.get('q', '').split())[:news_index.MAX_QUERY_LENGTH]
        if len(query) < news_index.MIN_QUERY_LENGTH:
            return Response({'error': f'q must be at least {news_index.MIN_QUERY_LENGTH} characters'}, status=400)
        page = _parse_int(request.query_params.get('page'), default=1, min_val=1, max_val=MAX_PAGE)
        limit = _parse_int(request.query_params.get('limit'), default=DEFAULT_LIMIT, min_val=1, max_val=MAX_LIMIT)
        result, source = news_index.search_with_fallback(query, page=page, limit=limit)
        response = Response(result)
        response['Cache-Control'] = 's-maxage=120'
        response['X-SR'] = source
        return response
