"""REST API for admin utilities (YouTube, health check)."""

import json
import logging
from datetime import datetime, timezone as dt_tz
import urllib.request
import urllib.error

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.apps import apps
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.db import connections, transaction
from django.db.utils import DatabaseError, IntegrityError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from api.v1.cache import worker_token_handler
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

        Videos = apps.get_model('supabase', 'Videos')
        if Videos.objects.using('supabase').filter(videourl=data['video_url']).exists():
            return JsonResponse({'error': 'Video already exists'}, status=409)

        video = Videos.objects.using('supabase').create(
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


def _parse_json_or_form(request):
    if request.content_type and 'application/json' in request.content_type.lower():
        return json.loads(request.body or b'{}')
    return request.POST.dict()


def _worker_context(request):
    """Get Worker base URL and user agent from request/settings."""
    worker_base = (settings.WORKER_BASE_URL or '').rstrip('/')
    user_agent = (
        request.META.get('HTTP_USER_AGENT', '').strip()
        or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    )
    if not worker_base:
        raise ValueError('WORKER_BASE_URL must be configured')
    return worker_base, user_agent


def _worker_request_json(url, method='GET', headers=None, payload=None, timeout=10):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    request_headers = dict(headers or {})
    request_headers.setdefault('Accept', 'application/json')
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8') if resp else ''
            parsed = json.loads(body) if body else {}
            return int(getattr(resp, 'status', 200)), parsed
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8')
        except Exception:
            detail = ''
        try:
            parsed = json.loads(detail) if detail else {'error': exc.reason}
        except json.JSONDecodeError:
            parsed = {'error': exc.reason, 'detail': detail[:500]}
        return int(exc.code), parsed


def _worker_authed_json(request, method, path, payload=None, query=''):
    """Make authenticated request to Worker using central token handler."""
    worker_base, user_agent = _worker_context(request)
    
    # Get token from central handler (handles caching automatically)
    token, expires_in, error = worker_token_handler.get_token()
    if error:
        return 503, {'error': error}

    url = f'{worker_base}{path}'
    if query:
        url = f'{url}?{query}'
    return _worker_request_json(
        url,
        method=method,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
            'User-Agent': user_agent,
        },
        payload=payload,
    )


def _category_to_live_payload(category):
    if isinstance(category, dict):
        return {
            'category_id': int(category.get('id')),
            'name': str(category.get('name') or ''),
            'enabled': bool(category.get('enabled')),
            'live_feed_type': int(category.get('live_feed_type') or 0),
        }
    return {
        'category_id': int(category.id),
        'name': str(category.name or ''),
        'enabled': bool(category.enabled),
        'live_feed_type': int(getattr(category, 'live_feed_type', 0) or 0),
    }


def _supabase_conn():
    return connections['supabase']


def _live_feed_schema_error():
    return (
        "Supabase column categories.live_feed_type is missing. "
        "Run: ALTER TABLE categories ADD COLUMN live_feed_type integer NOT NULL DEFAULT 0;"
    )


def _live_feed_sequence_error():
    return (
        "Supabase categories id sequence is out of sync. Run once: "
        "SELECT setval(pg_get_serial_sequence('categories','id'), "
        "COALESCE((SELECT MAX(id) FROM categories), 1), true);"
    )


def _categories_has_live_feed_type():
    with _supabase_conn().cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'categories'
              AND column_name = 'live_feed_type'
            LIMIT 1
            """
        )
        return cursor.fetchone() is not None


def _dictfetchall(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _fetch_live_categories_rows():
    with _supabase_conn().cursor() as cursor:
        cursor.execute(
            """
            SELECT id, name, enabled, "order", COALESCE(live_feed_type, 0) AS live_feed_type
            FROM categories
            WHERE COALESCE(live_feed_type, 0) > 0
            ORDER BY "order" ASC, id ASC
            """
        )
        rows = _dictfetchall(cursor)
    for row in rows:
        row['id'] = int(row['id'])
        row['enabled'] = bool(row['enabled'])
        row['order'] = int(row.get('order') or 0)
        row['live_feed_type'] = int(row.get('live_feed_type') or 0)
    return rows


def _fetch_category_row(category_id):
    with _supabase_conn().cursor() as cursor:
        cursor.execute(
            """
            SELECT id, name, enabled, "order", COALESCE(live_feed_type, 0) AS live_feed_type
            FROM categories
            WHERE id = %s
            LIMIT 1
            """,
            [int(category_id)],
        )
        rows = _dictfetchall(cursor)
    if not rows:
        return None
    row = rows[0]
    row['id'] = int(row['id'])
    row['enabled'] = bool(row['enabled'])
    row['order'] = int(row.get('order') or 0)
    row['live_feed_type'] = int(row.get('live_feed_type') or 0)
    return row


@staff_member_required
@require_POST
def live_feed_publish(request):
    """Publish a live-feed item to the Cloudflare Worker control endpoint."""
    try:
        body = _parse_json_or_form(request)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    category_id_raw = body.get('category_id')
    title_raw = body.get('title')
    timestamp = body.get('timestamp')
    impact_raw = body.get('impact', 0)
    payload = body.get('payload')

    try:
        category_id = int(category_id_raw)
        if category_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return JsonResponse({'error': 'category_id must be a positive integer'}, status=400)

    title = str(title_raw or '').strip()
    if not title:
        return JsonResponse({'error': 'title is required'}, status=400)

    try:
        impact = int(impact_raw)
    except (TypeError, ValueError):
        impact = 0
    if impact not in (0, 1, 2):
        impact = 0

    if isinstance(payload, str):
        payload = payload.strip()
        if payload:
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return JsonResponse({'error': 'payload must be valid JSON object'}, status=400)
        else:
            payload = None

    if payload is not None and not isinstance(payload, dict):
        return JsonResponse({'error': 'payload must be a JSON object'}, status=400)

    try:
        if not _categories_has_live_feed_type():
            return JsonResponse({'error': _live_feed_schema_error()}, status=503)
        category = _fetch_category_row(category_id)
    except DatabaseError as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    if not category:
        return JsonResponse({'error': 'Category not found'}, status=404)

    live_feed_type = int(category.get('live_feed_type') or 0)
    if live_feed_type == 0:
        return JsonResponse({'error': 'Category is not configured as live feed'}, status=400)
    if not bool(category.get('enabled')):
        return JsonResponse({'error': 'Category is disabled'}, status=400)

    publish_payload = {
        'category_id': category_id,
        'title': title,
        'impact': impact,
    }
    if timestamp:
        publish_payload['timestamp'] = timestamp
    if payload is not None:
        publish_payload['payload'] = payload

    try:
        status, response_data = _worker_authed_json(
            request,
            'POST',
            '/api/v1/live-feed/admin/items',
            payload=publish_payload,
        )
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    except Exception as exc:
        logger.exception('Live feed publish failed')
        return JsonResponse({'error': str(exc)}, status=500)

    return JsonResponse(response_data, status=status)


@staff_member_required
@require_http_methods(['GET'])
def live_feed_token(request):
    """Issue a Worker JWT for admin live-feed WebSocket usage."""
    token, expires_in, error = worker_token_handler.get_token()
    if error:
        return JsonResponse({'error': error}, status=503)
    return JsonResponse({
        'token': token,
        'token_type': 'Bearer',
        'expires_in': expires_in,
    })


@staff_member_required
@require_http_methods(['GET', 'POST'])
def live_feed_categories(request):
    try:
        if not _categories_has_live_feed_type():
            return JsonResponse({'error': _live_feed_schema_error()}, status=503)
    except DatabaseError as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    if request.method == 'GET':
        try:
            return JsonResponse({'items': _fetch_live_categories_rows()}, status=200)
        except DatabaseError as exc:
            return JsonResponse({'error': str(exc)}, status=500)

    try:
        body = _parse_json_or_form(request)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    name = str(body.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'name is required'}, status=400)

    live_feed_type = body.get('live_feed_type')
    try:
        live_feed_type = int(live_feed_type)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'live_feed_type must be an integer'}, status=400)
    if live_feed_type <= 0:
        return JsonResponse({'error': 'live_feed_type must be > 0 for live category'}, status=400)

    enabled = body.get('enabled', True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        enabled = bool(enabled)

    order_raw = body.get('order', 0)
    try:
        order = int(order_raw)
    except (TypeError, ValueError):
        order = 0

    try:
        with transaction.atomic(using='supabase'):
            with _supabase_conn().cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO categories (name, enabled, "order", live_feed_type)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    [name, enabled, order, live_feed_type],
                )
                next_id = int(cursor.fetchone()[0])
        category_row = _fetch_category_row(next_id)
    except IntegrityError as exc:
        message = str(exc)
        if 'duplicate key value violates unique constraint "category_pkey"' in message:
            return JsonResponse({'error': _live_feed_sequence_error()}, status=500)
        return JsonResponse({'error': message}, status=500)
    except DatabaseError as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    # Sync to DO (Durable Object)
    payload = _category_to_live_payload(category_row)
    try:
        status, data = _worker_authed_json(
            request,
            'POST',
            '/api/v1/live-feed/admin/categories/upsert',
            payload=payload,
        )
    except Exception as exc:
        # DO sync failed - rollback Supabase insert
        try:
            with _supabase_conn().cursor() as cursor:
                cursor.execute("DELETE FROM categories WHERE id = %s", [int(category_row['id'])])
        except Exception:
            pass
        return JsonResponse({
            'error': f'DO sync failed: {exc}',
            'failed_at': 'worker_do',
            'supabase_rolled_back': True,
        }, status=500)

    if status >= 400:
        # DO rejected - rollback Supabase insert
        try:
            with _supabase_conn().cursor() as cursor:
                cursor.execute("DELETE FROM categories WHERE id = %s", [int(category_row['id'])])
        except Exception:
            pass
        return JsonResponse({
            'error': data.get('error', 'DO rejected category'),
            'failed_at': 'worker_do',
            'supabase_rolled_back': True,
            'do_status': status,
            'do_response': data,
        }, status=status)

    return JsonResponse({
        'id': int(category_row['id']),
        'name': category_row['name'],
        'enabled': bool(category_row['enabled']),
        'order': int(category_row['order']),
        'live_feed_type': int(category_row['live_feed_type']),
        'synced': {'supabase': True, 'do': True},
    }, status=201)


@staff_member_required
@require_POST
def live_feed_category_update(request, category_id):
    try:
        if not _categories_has_live_feed_type():
            return JsonResponse({'error': _live_feed_schema_error()}, status=503)
        category_row = _fetch_category_row(category_id)
    except DatabaseError as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    if not category_row:
        return JsonResponse({'error': 'Category not found'}, status=404)

    try:
        body = _parse_json_or_form(request)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    new_name = str(body.get('name', category_row['name']) or '').strip()
    if not new_name:
        return JsonResponse({'error': 'name is required'}, status=400)

    enabled_in = body.get('enabled', category_row['enabled'])
    if isinstance(enabled_in, str):
        new_enabled = enabled_in.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        new_enabled = bool(enabled_in)

    try:
        new_order = int(body.get('order', category_row['order']))
    except (TypeError, ValueError):
        new_order = 0

    try:
        new_live_feed_type = int(body.get('live_feed_type', category_row['live_feed_type']))
        if new_live_feed_type < 0:
            new_live_feed_type = 0
    except (TypeError, ValueError):
        return JsonResponse({'error': 'live_feed_type must be an integer'}, status=400)

    # Step 1: Update Supabase
    try:
        with _supabase_conn().cursor() as cursor:
            cursor.execute(
                """
                UPDATE categories
                SET name = %s, enabled = %s, "order" = %s, live_feed_type = %s
                WHERE id = %s
                """,
                [new_name, new_enabled, new_order, new_live_feed_type, int(category_id)],
            )
    except DatabaseError as exc:
        return JsonResponse({
            'error': f'Supabase update failed: {exc}',
            'failed_at': 'supabase',
        }, status=500)

    updated_row = {
        'id': int(category_id),
        'name': new_name,
        'enabled': bool(new_enabled),
        'order': int(new_order),
        'live_feed_type': int(new_live_feed_type),
    }

    # Step 2: Sync to DO
    payload = _category_to_live_payload(updated_row)
    do_synced = False
    do_error = None
    try:
        status, data = _worker_authed_json(
            request,
            'POST',
            '/api/v1/live-feed/admin/categories/upsert',
            payload=payload,
        )
        if status < 400:
            do_synced = True
        else:
            do_error = data.get('error', f'DO returned {status}')
    except Exception as exc:
        do_error = str(exc)

    # Return result with sync status
    result = {
        'id': int(updated_row['id']),
        'name': updated_row['name'],
        'enabled': bool(updated_row['enabled']),
        'order': int(updated_row['order']),
        'live_feed_type': int(updated_row['live_feed_type']),
        'synced': {'supabase': True, 'do': do_synced},
    }
    if do_error:
        result['do_error'] = do_error
        result['warning'] = 'Supabase updated but DO sync failed'
    return JsonResponse(result, status=200)


@staff_member_required
@require_POST
def live_feed_category_delete(request, category_id):
    try:
        if not _categories_has_live_feed_type():
            return JsonResponse({'error': _live_feed_schema_error()}, status=503)
        category = _fetch_category_row(category_id)
    except DatabaseError as exc:
        return JsonResponse({
            'error': f'Supabase query failed: {exc}',
            'failed_at': 'supabase',
        }, status=500)

    if not category:
        return JsonResponse({'error': 'Category not found'}, status=404)

    # Step 1: Delete from DO first (can rollback easily)
    do_deleted = False
    do_error = None
    try:
        status, data = _worker_authed_json(
            request,
            'POST',
            '/api/v1/live-feed/admin/categories/delete',
            payload={'category_id': int(category_id)},
        )
        if status < 400:
            do_deleted = True
        else:
            do_error = data.get('error', f'DO returned {status}')
    except Exception as exc:
        do_error = str(exc)

    if not do_deleted:
        return JsonResponse({
            'error': f'DO delete failed: {do_error}',
            'failed_at': 'worker_do',
            'supabase_unchanged': True,
        }, status=500)

    # Step 2: Delete from Supabase
    try:
        with _supabase_conn().cursor() as cursor:
            cursor.execute("DELETE FROM categories WHERE id = %s", [int(category_id)])
    except DatabaseError as exc:
        return JsonResponse({
            'error': f'Supabase delete failed: {exc}',
            'failed_at': 'supabase',
            'do_deleted': True,
            'warning': 'DO deleted but Supabase failed - data inconsistent!',
        }, status=500)

    return JsonResponse({
        'deleted': int(category_id),
        'synced': {'supabase': True, 'do': True},
    }, status=200)


@staff_member_required
@require_http_methods(['GET'])
def live_feed_items(request):
    category_id = request.GET.get('category_id', '').strip()
    limit = request.GET.get('limit', '50').strip()
    if not category_id:
        return JsonResponse({'error': 'category_id is required'}, status=400)
    query = f'category_id={category_id}&limit={limit}'
    try:
        status, data = _worker_authed_json(
            request,
            'GET',
            '/api/v1/live-feed/admin/items/list',
            query=query,
        )
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)
    return JsonResponse(data, status=status)


@staff_member_required
@require_http_methods(['GET'])
def live_feed_stats(request):
    """Fetch live feed DO analytics from Cloudflare Analytics Engine."""
    import urllib.request
    import urllib.error
    
    account_id = getattr(settings, 'CF_ACCOUNT_ID', '')
    token = getattr(settings, 'CF_ANALYTICS_TOKEN', '')
    if not account_id or not token:
        return JsonResponse({'error': 'CF_ACCOUNT_ID and CF_ANALYTICS_TOKEN not configured'}, status=503)

    # Supported ranges
    RANGES = {
        '10m': ("'10' MINUTE", "'1' MINUTE", "minute"),
        '30m': ("'30' MINUTE", "'1' MINUTE", "minute"),
        '1h':  ("'1' HOUR",    "'1' MINUTE", "minute"),
        '6h':  ("'6' HOUR",    "'5' MINUTE", "minute"),
        '24h': ("'24' HOUR",   "'1' HOUR",   "hour"),
        '7d':  ("'7' DAY",     "'1' HOUR",   "hour"),
        '30d': ("'30' DAY",    "'1' DAY",    "day"),
    }
    range_key = request.GET.get('range', '10m')
    if range_key not in RANGES:
        range_key = '10m'
    where_interval, bucket_interval, unit = RANGES[range_key]

    # Query DO stats (index1 = 'do_live_feed')
    # doubles: [connects, messages, publishes, broadcasts, load_older]
    sql = (
        "SELECT"
        f" toStartOfInterval(timestamp, INTERVAL {bucket_interval}) AS ts,"
        " SUM(double1) AS connects,"
        " SUM(double2) AS messages,"
        " SUM(double3) AS publishes,"
        " SUM(double4) AS broadcasts,"
        " SUM(double5) AS load_older"
        " FROM cache_analytics"
        f" WHERE timestamp >= NOW() - INTERVAL {where_interval}"
        " AND index1 = 'do_live_feed'"
        " GROUP BY ts ORDER BY ts ASC"
    )

    sql_endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/analytics_engine/sql"

    try:
        req = urllib.request.Request(
            sql_endpoint,
            data=sql.encode(),
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'text/plain',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        return JsonResponse({'error': f'CF API HTTP {e.code}: {e.reason}', 'detail': body}, status=502)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    rows = data.get('data', [])
    if not rows:
        now = datetime.now(dt_tz.utc)
        return JsonResponse({
            'series': [],
            'totals': {'connects': 0, 'messages': 0, 'publishes': 0, 'broadcasts': 0, 'load_older': 0},
            'unit': unit,
            'range': range_key,
            'from': '',
            'to': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'message': 'No DO analytics data yet.',
        })

    series = []
    for row in rows:
        ts_raw = row.get('ts', '')
        ts_iso = ts_raw.replace(' ', 'T') + 'Z' if ts_raw and 'T' not in ts_raw else ts_raw
        series.append({
            'ts': ts_iso,
            'connects': int(float(row.get('connects') or 0)),
            'messages': int(float(row.get('messages') or 0)),
            'publishes': int(float(row.get('publishes') or 0)),
            'broadcasts': int(float(row.get('broadcasts') or 0)),
            'load_older': int(float(row.get('load_older') or 0)),
        })

    totals = {
        'connects': sum(s['connects'] for s in series),
        'messages': sum(s['messages'] for s in series),
        'publishes': sum(s['publishes'] for s in series),
        'broadcasts': sum(s['broadcasts'] for s in series),
        'load_older': sum(s['load_older'] for s in series),
    }

    now = datetime.now(dt_tz.utc)
    return JsonResponse({
        'series': series,
        'totals': totals,
        'unit': unit,
        'range': range_key,
        'from': series[0]['ts'] if series else '',
        'to': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
    })


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

    Videos = apps.get_model('supabase', 'Videos')

    # Keep legacy behavior exactly for single-item requests.
    if not batch_mode:
        try:
            validate_youtube_shorts_url(urls[0])
            data = fetch_video_data(urls[0])
            publisher = _get_or_create_publisher(data['channel_title'], data.get('channel_id', ''))

            if Videos.objects.using('supabase').filter(videourl=data['video_url']).exists():
                return Response({'error': 'Video already exists'}, status=409)

            video = Videos.objects.using('supabase').create(
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

            if Videos.objects.using('supabase').filter(videourl=data['video_url']).exists():
                duplicate += 1
                results.append({
                    'url': data['video_url'],
                    'status': 'duplicate',
                    'error': 'Video already exists',
                })
                continue

            video = Videos.objects.using('supabase').create(
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
