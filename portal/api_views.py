"""REST API for admin utilities (YouTube, health check)."""

import json
import logging
from datetime import datetime, timezone as dt_tz

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import Categories, News, Topics, Videopublishers, Videos
from .youtube import fetch_video_data, fetch_channel_icon, validate_youtube_shorts_url

logger = logging.getLogger(__name__)


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


def _query_flag(request, key='all'):
    raw = request.GET.get(key)
    if raw is None:
        return False
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def _split_csv(raw_value):
    if not raw_value:
        return []
    return [item.strip() for item in str(raw_value).split(',') if item.strip()]


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def news_data(request):
    # Default remains empty unless explicitly requested by query flag.
    if not _query_flag(request):
        return Response({'items': [], 'count': 0})

    items = list(
        News.objects
        .exclude(source__isnull=True)
        .exclude(source='')
        .values_list('source', flat=True)
    )
    return Response({'items': items, 'count': len(items)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def videos_data(request):
    # Default remains empty unless explicitly requested by query flag.
    if not _query_flag(request):
        return Response({'items': [], 'count': 0})

    items = list(
        Videos.objects
        .exclude(videourl__isnull=True)
        .exclude(videourl='')
        .values_list('videourl', flat=True)
    )
    return Response({'items': items, 'count': len(items)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def categories_data(request):
    qs = (
        Categories.objects
        .filter(enabled=True)
        .only('id', 'name', 'enabled', 'order', 'live_feed_type')
        .order_by('order', 'id')
    )

    live_feed_type_raw = request.GET.get('live_feed_type', '').strip()
    if live_feed_type_raw:
        try:
            qs = qs.filter(live_feed_type=int(live_feed_type_raw))
        except ValueError:
            return Response({'error': 'live_feed_type must be an integer'}, status=400)

    skip_names = _split_csv(request.GET.get('skip_names') or request.GET.get('exclude_names'))
    if skip_names:
        qs = qs.exclude(name__in=skip_names)

    skip_contains = _split_csv(request.GET.get('skip_contains'))
    for term in skip_contains:
        qs = qs.exclude(name__icontains=term)

    items = [
        {
            'id': int(category.id),
            'name': str(category.name or ''),
            'enabled': bool(category.enabled),
            'order': int(category.order or 0),
            'live_feed_type': int(getattr(category, 'live_feed_type', 0) or 0),
        }
        for category in qs
    ]
    return Response({'items': items, 'count': len(items)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def topics_data(request):
    qs = (
        Topics.objects
        .filter(enabled=True)
        .only('id', 'name', 'order', 'enabled', 'image')
        .order_by('order', 'id')
    )
    items = [
        {
            'id': int(topic.id),
            'name': str(topic.name or ''),
            'order': int(topic.order or 0),
            'enabled': bool(topic.enabled),
            'image': topic.image,
        }
        for topic in qs
    ]
    return Response({'items': items, 'count': len(items)})


@staff_member_required
@require_POST
def youtube_fetch(request):
    try:
        body = json.loads(request.body)
        url = body.get('url', '').strip()
        if not url:
            return JsonResponse({'error': 'URL is required'}, status=400)

        validate_youtube_shorts_url(url)
        data = fetch_video_data(url)
        publisher = _get_or_create_publisher(data['channel_title'], data.get('channel_id', ''))

        if Videos.objects.filter(videourl=data['video_url']).exists():
            return JsonResponse({'error': 'Video already exists'}, status=409)

        video = Videos.objects.create(
            title=data['title'],
            videourl=data['video_url'],
            source='YouTube',
            publisher=publisher,
            timestamp=_parse_timestamp(data.get('published_at', '')),
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

    channel_url = (
        f'https://www.youtube.com/channel/{channel_id}'
        if channel_id
        else f'https://www.youtube.com/@{channel_title.replace(" ", "")}'
    )

    try:
        return Videopublishers.objects.get(title=channel_title)
    except Videopublishers.DoesNotExist:
        icon_url = fetch_channel_icon(channel_url) or ''
        return Videopublishers.objects.create(
            title=channel_title,
            url=channel_url,
            profileiconurl=icon_url,
            platform='youtube',
        )


def _parse_timestamp(published_at):
    if not published_at:
        return timezone.now()
    try:
        dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        return dt
    except (ValueError, TypeError):
        return timezone.now()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def youtube_fetch_api(request):
    max_batch_size = 50

    # Backward-compatible single mode: POST {"url": "..."}
    url = request.data.get('url', '')
    url = url.strip() if isinstance(url, str) else ''

    # New batch mode: POST {"urls": ["...", "..."]}
    urls_payload = request.data.get('urls', None)
    if urls_payload is None:
        if not url:
            return Response({'error': 'URL is required'}, status=400)
        urls = [url]
        batch_mode = False
    else:
        if not isinstance(urls_payload, list):
            return Response({'error': '"urls" must be an array of YouTube URLs'}, status=400)
        cleaned = []
        for item in urls_payload:
            if isinstance(item, str):
                candidate = item.strip()
            elif item is None:
                candidate = ''
            else:
                candidate = str(item).strip()
            if candidate:
                cleaned.append(candidate)
        if not cleaned:
            return Response({'error': '"urls" must contain at least one non-empty URL'}, status=400)
        if len(cleaned) > max_batch_size:
            return Response({'error': f'"urls" supports up to {max_batch_size} URLs per request'}, status=400)
        urls = cleaned
        batch_mode = True

    # Keep legacy behavior exactly for single-item requests.
    if not batch_mode:
        try:
            validate_youtube_shorts_url(urls[0])
            data = fetch_video_data(urls[0])
            publisher = _get_or_create_publisher(data['channel_title'], data.get('channel_id', ''))

            if Videos.objects.filter(videourl=data['video_url']).exists():
                return Response({'error': 'Video already exists'}, status=409)

            video = Videos.objects.create(
                title=data['title'],
                videourl=data['video_url'],
                source='YouTube',
                publisher=publisher,
                timestamp=_parse_timestamp(data.get('published_at', '')),
                score=data.get('score', 0),
                thumbnailurl=data['thumbnail_url'],
            )

            return Response({
                'id': video.id,
                'title': video.title,
                'videourl': video.videourl,
                'thumbnailurl': video.thumbnailurl,
                'publisher': publisher.title if publisher else None,
                'timestamp': video.timestamp.isoformat(),
            }, status=201)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('YouTube fetch API failed')
            return Response({'error': str(e)}, status=500)

    # Batch mode returns per-item outcomes and continues on errors.
    seen = set()
    unique_urls = []
    for item_url in urls:
        if item_url in seen:
            continue
        seen.add(item_url)
        unique_urls.append(item_url)

    results = []
    created = 0
    duplicate = 0
    failed = 0

    for item_url in unique_urls:
        try:
            validate_youtube_shorts_url(item_url)
            data = fetch_video_data(item_url)
            publisher = _get_or_create_publisher(data['channel_title'], data.get('channel_id', ''))

            if Videos.objects.filter(videourl=data['video_url']).exists():
                duplicate += 1
                results.append({
                    'url': data['video_url'],
                    'status': 'duplicate',
                    'error': 'Video already exists',
                })
                continue

            video = Videos.objects.create(
                title=data['title'],
                videourl=data['video_url'],
                source='YouTube',
                publisher=publisher,
                timestamp=_parse_timestamp(data.get('published_at', '')),
                score=data.get('score', 0),
                thumbnailurl=data['thumbnail_url'],
            )
            created += 1
            results.append({
                'url': video.videourl,
                'status': 'created',
                'id': video.id,
                'title': video.title,
            })
        except ValueError as e:
            failed += 1
            results.append({
                'url': item_url,
                'status': 'invalid',
                'error': str(e),
            })
        except Exception as e:
            failed += 1
            logger.exception('YouTube batch add failed for URL: %s', item_url)
            results.append({
                'url': item_url,
                'status': 'failed',
                'error': str(e),
            })

    total = len(unique_urls)
    response_status = 201 if created == total else 207
    return Response({
        'mode': 'batch',
        'total': total,
        'created': created,
        'duplicate': duplicate,
        'failed': failed,
        'results': results,
    }, status=response_status)
