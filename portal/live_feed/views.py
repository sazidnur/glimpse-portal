import json
import time
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.template.response import TemplateResponse
from django.contrib import admin

from portal.models import Categories
from .manager import hub_manager, HUBS
from .models import LiveFeedLog


@staff_member_required
@require_GET
def dashboard_view(request):
    categories = list(
        Categories.objects
        .filter(live_feed_type__gt=0)
        .order_by('order', 'id')
        .values('id', 'name', 'enabled', 'order', 'live_feed_type')
    )

    context = {
        **admin.site.each_context(request),
        'title': 'Live Feed Manager',
        'hubs': list(HUBS.keys()),
        'hub_info': HUBS,
        'categories': categories,
        'categories_json': json.dumps(categories),
    }
    return TemplateResponse(request, 'admin/live_feed/dashboard.html', context)


@staff_member_required
@require_GET
def api_hubs(request):
    refresh = request.GET.get('refresh', '').strip().lower() in {'1', 'true', 'yes'}
    if refresh:
        hub = request.GET.get('hub', 'all')
        hub_manager.request_live_users(hub)
        # Give socket handlers a brief moment to process hub_users replies.
        time.sleep(0.3)

    states = hub_manager.get_hub_states()
    return JsonResponse({'hubs': states})


@staff_member_required
@require_POST
def api_connect(request):
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    hub = data.get('hub', 'all')

    if hub == 'all':
        results = hub_manager.connect_all()
        return JsonResponse({'success': True, 'results': results})
    else:
        result = hub_manager.connect_hub(hub)
        return JsonResponse(result)


@staff_member_required
@require_POST
def api_disconnect(request):
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    hub = data.get('hub', 'all')

    if hub == 'all':
        results = hub_manager.disconnect_all()
        return JsonResponse({'success': True, 'results': results})
    else:
        result = hub_manager.disconnect_hub(hub)
        return JsonResponse(result)


@staff_member_required
@require_POST
def api_publish(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    hub = data.get('hub', 'all')
    category_id = data.get('category_id')
    title = data.get('title', '').strip()
    impact = data.get('impact', 0)
    timestamp = data.get('timestamp')

    if not category_id:
        return JsonResponse({'error': 'category_id required'}, status=400)
    if not title:
        return JsonResponse({'error': 'title required'}, status=400)

    try:
        category_id = int(category_id)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'category_id must be integer'}, status=400)

    category = Categories.objects.filter(
        id=category_id,
        live_feed_type__gt=0,
        enabled=True
    ).first()

    if not category:
        return JsonResponse({'error': 'Category not found or not a live feed category'}, status=404)

    result = hub_manager.publish_item(
        hub=hub,
        category_id=category_id,
        title=title,
        impact=int(impact),
        timestamp=timestamp
    )

    return JsonResponse(result)


@staff_member_required
@require_GET
def api_logs(request):
    hub = request.GET.get('hub', '')
    limit = min(int(request.GET.get('limit', 100)), 500)
    since = request.GET.get('since')

    qs = LiveFeedLog.objects.all()

    if hub and hub != 'all':
        qs = qs.filter(hub=hub)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            qs = qs.filter(created_at__gt=since_dt)
        except ValueError:
            pass

    logs = list(
        qs.order_by('-created_at')[:limit]
        .values('id', 'hub', 'event_type', 'level', 'message', 'details', 'created_at')
    )

    for log in logs:
        log['created_at'] = log['created_at'].isoformat()
        log['level_display'] = dict(LiveFeedLog.LogLevel.choices).get(log['level'], 'Info')

    return JsonResponse({'logs': logs})


@staff_member_required
@require_POST
def api_clear_logs(request):
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    hub = data.get('hub')

    if hub and hub != 'all':
        count, _ = LiveFeedLog.objects.filter(hub=hub).delete()
    else:
        count, _ = LiveFeedLog.objects.all().delete()

    return JsonResponse({'deleted': count})


@staff_member_required
@require_GET
def api_stream(request):
    hub = request.GET.get('hub', 'apac')
    limit = min(int(request.GET.get('limit', 100)), 500)

    if hub not in HUBS:
        return JsonResponse({'error': 'Invalid hub'}, status=400)

    items = hub_manager._get_feed_items(hub, limit)
    snapshot = hub_manager.get_snapshot(hub)

    return JsonResponse({
        'hub': hub,
        'items': items,
        'snapshot': snapshot,
    })


@staff_member_required
@require_GET
def api_costs(request):
    costs = hub_manager.get_costs()
    return JsonResponse(costs)


@staff_member_required
@require_POST
def api_reset_costs(request):
    hub_manager.reset_costs()
    return JsonResponse({'success': True})


@staff_member_required
@require_GET
def api_categories(request):
    categories = list(
        Categories.objects
        .filter(live_feed_type__gt=0)
        .order_by('order', 'id')
        .values('id', 'name', 'enabled', 'order', 'live_feed_type')
    )
    return JsonResponse({'categories': categories})

