import json
import time
from datetime import datetime, timezone
from typing import Any

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.template.response import TemplateResponse
from django.contrib import admin
from django.db import OperationalError, ProgrammingError

from portal.models import Categories
from .manager import hub_manager, HUBS
from .models import LiveFeedLog, LiveFeedPipeline, LiveFeedPipelineLog, LiveFeedPublishedItem
from .pipeline_manager import pipeline_manager
from .pipelines import get_pipeline_sources, source_definition_map


def _pipeline_sources_payload():
    return [
        {
            'key': source.key,
            'label': source.label,
            'pipeline_type': source.pipeline_type,
        }
        for source in get_pipeline_sources()
    ]


def _serialize_pipeline(pipeline: LiveFeedPipeline, source_map: dict[str, Any]) -> dict:
    data = {
        'id': pipeline.id,
        'source': pipeline.source,
        'source_label': source_map.get(pipeline.source).label if source_map.get(pipeline.source) else pipeline.source,
        'pipeline_type': pipeline.pipeline_type,
        'category_id': pipeline.category_id,
        'category_name': pipeline.category.name if pipeline.category_id else '',
        'default_impact': int(pipeline.default_impact or 0),
        'config': pipeline.config if isinstance(pipeline.config, dict) else {},
        'should_run': bool(pipeline.should_run),
        'status': pipeline.status,
        'owner_instance': pipeline.owner_instance or '',
        'last_started_at': pipeline.last_started_at.isoformat() if pipeline.last_started_at else None,
        'last_stopped_at': pipeline.last_stopped_at.isoformat() if pipeline.last_stopped_at else None,
        'last_activity_at': pipeline.last_activity_at.isoformat() if pipeline.last_activity_at else None,
        'last_error': pipeline.last_error or '',
        'total_seen': int(pipeline.total_seen or 0),
        'total_published': int(pipeline.total_published or 0),
        'updated_at': pipeline.updated_at.isoformat() if pipeline.updated_at else None,
    }
    return data


def _pipeline_schema_error_response(exc: Exception) -> JsonResponse:
    return JsonResponse(
        {
            'error': (
                'Live feed pipeline schema is out of date. '
                'Run migrations (python manage.py migrate).'
            ),
            'details': str(exc),
        },
        status=503,
    )

@staff_member_required
@require_GET
def dashboard_view(request):
    # Safety net: ensure monitor is active when live feed admin is visited.
    try:
        pipeline_manager.start_monitor()
    except Exception:
        pass

    categories = [
        {
            'id': row['id'],
            'name': row['name'],
            'enabled': row['enabled'],
            'order': row['order'],
            'live_feed_type': row['live_feed_type'],
            'source': str((row.get('config') or {}).get('source', '')).strip() if isinstance(row.get('config'), dict) else '',
            'page_title': str((row.get('config') or {}).get('page_title', '')).strip() if isinstance(row.get('config'), dict) else '',
            'page_tagline': str((row.get('config') or {}).get('page_tagline', '')).strip() if isinstance(row.get('config'), dict) else '',
        }
        for row in (
            Categories.objects
            .filter(live_feed_type__gt=0)
            .order_by('order', 'id')
            .values('id', 'name', 'enabled', 'order', 'live_feed_type', 'config')
        )
    ]

    context = {
        **admin.site.each_context(request),
        'title': 'Live Feed Manager',
        'hubs': list(HUBS.keys()),
        'hub_info': HUBS,
        'categories': categories,
        'categories_json': json.dumps(categories),
        'pipeline_sources': _pipeline_sources_payload(),
        'pipeline_sources_json': json.dumps(_pipeline_sources_payload()),
    }
    return TemplateResponse(request, 'admin/live_feed/dashboard.html', context)


@staff_member_required
@require_GET
def pipeline_manager_view(request):
    context = {
        **admin.site.each_context(request),
        'title': 'Pipeline Configuration',
    }
    return TemplateResponse(request, 'admin/live_feed/pipelines.html', context)


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
@require_POST
def api_fanout_reseed(request):
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    hub = str(data.get('hub') or 'all').strip().lower() or 'all'
    if hub != 'all' and hub not in HUBS:
        return JsonResponse({'error': f'Invalid hub: {hub}'}, status=400)

    category_raw = data.get('category_id')
    try:
        category_id = int(category_raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'category_id must be integer'}, status=400)

    category = Categories.objects.filter(
        id=category_id,
        live_feed_type__gt=0,
        enabled=True,
    ).first()
    if not category:
        return JsonResponse({'error': 'Category not found or not an enabled live feed category'}, status=404)

    limit = None
    if 'limit' in data and data.get('limit') not in (None, ''):
        try:
            limit = int(data.get('limit'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'limit must be integer'}, status=400)
        if limit < 1 or limit > 500:
            return JsonResponse({'error': 'limit must be between 1 and 500'}, status=400)

    result = hub_manager.set_initial_fanout_snapshot(
        category_id=category_id,
        hub=hub,
        limit=limit,
    )
    if not result.get('success'):
        return JsonResponse(result, status=400)
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
    categories = [
        {
            'id': row['id'],
            'name': row['name'],
            'enabled': row['enabled'],
            'order': row['order'],
            'live_feed_type': row['live_feed_type'],
            'source': str((row.get('config') or {}).get('source', '')).strip() if isinstance(row.get('config'), dict) else '',
            'page_title': str((row.get('config') or {}).get('page_title', '')).strip() if isinstance(row.get('config'), dict) else '',
            'page_tagline': str((row.get('config') or {}).get('page_tagline', '')).strip() if isinstance(row.get('config'), dict) else '',
        }
        for row in (
            Categories.objects
            .filter(live_feed_type__gt=0)
            .order_by('order', 'id')
            .values('id', 'name', 'enabled', 'order', 'live_feed_type', 'config')
        )
    ]
    return JsonResponse({'categories': categories})

@staff_member_required
@require_GET
def api_pipeline_sources(request):
    return JsonResponse({'sources': _pipeline_sources_payload()})

@staff_member_required
@require_GET
def api_pipelines(request):
    source_map = source_definition_map()
    try:
        rows = (
            LiveFeedPipeline.objects
            .select_related('category')
            .order_by('-updated_at')
        )
        pipelines = [_serialize_pipeline(row, source_map) for row in rows]
    except (ProgrammingError, OperationalError) as exc:
        return _pipeline_schema_error_response(exc)
    return JsonResponse({'pipelines': pipelines})

@staff_member_required
@require_GET
def api_pipeline_logs(request):
    pipeline_id = request.GET.get('pipeline_id')
    limit = min(max(int(request.GET.get('limit', 100)), 1), 500)

    try:
        qs = LiveFeedPipelineLog.objects.select_related('pipeline')
    except (ProgrammingError, OperationalError) as exc:
        return _pipeline_schema_error_response(exc)
    if pipeline_id:
        try:
            qs = qs.filter(pipeline_id=int(pipeline_id))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'pipeline_id must be integer'}, status=400)

    logs = []
    try:
        for row in qs.order_by('-created_at')[:limit]:
            logs.append({
                'id': row.id,
                'pipeline_id': row.pipeline_id,
                'event_type': row.event_type,
                'level': row.level,
                'level_display': row.get_level_display(),
                'message': row.message,
                'details': row.details or {},
                'created_at': row.created_at.isoformat(),
            })
    except (ProgrammingError, OperationalError) as exc:
        return _pipeline_schema_error_response(exc)
    return JsonResponse({'logs': logs})


def _validate_source_and_category(source_key: str, category_id: int):
    definitions = source_definition_map()
    source = definitions.get(source_key)
    if not source:
        return None, None, JsonResponse({'error': 'Invalid pipeline source'}, status=400)

    category = Categories.objects.filter(id=category_id, enabled=True, live_feed_type__gt=0).first()
    if not category:
        return None, None, JsonResponse({'error': 'Category not found or not enabled live feed category'}, status=404)

    category_type = int(category.live_feed_type or 0)
    if category_type != int(source.pipeline_type):
        return None, None, JsonResponse({
            'error': (
                f'Category type mismatch. Source "{source.label}" requires live_feed_type={source.pipeline_type}, '
                f'but category has live_feed_type={category_type}.'
            )
        }, status=400)

    return source, category, None


def _normalize_impact(value: Any, *, default: int = 2) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(0, min(2, parsed))


def _normalize_pipeline_config(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('config must be a JSON object')

    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or '').strip()
        if not key:
            continue
        normalized[key] = raw_value

    try:
        json.dumps(normalized)
    except TypeError as exc:
        raise ValueError('config contains non-JSON-serializable values') from exc
    return normalized

@staff_member_required
@require_POST
def api_pipeline_run(request):
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    source_key = str(data.get('source') or '').strip()
    default_impact = _normalize_impact(data.get('default_impact'), default=2)
    config_payload: dict[str, Any] | None = None
    if 'config' in data:
        try:
            config_payload = _normalize_pipeline_config(data.get('config'))
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)

    category_raw = data.get('category_id')
    try:
        category_id = int(category_raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'category_id must be integer'}, status=400)

    source, category, error_response = _validate_source_and_category(source_key, category_id)
    if error_response:
        return error_response

    pipeline, _created = LiveFeedPipeline.objects.get_or_create(
        source=source.key,
        category=category,
        defaults={
            'pipeline_type': int(source.pipeline_type),
            'default_impact': default_impact,
            'config': config_payload or {},
        }
    )

    if config_payload is None:
        config_payload = pipeline.config if isinstance(pipeline.config, dict) else {}

    pipeline.pipeline_type = int(source.pipeline_type)
    pipeline.default_impact = default_impact
    pipeline.config = config_payload
    pipeline.should_run = True
    pipeline.status = LiveFeedPipeline.Status.STARTING
    pipeline.last_error = ''
    pipeline.save(update_fields=['pipeline_type', 'default_impact', 'config', 'should_run', 'status', 'last_error', 'updated_at'])

    LiveFeedPipelineLog.log(
        pipeline=pipeline,
        event_type=LiveFeedPipelineLog.EventType.START,
        level=LiveFeedPipelineLog.LogLevel.INFO,
        message='Pipeline requested to run',
        details={
            'source': source.key,
            'category_id': category.id,
            'default_impact': default_impact,
            'config_keys': sorted(config_payload.keys()),
        },
    )

    pipeline_manager.request_reconcile()

    source_map = source_definition_map()
    return JsonResponse({'success': True, 'pipeline': _serialize_pipeline(pipeline, source_map)})

@staff_member_required
@require_POST
def api_pipeline_start(request, pipeline_id: int):
    pipeline = LiveFeedPipeline.objects.select_related('category').filter(id=pipeline_id).first()
    if not pipeline:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)

    source_map = source_definition_map()
    source = source_map.get(pipeline.source)
    if not source:
        return JsonResponse({'error': f'Unsupported source: {pipeline.source}'}, status=400)

    if int(pipeline.pipeline_type or 0) != int(source.pipeline_type):
        return JsonResponse({'error': 'Pipeline source type configuration mismatch'}, status=400)

    if int(pipeline.category.live_feed_type or 0) != int(pipeline.pipeline_type):
        return JsonResponse({'error': 'Pipeline category type no longer matches pipeline type'}, status=400)

    pipeline.should_run = True
    pipeline.status = LiveFeedPipeline.Status.STARTING
    pipeline.last_error = ''
    pipeline.save(update_fields=['should_run', 'status', 'last_error', 'updated_at'])

    LiveFeedPipelineLog.log(
        pipeline=pipeline,
        event_type=LiveFeedPipelineLog.EventType.START,
        level=LiveFeedPipelineLog.LogLevel.INFO,
        message='Pipeline requested to start',
    )
    pipeline_manager.request_reconcile()
    return JsonResponse({'success': True, 'pipeline': _serialize_pipeline(pipeline, source_map)})

@staff_member_required
@require_POST
def api_pipeline_stop(request, pipeline_id: int):
    pipeline = LiveFeedPipeline.objects.select_related('category').filter(id=pipeline_id).first()
    if not pipeline:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)

    pipeline.should_run = False
    pipeline.status = LiveFeedPipeline.Status.STOPPING
    pipeline.save(update_fields=['should_run', 'status', 'updated_at'])

    LiveFeedPipelineLog.log(
        pipeline=pipeline,
        event_type=LiveFeedPipelineLog.EventType.STOP,
        level=LiveFeedPipelineLog.LogLevel.INFO,
        message='Pipeline requested to stop',
    )
    pipeline_manager.stop_local_runner(pipeline.id)
    pipeline_manager.request_reconcile()
    source_map = source_definition_map()
    return JsonResponse({'success': True, 'pipeline': _serialize_pipeline(pipeline, source_map)})

@staff_member_required
@require_POST
def api_pipeline_update(request, pipeline_id: int):
    pipeline = LiveFeedPipeline.objects.select_related('category').filter(id=pipeline_id).first()
    if not pipeline:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    updated_fields: list[str] = []
    details: dict[str, Any] = {}

    if 'default_impact' in data:
        default_impact = _normalize_impact(data.get('default_impact'), default=int(pipeline.default_impact or 2))
        if int(pipeline.default_impact or 0) != default_impact:
            pipeline.default_impact = default_impact
            updated_fields.append('default_impact')
            details['default_impact'] = default_impact

    if 'config' in data:
        try:
            config_payload = _normalize_pipeline_config(data.get('config'))
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        existing_config = pipeline.config if isinstance(pipeline.config, dict) else {}
        if existing_config != config_payload:
            pipeline.config = config_payload
            updated_fields.append('config')
            details['config_keys'] = sorted(config_payload.keys())

    if not updated_fields:
        source_map = source_definition_map()
        return JsonResponse({'success': True, 'pipeline': _serialize_pipeline(pipeline, source_map), 'unchanged': True})

    updated_fields.append('updated_at')
    pipeline.save(update_fields=updated_fields)

    LiveFeedPipelineLog.log(
        pipeline=pipeline,
        event_type=LiveFeedPipelineLog.EventType.UPDATE,
        level=LiveFeedPipelineLog.LogLevel.INFO,
        message='Pipeline settings updated',
        details=details,
    )
    source_map = source_definition_map()
    return JsonResponse({'success': True, 'pipeline': _serialize_pipeline(pipeline, source_map)})

@staff_member_required
@require_POST
def api_pipeline_delete(request, pipeline_id: int):
    pipeline = LiveFeedPipeline.objects.filter(id=pipeline_id).first()
    if not pipeline:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)

    if pipeline.should_run:
        return JsonResponse({'error': 'Stop the pipeline before deleting it'}, status=400)

    pipeline_manager.stop_local_runner(pipeline.id)
    pipeline.delete()
    pipeline_manager.request_reconcile()
    return JsonResponse({'success': True})


@staff_member_required
@require_GET
def published_items_view(request):
    """Page view for listing published items (live feed categories only)."""
    categories = list(
        Categories.objects
        .filter(live_feed_type__gt=0)
        .order_by('order', 'id')
        .values('id', 'name', 'enabled', 'order', 'live_feed_type', 'config')
    )

    # Build hub list with proper display names
    hub_list = [
        {'key': hub_key, 'name': hub_info['name']}
        for hub_key, hub_info in HUBS.items()
    ]

    context = {
        **admin.site.each_context(request),
        'title': 'Published Items',
        'categories': categories,
        'hubs': hub_list,
    }
    return TemplateResponse(request, 'admin/live_feed/published_items.html', context)


@staff_member_required
@require_GET
def api_published_items(request):
    """API endpoint for fetching published items with filtering."""
    category_id = request.GET.get('category_id')
    hub = request.GET.get('hub')
    limit = min(max(int(request.GET.get('limit', 100)), 1), 500)
    offset = max(int(request.GET.get('offset', 0)), 0)
    since = request.GET.get('since')

    qs = LiveFeedPublishedItem.objects.select_related('category').filter(
        category__live_feed_type__gt=0
    )

    if category_id:
        try:
            qs = qs.filter(category_id=int(category_id))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'category_id must be integer'}, status=400)

    if hub and hub != 'all':
        qs = qs.filter(hub=hub)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            qs = qs.filter(created_at__gt=since_dt)
        except ValueError:
            pass

    total = qs.count()
    items = []
    for row in qs.order_by('-created_at')[offset:offset + limit]:
        items.append({
            'id': row.id,
            'category_id': row.category_id,
            'category_name': row.category.name if row.category else '',
            'sequence_id': row.sequence_id,
            'title': row.title,
            'impact': row.impact,
            'timestamp': row.timestamp.isoformat() if row.timestamp else None,
            'hub': row.hub,
            'payload': row.payload or {},
            'created_at': row.created_at.isoformat(),
        })

    return JsonResponse({
        'items': items,
        'total': total,
        'limit': limit,
        'offset': offset,
        'has_more': offset + limit < total,
    })


@staff_member_required
@require_POST
def api_published_items_delete(request):
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    raw_ids = data.get('ids')
    if not isinstance(raw_ids, list):
        return JsonResponse({'error': 'ids must be an array of integers'}, status=400)

    ids: list[int] = []
    for raw in raw_ids:
        try:
            item_id = int(raw)
        except (TypeError, ValueError):
            continue
        if item_id > 0:
            ids.append(item_id)

    if not ids:
        return JsonResponse({'error': 'No valid item ids provided'}, status=400)

    # keep input order while deduplicating
    ids = list(dict.fromkeys(ids))

    qs = LiveFeedPublishedItem.objects.filter(
        id__in=ids,
        category__live_feed_type__gt=0,
    )
    existing_ids = list(qs.values_list('id', flat=True))
    qs.delete()

    existing_id_set = set(existing_ids)
    missing_ids = [item_id for item_id in ids if item_id not in existing_id_set]

    return JsonResponse({
        'success': True,
        'deleted': len(existing_ids),
        'deleted_ids': existing_ids,
        'missing_ids': missing_ids,
    })


@staff_member_required
@require_GET
def api_category_config(request, category_id: int):
    """API endpoint to get category config."""
    category = Categories.objects.filter(id=category_id, live_feed_type__gt=0).first()
    if not category:
        return JsonResponse({'error': 'Category not found or not a live feed category'}, status=404)

    return JsonResponse({
        'id': category.id,
        'name': category.name,
        'config': category.config or {},
        'initial_fanout_limit': category.initial_fanout_limit,
    })


@staff_member_required
@require_POST
def api_category_config_update(request, category_id: int):
    """API endpoint to update category config."""
    category = Categories.objects.filter(id=category_id, live_feed_type__gt=0).first()
    if not category:
        return JsonResponse({'error': 'Category not found or not a live feed category'}, status=404)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    config = data.get('config')
    if config is None:
        return JsonResponse({'error': 'config is required'}, status=400)

    if not isinstance(config, dict):
        return JsonResponse({'error': 'config must be a JSON object'}, status=400)

    # Validate that it's JSON serializable
    try:
        json.dumps(config)
    except TypeError:
        return JsonResponse({'error': 'config contains non-JSON-serializable values'}, status=400)

    category.config = config
    category.save(update_fields=['config'])

    return JsonResponse({
        'success': True,
        'id': category.id,
        'name': category.name,
        'config': category.config,
        'initial_fanout_limit': category.initial_fanout_limit,
    })
