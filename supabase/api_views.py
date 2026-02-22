"""
REST API for WordPress News Integration and Admin utilities.
"""

import json
import logging

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.apps import apps
from django.contrib.admin.views.decorators import staff_member_required
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import News
from .serializers import NewsListSerializer
from .youtube import fetch_video_data, fetch_channel_icon

logger = logging.getLogger(__name__)

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


@staff_member_required
@require_POST
def youtube_fetch(request):
    try:
        body = json.loads(request.body)
        url = body.get('url', '').strip()
        if not url:
            return JsonResponse({'error': 'URL is required'}, status=400)

        data = fetch_video_data(url)
        publisher = _get_or_create_publisher(data['channel_title'], data.get('channel_id', ''))

        Videos = apps.get_model('supabase', 'Videos')
        video = Videos.objects.using('supabase').create(
            title=data['title'],
            videourl=data['video_url'],
            source='YouTube',
            publisher=publisher,
            timestamp=timezone.now(),
            score=data.get('score', 0),
            thumbnailurl=data['thumbnail_url'],
        )

        return JsonResponse({
            'id': video.id,
            'title': video.title,
            'videourl': video.videourl,
            'thumbnailurl': video.thumbnailurl,
            'publisher': publisher.title if publisher else None,
        })

    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        logger.exception('YouTube fetch failed')
        return JsonResponse({'error': str(e)}, status=500)


def _get_or_create_publisher(channel_title, channel_id):
    if not channel_title:
        return None

    Videopublishers = apps.get_model('supabase', 'Videopublishers')
    channel_url = (
        f'https://www.youtube.com/channel/{channel_id}'
        if channel_id
        else f'https://www.youtube.com/@{channel_title.replace(" ", "")}'
    )

    try:
        return Videopublishers.objects.using('supabase').get(title=channel_title)
    except Videopublishers.DoesNotExist:
        icon_url = fetch_channel_icon(channel_url) or ''
        return Videopublishers.objects.using('supabase').create(
            title=channel_title,
            url=channel_url,
            profileiconurl=icon_url,
            platform='youtube',
        )
