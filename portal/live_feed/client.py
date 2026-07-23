"""Client API for the live feed service.

This is the only entry point views, celery tasks, and pipelines should use.
It never opens hub sockets itself: desired state goes to Postgres, commands
go through the RPC layer, and status/stream data is read from the mirrors
the service maintains in Redis.
"""

import json
import logging

from django_redis import get_redis_connection

from portal.models import LiveFeedHub

from . import rpc
from .constants import COST_FIELDS, COSTS_KEY, HUBS, STATUS_KEY, items_key, snapshot_key

logger = logging.getLogger(__name__)

CONNECT_RPC_TIMEOUT = 12.0
PUBLISH_RPC_TIMEOUT = 15.0
SERVICE_OFFLINE_ERROR = 'Live feed service is not running'


def _redis():
    return get_redis_connection('default')


def _offline_hub_state(hub: str, desired: dict) -> dict:
    return {
        'name': HUBS[hub]['name'],
        'location': HUBS[hub]['location'],
        'desired': bool(desired.get(hub, False)),
        'connected': False,
        'connecting': False,
        'live_users': 0,
        'admin_users': 0,
        'connected_at': None,
        'last_activity': None,
        'last_error': SERVICE_OFFLINE_ERROR if desired.get(hub) else None,
        'owner': '',
    }


def get_hub_states() -> dict:
    try:
        desired = LiveFeedHub.desired_map()
    except Exception:
        desired = {}

    raw = None
    try:
        raw = _redis().get(STATUS_KEY)
    except Exception:
        logger.warning("Failed to read live feed status mirror", exc_info=True)

    if raw:
        try:
            status = json.loads(raw)
            hubs = status.get('hubs') or {}
            return {hub: {**_offline_hub_state(hub, desired), **(hubs.get(hub) or {})} for hub in HUBS}
        except (TypeError, ValueError):
            pass

    return {hub: _offline_hub_state(hub, desired) for hub in HUBS}


def connect_hub(hub: str) -> dict:
    if hub not in HUBS:
        return {'success': False, 'error': f'Unknown hub: {hub}'}
    LiveFeedHub.set_desired(hub, True)
    return rpc.call('connect', {'hub': hub}, timeout=CONNECT_RPC_TIMEOUT)


def connect_all() -> dict:
    for hub in HUBS:
        LiveFeedHub.set_desired(hub, True)
    result = rpc.call('connect', {'hub': 'all'}, timeout=CONNECT_RPC_TIMEOUT)
    if isinstance(result.get('results'), dict):
        return result['results']
    return {hub: {'success': False, 'error': str(result.get('error') or 'Connect failed')} for hub in HUBS}


def disconnect_hub(hub: str) -> dict:
    if hub not in HUBS:
        return {'success': False, 'error': f'Unknown hub: {hub}'}
    LiveFeedHub.set_desired(hub, False)
    result = rpc.call('disconnect', {'hub': hub}, timeout=CONNECT_RPC_TIMEOUT)
    if result.get('timeout'):
        # Desired state is saved; the service will disconnect once it is back.
        return {'success': True, 'deferred': True}
    return result


def disconnect_all() -> dict:
    results = {}
    for hub in HUBS:
        results[hub] = disconnect_hub(hub)
    return results


def publish_item(*, hub: str, category_id: int, title: str, impact: int = 0,
                 timestamp: str = None, dedupe_key: str = '') -> dict:
    return rpc.call(
        'publish_item',
        {
            'hub': hub,
            'category_id': int(category_id),
            'title': title,
            'impact': int(impact),
            'timestamp': timestamp or '',
            'dedupe_key': dedupe_key or '',
        },
        timeout=PUBLISH_RPC_TIMEOUT,
    )


def set_initial_fanout_snapshot(*, category_id: int, hub: str = 'all', limit: int = None) -> dict:
    return rpc.call(
        'set_broadcast',
        {'category_id': int(category_id), 'hub': hub, 'limit': limit},
        timeout=PUBLISH_RPC_TIMEOUT,
    )


def request_live_users(hub: str = 'all') -> dict:
    return rpc.call('get_live_users', {'hub': hub}, timeout=8.0)


def nudge_pipelines():
    result = rpc.call('reconcile_pipelines', {}, timeout=3.0)
    if not result.get('success'):
        logger.info("Pipeline reconcile nudge not delivered: %s", result.get('error'))


def get_feed_items(hub: str, limit: int = 100) -> list:
    try:
        items = _redis().lrange(items_key(hub), 0, limit - 1)
        return [json.loads(item) for item in items]
    except Exception:
        logger.warning("Failed to read feed items for %s", hub, exc_info=True)
        return []


def get_snapshot(hub: str):
    try:
        data = _redis().get(snapshot_key(hub))
    except Exception:
        return None
    if not data:
        return None
    try:
        return json.loads(data)
    except (TypeError, ValueError):
        return None


def get_costs() -> dict:
    try:
        raw = _redis().hgetall(COSTS_KEY) or {}
    except Exception:
        raw = {}

    def _decode(value):
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='ignore')
        return str(value or '')

    decoded = {_decode(k): _decode(v) for k, v in raw.items()}
    costs = {}
    for field in COST_FIELDS:
        try:
            costs[field] = int(decoded.get(field, 0) or 0)
        except (TypeError, ValueError):
            costs[field] = 0
    return costs


def reset_costs():
    rpc.call('reset_costs', {}, timeout=3.0)
    try:
        _redis().delete(COSTS_KEY)
    except Exception:
        pass
