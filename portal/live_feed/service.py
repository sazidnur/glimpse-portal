"""Live feed socket service.

Runs as a single dedicated process (`manage.py live_feed_service`) that owns
all hub WebSockets. Everything else (gunicorn views, celery tasks, pipeline
runners) talks to it through the RPC layer and only ever gets `success: True`
after the Durable Object acknowledged the message.

Desired connection state lives in Postgres (LiveFeedHub), so the service
reconnects by itself after any restart or deploy. Redis holds only mirrors
and queues — losing it never drops an established socket.

Keepalive uses WebSocket protocol-level pings only, which Cloudflare's
runtime answers without waking a hibernated Durable Object.
"""

import json
import logging
import os
import socket as socket_module
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import websocket
from dateutil.parser import parse as parse_datetime
from django.conf import settings
from django.db import IntegrityError, close_old_connections
from django_redis import get_redis_connection

from portal.models import Categories, LiveFeedHub, LiveFeedLog, LiveFeedPublishedItem

from . import rpc
from .constants import (
    COST_FIELDS,
    COSTS_KEY,
    COSTS_TTL_SECONDS,
    HUBS,
    STATUS_KEY,
    STATUS_TTL_SECONDS,
    items_key,
    snapshot_key,
)

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 3.0
RECONNECT_BASE_DELAY = 2.0
RECONNECT_MAX_DELAY = 60.0
HANDSHAKE_TIMEOUT_SECONDS = 30.0
ACK_TIMEOUT_SECONDS = 10.0
CONNECT_WAIT_SECONDS = 8.0
LIVE_USERS_TIMEOUT_SECONDS = 5.0
INACTIVITY_TIMEOUT_SECONDS = 12 * 60 * 60


class AckTimeout(Exception):
    pass


class HubConnection:
    """One WebSocket to one hub Durable Object.

    The connection is only considered usable after the DO's `connected`
    handshake arrives. `request()` sends a command and blocks until the DO
    replies with one of the expected ack types (or `error`), so a publish
    can never be reported as delivered when it was not.
    """

    def __init__(self, hub: str, service: 'LiveFeedService'):
        self.hub = hub
        self.service = service
        self.connected = False
        self.live_users = 0
        self.admin_users = 0
        self.connected_at: Optional[datetime] = None
        self.last_activity: Optional[datetime] = None
        self.last_error = ''
        self.started_at = time.time()
        self._ws_app = None
        self._closing = False
        self._request_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._expect_types: tuple = ()
        self._response: Optional[dict] = None
        self._response_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f'lf-hub-{hub}')

    def start(self):
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def intentionally_closed(self) -> bool:
        return self._closing

    def stop(self):
        self._closing = True
        self._fail_pending('Connection closed')
        if self._ws_app:
            try:
                self._ws_app.close()
            except Exception:
                pass

    def request(self, message: dict, expect_types: tuple, timeout: float = ACK_TIMEOUT_SECONDS) -> dict:
        with self._request_lock:
            if not self.connected or not self._ws_app:
                raise ConnectionError(f'Hub {self.hub} is not connected')

            with self._pending_lock:
                self._expect_types = tuple(expect_types) + ('error',)
                self._response = None
                self._response_event.clear()

            try:
                self._ws_app.send(json.dumps(message))
            except Exception as exc:
                with self._pending_lock:
                    self._expect_types = ()
                raise ConnectionError(f'Send to hub {self.hub} failed: {exc}') from exc

            self.service.count('messages_sent')
            self._touch()

            acked = self._response_event.wait(timeout)
            with self._pending_lock:
                response = self._response
                self._expect_types = ()
                self._response = None

            if not acked:
                raise AckTimeout(f'Hub {self.hub} did not acknowledge within {timeout:.0f}s')
            if not isinstance(response, dict):
                raise ConnectionError(f'Hub {self.hub} connection dropped while waiting for ack')
            return response

    def _fail_pending(self, reason: str):
        with self._pending_lock:
            if self._expect_types:
                self._expect_types = ()
                self._response = None
                self._response_event.set()
                logger.warning("Pending request on %s failed: %s", self.hub, reason)

    def _touch(self):
        self.last_activity = datetime.now(timezone.utc)
        self.service.touch_activity()

    def _ws_url(self) -> str:
        base = (getattr(settings, 'WORKER_BASE_URL', '') or '').rstrip('/')
        if base.startswith('https://'):
            return f"wss://{base[8:]}/api/v1/admin/live-feed"
        if base.startswith('http://'):
            return f"ws://{base[7:]}/api/v1/admin/live-feed"
        return f"wss://{base}/api/v1/admin/live-feed"

    def _run(self):
        token = getattr(settings, 'LIVE_FEED_ADMIN_TOKEN', '') or ''
        if not token:
            self.last_error = 'LIVE_FEED_ADMIN_TOKEN not configured'
            self.service.on_socket_closed(self.hub, self)
            return

        headers = {
            'Authorization': f'Token {token}',
            'X-Live-Feed-Hub': self.hub,
        }

        try:
            self._ws_app = websocket.WebSocketApp(
                self._ws_url(),
                header=headers,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            # Protocol-level pings only: answered by Cloudflare's runtime
            # without waking a hibernated Durable Object.
            self._ws_app.run_forever(ping_interval=30, ping_timeout=20)
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("WebSocket loop failed for %s", self.hub)
        finally:
            was_connected = self.connected
            self.connected = False
            self._fail_pending('Socket closed')
            self.service.on_socket_closed(self.hub, self, was_connected=was_connected)

    def _on_error(self, ws, error):
        self.last_error = str(error)
        logger.error("WebSocket error on %s: %s", self.hub, error)

    def _on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        self._fail_pending(f'Socket closed (code={close_status_code})')

    def _on_message(self, ws, raw):
        self._touch()
        self.service.count('messages_received')
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("Invalid JSON from %s: %.100s", self.hub, raw)
            return
        if not isinstance(data, dict):
            return

        msg_type = str(data.get('type') or '')

        if msg_type == 'connected':
            self.live_users = int(data.get('live_users') or 0)
            self.admin_users = int(data.get('admin_users') or 0)
            self.connected_at = datetime.now(timezone.utc)
            self.last_error = ''
            self.connected = True
            self.service.on_hub_connected(self.hub, self, data)

        elif msg_type in ('publish_item_ack', 'set_broadcast_ack', 'hub_users'):
            self.live_users = int(data.get('live_users') or self.live_users)
            self.admin_users = int(data.get('admin_users') or self.admin_users)

        elif msg_type == 'snapshot':
            self.service.store_snapshot(self.hub, data)

        elif msg_type == 'message':
            self.service.store_feed_item(self.hub, data)

        delivered = False
        with self._pending_lock:
            if self._expect_types and msg_type in self._expect_types:
                self._response = data
                self._response_event.set()
                delivered = True

        if msg_type == 'error' and not delivered:
            self.service.log_event(
                self.hub, 'error', str(data.get('error') or 'Unknown hub error'), level='error'
            )


class LiveFeedService:
    def __init__(self):
        self.instance_id = f"{socket_module.gethostname()}-{os.getpid()}"
        self._conns: Dict[str, Optional[HubConnection]] = {hub: None for hub in HUBS}
        self._backoff: Dict[str, float] = {hub: RECONNECT_BASE_DELAY for hub in HUBS}
        self._next_attempt: Dict[str, float] = {hub: 0.0 for hub in HUBS}
        self._last_errors: Dict[str, str] = {hub: '' for hub in HUBS}
        self._stop = threading.Event()
        self._rpc = rpc.RpcServer(self.handle_action)
        self._last_activity: Optional[datetime] = None
        self._reconcile_lock = threading.Lock()

    # --- lifecycle -------------------------------------------------------

    def run(self):
        from .pipeline_manager import pipeline_manager

        logger.info("Live feed service starting (instance=%s)", self.instance_id)
        rpc.register_local_handler(self.handle_action)
        self._rpc.start()
        pipeline_manager.start_monitor()

        try:
            while not self._stop.is_set():
                try:
                    self._reconcile()
                except Exception:
                    logger.exception("Live feed reconcile failed")
                self._stop.wait(RECONCILE_INTERVAL_SECONDS)
        finally:
            logger.info("Live feed service shutting down")
            rpc.unregister_local_handler()
            self._rpc.stop()
            pipeline_manager.stop_monitor()
            for hub, conn in self._conns.items():
                if conn is not None:
                    conn.stop()
            try:
                self._redis().delete(STATUS_KEY)
            except Exception:
                pass

    def stop(self):
        self._stop.set()

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def _redis():
        return get_redis_connection('default')

    def touch_activity(self):
        self._last_activity = datetime.now(timezone.utc)

    def count(self, field: str, amount: int = 1):
        if field not in COST_FIELDS:
            return
        try:
            redis = self._redis()
            redis.hincrby(COSTS_KEY, field, int(amount))
            redis.expire(COSTS_KEY, COSTS_TTL_SECONDS)
        except Exception:
            pass

    def log_event(self, hub: str, event_type: str, message: str,
                  level: str = 'info', details: dict = None):
        level_map = {
            'debug': LiveFeedLog.LogLevel.DEBUG,
            'info': LiveFeedLog.LogLevel.INFO,
            'warning': LiveFeedLog.LogLevel.WARNING,
            'error': LiveFeedLog.LogLevel.ERROR,
        }
        try:
            close_old_connections()
            LiveFeedLog.log(
                hub=hub,
                event_type=event_type,
                message=message,
                level=level_map.get(level, LiveFeedLog.LogLevel.INFO),
                details=details,
            )
        except Exception:
            logger.exception("Failed to write live feed log event")

    def store_snapshot(self, hub: str, data: dict):
        try:
            self._redis().set(snapshot_key(hub), json.dumps(data))
        except Exception:
            logger.exception("Failed to store snapshot for %s", hub)

    def store_feed_item(self, hub: str, item: dict):
        try:
            redis = self._redis()
            redis.lpush(items_key(hub), json.dumps(item))
            redis.ltrim(items_key(hub), 0, 999)
        except Exception:
            logger.exception("Failed to store feed item for %s", hub)

    def _clear_hub_mirrors(self, hub: str):
        try:
            redis = self._redis()
            redis.delete(snapshot_key(hub))
            redis.delete(items_key(hub))
        except Exception:
            pass

    # --- connection reconcile --------------------------------------------

    def _desired_map(self) -> dict:
        try:
            close_old_connections()
            stored = LiveFeedHub.desired_map()
        except Exception:
            logger.exception("Failed to read desired hub state")
            return {hub: (self._conns.get(hub) is not None) for hub in HUBS}
        return {hub: bool(stored.get(hub, False)) for hub in HUBS}

    def _reconcile(self):
        with self._reconcile_lock:
            self._reconcile_locked()

    def _reconcile_locked(self):
        close_old_connections()
        desired = self._desired_map()
        now = time.time()

        for hub in HUBS:
            conn = self._conns.get(hub)
            alive = conn is not None and conn.is_alive()

            if desired[hub]:
                if alive and not conn.connected and (now - conn.started_at) > HANDSHAKE_TIMEOUT_SECONDS:
                    logger.warning("Hub %s handshake timed out; recycling connection", hub)
                    conn.stop()
                    alive = False
                if not alive:
                    if conn is not None:
                        self._conns[hub] = None
                    if now >= self._next_attempt[hub]:
                        self._start_connection(hub, now)
            else:
                if conn is not None:
                    self._drop_connection(hub, conn)
                self._backoff[hub] = RECONNECT_BASE_DELAY
                self._next_attempt[hub] = 0.0

        self._check_inactivity(desired)
        self._write_status(desired)

    def _start_connection(self, hub: str, now: float):
        delay = self._backoff[hub]
        self._backoff[hub] = min(RECONNECT_MAX_DELAY, delay * 2)
        self._next_attempt[hub] = now + delay
        conn = HubConnection(hub, self)
        self._conns[hub] = conn
        conn.start()
        logger.info("Connecting to hub %s (next retry in %.0fs if it fails)", hub, delay)

    def _drop_connection(self, hub: str, conn: HubConnection):
        was_connected = conn.connected
        conn.stop()
        self._conns[hub] = None
        self._clear_hub_mirrors(hub)
        if was_connected:
            self.count('disconnects')
            self.log_event(hub, 'disconnect', 'Disconnected from hub')
        self._last_errors[hub] = ''

    def on_hub_connected(self, hub: str, conn: HubConnection, data: dict):
        self._backoff[hub] = RECONNECT_BASE_DELAY
        self._last_errors[hub] = ''

        actual_hub = str(data.get('hub') or '').strip().lower()
        if actual_hub and actual_hub != hub:
            conn.last_error = f'Hub mismatch from worker: expected={hub} actual={actual_hub}'
            self.log_event(
                hub, 'error', conn.last_error, level='error',
                details={'expected_hub': hub, 'actual_hub': actual_hub},
            )

        snapshot = data.get('snapshot')
        if snapshot:
            self.store_snapshot(hub, snapshot)

        self.count('connects')
        self.log_event(
            hub, 'connect',
            f"Connected (users={conn.live_users}, admins={conn.admin_users})",
            details={'live_users': conn.live_users, 'admin_users': conn.admin_users},
        )
        logger.info("Connected to hub %s", hub)
        self._write_status(self._desired_map())

    def on_socket_closed(self, hub: str, conn: HubConnection, was_connected: bool = False):
        if conn.last_error:
            self._last_errors[hub] = conn.last_error
        if self._conns.get(hub) is conn:
            if was_connected and not conn.intentionally_closed and not self._stop.is_set():
                logger.warning("Connection to hub %s lost; will reconnect", hub)
                self.log_event(
                    hub, 'disconnect', 'Connection lost; reconnecting automatically',
                    level='warning',
                    details={'last_error': conn.last_error or ''},
                )

    def _check_inactivity(self, desired: dict):
        any_connected = any(
            conn is not None and conn.connected for conn in self._conns.values()
        )
        if not any_connected or not self._last_activity:
            return
        elapsed = (datetime.now(timezone.utc) - self._last_activity).total_seconds()
        if elapsed <= INACTIVITY_TIMEOUT_SECONDS:
            return

        logger.warning("Disconnecting all hubs after %.1fh of inactivity", elapsed / 3600)
        self.log_event(
            'all', 'disconnect',
            f'Disconnected all hubs due to {elapsed / 3600:.1f}h inactivity',
            level='warning',
        )
        for hub in HUBS:
            if desired.get(hub):
                try:
                    LiveFeedHub.set_desired(hub, False)
                except Exception:
                    logger.exception("Failed to persist inactivity disconnect for %s", hub)

    def _hub_status(self, hub: str, desired: dict) -> dict:
        conn = self._conns.get(hub)
        alive = conn is not None and conn.is_alive()
        connected = bool(alive and conn.connected)
        return {
            'name': HUBS[hub]['name'],
            'location': HUBS[hub]['location'],
            'desired': bool(desired.get(hub, False)),
            'connected': connected,
            'connecting': bool(alive and not connected),
            'live_users': conn.live_users if conn else 0,
            'admin_users': conn.admin_users if conn else 0,
            'connected_at': conn.connected_at.isoformat() if conn and conn.connected_at else None,
            'last_activity': conn.last_activity.isoformat() if conn and conn.last_activity else None,
            'last_error': ((conn.last_error if conn else '') or self._last_errors.get(hub, '')) or None,
            'owner': self.instance_id if alive else '',
        }

    def _build_status(self, desired: dict) -> dict:
        return {
            'instance': self.instance_id,
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'hubs': {hub: self._hub_status(hub, desired) for hub in HUBS},
        }

    def _write_status(self, desired: dict):
        try:
            self._redis().set(
                STATUS_KEY,
                json.dumps(self._build_status(desired)),
                ex=STATUS_TTL_SECONDS,
            )
        except Exception:
            logger.warning("Failed to write live feed status mirror", exc_info=True)

    # --- publishing ------------------------------------------------------

    def _store_published_item(self, *, category_id: int, sequence_id: int, title: str,
                              impact: int, timestamp: str, hub: str, payload: dict,
                              dedupe_key: str = '') -> Optional[LiveFeedPublishedItem]:
        key = (dedupe_key or '').strip() or None
        if key:
            existing = LiveFeedPublishedItem.objects.filter(dedupe_key=key).first()
            if existing:
                return existing

        category = Categories.objects.filter(id=category_id).first()
        if not category:
            logger.error("Cannot store published item: category %s not found", category_id)
            return None

        try:
            ts = parse_datetime(timestamp) if timestamp else datetime.now(timezone.utc)
        except (ValueError, OverflowError):
            ts = datetime.now(timezone.utc)

        try:
            item = LiveFeedPublishedItem.objects.create(
                category=category,
                sequence_id=sequence_id,
                title=title,
                impact=impact,
                timestamp=ts,
                hub=hub,
                payload=payload,
                dedupe_key=key,
            )
        except IntegrityError:
            return LiveFeedPublishedItem.objects.filter(dedupe_key=key).first()

        LiveFeedPublishedItem.cleanup_if_needed()
        return item

    def _build_fanout_snapshot(self, category_id: int, limit: Optional[int] = None) -> Optional[dict]:
        category = Categories.objects.filter(id=category_id).first()
        if not category:
            return None
        items = LiveFeedPublishedItem.get_initial_fanout_items(category, limit=limit)
        if not items:
            return None
        return {
            'type': 'snapshot',
            'category': {str(category_id): [item.to_fanout_dict() for item in items]},
        }

    def _connected_conn(self, hub: str) -> Optional[HubConnection]:
        conn = self._conns.get(hub)
        if conn is not None and conn.is_alive() and conn.connected:
            return conn
        return None

    def _send_with_ack(self, hub: str, message: dict, expect: tuple,
                       timeout: float = ACK_TIMEOUT_SECONDS) -> dict:
        conn = self._connected_conn(hub)
        if conn is None:
            return {'success': False, 'error': 'Not connected', 'skipped': True}
        try:
            response = conn.request(message, expect, timeout=timeout)
        except AckTimeout as exc:
            self.log_event(hub, 'error', str(exc), level='error')
            conn.stop()
            return {'success': False, 'error': str(exc)}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

        if str(response.get('type') or '') == 'error':
            return {'success': False, 'error': str(response.get('error') or 'Hub rejected message')}
        return {'success': True, 'ack': response}

    def _publish_item(self, payload: dict) -> dict:
        hub = str(payload.get('hub') or 'all')
        if hub != 'all' and hub not in HUBS:
            return {'success': False, 'error': f'Unknown hub: {hub}'}

        category_id = int(payload.get('category_id') or 0)
        title = str(payload.get('title') or '').strip()
        impact = max(0, min(2, int(payload.get('impact') or 0)))
        timestamp = str(payload.get('timestamp') or '') or datetime.now(timezone.utc).isoformat()
        dedupe_key = str(payload.get('dedupe_key') or '')
        if not category_id or not title:
            return {'success': False, 'error': 'category_id and title are required'}

        stored = self._store_published_item(
            category_id=category_id,
            sequence_id=int(datetime.now(timezone.utc).timestamp() * 1000),
            title=title,
            impact=impact,
            timestamp=timestamp,
            hub=hub,
            payload={},
            dedupe_key=dedupe_key,
        )

        item = {
            'type': 'message',
            'category_id': category_id,
            'sequence_id': stored.sequence_id if stored else int(datetime.now(timezone.utc).timestamp() * 1000),
            'title': title,
        }
        if impact:
            item['impact'] = impact
        item['timestamp'] = timestamp

        if stored and stored.payload != item:
            LiveFeedPublishedItem.objects.filter(id=stored.id).update(payload=item)

        message = {'type': 'publish_item', 'item': item}
        snapshot = self._build_fanout_snapshot(category_id) if stored else None
        if snapshot:
            message['snapshot'] = snapshot

        targets = list(HUBS) if hub == 'all' else [hub]
        results = {h: self._send_with_ack(h, message, ('publish_item_ack',)) for h in targets}

        successful = [h for h, r in results.items() if r.get('success')]
        skipped = [h for h, r in results.items() if r.get('skipped')]
        failed = [h for h, r in results.items() if not r.get('success') and not r.get('skipped')]
        success = bool(successful)

        if success:
            self.count('publishes')

        if hub == 'all':
            if success:
                self.log_event(
                    'all', 'publish',
                    f'Published to {len(successful)} hub(s): "{title[:50]}"',
                    details={
                        'category_id': category_id,
                        'successful_hubs': successful,
                        'skipped_hubs': skipped,
                        'failed_hubs': failed,
                        'fanout_updated': snapshot is not None,
                    },
                )
            else:
                self.log_event(
                    'all', 'error',
                    f'Publish failed on all hubs: "{title[:50]}"',
                    level='error',
                    details={'category_id': category_id, 'skipped_hubs': skipped, 'failed_hubs': failed},
                )
            return {
                'success': success,
                'results': {h: {k: v for k, v in r.items() if k != 'ack'} for h, r in results.items()},
                'successful_hubs': successful,
                'skipped_hubs': skipped,
                'failed_hubs': failed,
                'error': '' if success else 'No hub acknowledged the publish',
            }

        result = results[hub]
        if result.get('success'):
            self.log_event(
                hub, 'publish', f'Published: "{title[:50]}"',
                details={'category_id': category_id, 'fanout_updated': snapshot is not None},
            )
            return {'success': True}
        return {'success': False, 'error': str(result.get('error') or 'Publish failed')}

    def _set_broadcast(self, payload: dict) -> dict:
        hub = str(payload.get('hub') or 'all')
        if hub != 'all' and hub not in HUBS:
            return {'success': False, 'error': f'Unknown hub: {hub}'}

        category_id = int(payload.get('category_id') or 0)
        limit = payload.get('limit')
        limit = int(limit) if limit else None

        snapshot = self._build_fanout_snapshot(category_id, limit=limit)
        if not snapshot:
            return {'success': False, 'error': 'No published items available for initial fanout'}

        fanout_items = ((snapshot.get('category') or {}).get(str(category_id)) or [])
        item_count = len(fanout_items)
        message = {'type': 'set_broadcast', 'snapshot': snapshot}

        targets = list(HUBS) if hub == 'all' else [hub]
        results = {h: self._send_with_ack(h, message, ('set_broadcast_ack',)) for h in targets}

        successful = [h for h, r in results.items() if r.get('success')]
        failed = [h for h, r in results.items() if not r.get('success')]
        success = bool(successful)

        if success:
            self.count('broadcasts', amount=len(successful))
            self.log_event(
                'all' if hub == 'all' else hub,
                'broadcast',
                f'Set initial fanout snapshot for category={category_id} on {len(successful)} hub(s)',
                details={
                    'category_id': category_id,
                    'item_count': item_count,
                    'successful_hubs': successful,
                    'failed_hubs': failed,
                },
            )
        else:
            self.log_event(
                'all' if hub == 'all' else hub,
                'error',
                f'Failed to set initial fanout snapshot for category={category_id}',
                level='error',
                details={'category_id': category_id, 'item_count': item_count, 'failed_hubs': failed},
            )

        return {
            'success': success,
            'results': {h: {k: v for k, v in r.items() if k != 'ack'} for h, r in results.items()},
            'successful_hubs': successful,
            'failed_hubs': failed,
            'item_count': item_count,
            'error': '' if success else 'Failed to send snapshot to connected hubs',
        }

    # --- RPC entry point ---------------------------------------------------

    def handle_action(self, action: str, payload: dict) -> dict:
        close_old_connections()

        if action == 'publish_item':
            return self._publish_item(payload)

        if action == 'set_broadcast':
            return self._set_broadcast(payload)

        if action == 'connect':
            return self._handle_connect(payload)

        if action == 'disconnect':
            self._reconcile()
            return {'success': True}

        if action == 'get_live_users':
            return self._handle_live_users(payload)

        if action == 'status':
            return {'success': True, 'status': self._build_status(self._desired_map())}

        if action == 'reconcile_pipelines':
            from .pipeline_manager import pipeline_manager
            pipeline_manager.request_reconcile()
            return {'success': True}

        if action == 'reset_costs':
            try:
                self._redis().delete(COSTS_KEY)
            except Exception:
                pass
            return {'success': True}

        return {'success': False, 'error': f'Unknown action: {action}'}

    def _handle_connect(self, payload: dict) -> dict:
        hub = str(payload.get('hub') or 'all')
        targets = list(HUBS) if hub == 'all' else [hub]
        if hub != 'all' and hub not in HUBS:
            return {'success': False, 'error': f'Unknown hub: {hub}'}

        self._reconcile()

        deadline = time.time() + CONNECT_WAIT_SECONDS
        while time.time() < deadline:
            if all(self._connected_conn(h) is not None for h in targets):
                break
            if self._stop.wait(0.2):
                break
            self._reconcile()

        results = {}
        for h in targets:
            conn = self._conns.get(h)
            connected = self._connected_conn(h) is not None
            results[h] = {
                'success': connected,
                'connected': connected,
                'error': '' if connected else ((conn.last_error if conn else '') or 'Connection pending'),
            }
        if hub == 'all':
            return {'success': any(r['success'] for r in results.values()), 'results': results}
        return results[hub]

    def _handle_live_users(self, payload: dict) -> dict:
        hub = str(payload.get('hub') or 'all')
        targets = list(HUBS) if hub == 'all' else [hub]
        if hub != 'all' and hub not in HUBS:
            return {'success': False, 'error': f'Unknown hub: {hub}'}

        results = {}
        for h in targets:
            result = self._send_with_ack(
                h, {'type': 'get_live_users'}, ('hub_users',),
                timeout=LIVE_USERS_TIMEOUT_SECONDS,
            )
            if result.get('success'):
                ack = result.get('ack') or {}
                results[h] = {
                    'success': True,
                    'live_users': int(ack.get('live_users') or 0),
                    'admin_users': int(ack.get('admin_users') or 0),
                }
            else:
                results[h] = {'success': False, 'error': str(result.get('error') or 'Not connected')}

        self._write_status(self._desired_map())
        return {'success': any(r.get('success') for r in results.values()), 'hubs': results}
