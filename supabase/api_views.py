"""
REST API for WordPress News Integration.

Endpoints:
- GET /api/news/   - Latest 20 news (Token auth)
- GET /api/health/ - Health check (no auth)

Required Header: Authorization: Token <your-token>
"""

from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import News
from .serializers import NewsListSerializer

# Cache timeout (5 minutes)
CACHE_TIMEOUT = 300


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def news_list(request):
    """
    Get latest 20 news articles.
    
    Response: [{title, summary, source, imageurl, time_ago}, ...]
    """
    cache_key = 'api:news:latest:20'
    
    # Try cache first
    cached = cache.get(cache_key)
    if cached is not None:
        response = Response(cached)
        response['X-Cache'] = 'HIT'
        return response
    
    # Fetch from database
    news = News.objects.order_by('-timestamp')[:20]
    data = NewsListSerializer(news, many=True).data
    
    # Cache for 5 minutes
    cache.set(cache_key, data, CACHE_TIMEOUT)
    
    response = Response(data)
    response['X-Cache'] = 'MISS'
    return response


@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    Health check endpoint (no auth required).
    
    Endpoint: GET /api/health/
    
    Used for monitoring and load balancer health checks.
    Returns basic status without exposing sensitive data.
    """
    return Response({
        'status': 'healthy',
        'service': 'glimpse-api',
        'version': '1.0.0',
    })
