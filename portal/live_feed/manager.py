import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

from django.conf import settings
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

HUBS = {
    'apac': {'name': 'APAC', 'location': 'Asia Pacific'},
    'europe': {'name': 'Europe', 'location': 'Western Europe'},
    'middle-east': {'name': 'Middle East', 'location': 'Middle East'},
    'americas': {'name': 'Americas', 'location': 'North/South America'},
}

INACTIVITY_TIMEOUT_SECONDS = 12 * 60 * 60
RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0

REDIS_KEY_PREFIX = 'live_feed:hub:'
REDIS_COSTS_PREFIX = 'live_feed:costs:'


@dataclass
class HubState:
    connected: bool = False
    connecting: bool = False
    live_users: int = 0
    admin_users: int = 0
    connected_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    last_error: Optional[str] = None
    snapshot: Optional[dict] = None


@dataclass
class CostCounters:
    connects: int = 0
    disconnects: int = 0
    publishes: int = 0
    broadcasts: int = 0
    messages_sent: int = 0
    messages_received: int = 0


class HubConnection:
    def __init__(self, hub: str, manager: 'LiveFeedHubManager'):
        self.hub = hub
        self.manager = manager
        self.ws = None
        self.state = HubState()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._reconnect_count = 0
        self._lock = threading.Lock()

    def _get_ws_url(self) -> str:
        worker_base = (getattr(settings, 'WORKER_BASE_URL', '') or '').rstrip('/')
        if worker_base.startswith('https://'):
            return f"wss://{worker_base[8:]}/api/v1/admin/live-feed"
        elif worker_base.startswith('http://'):
            return f"ws://{worker_base[7:]}/api/v1/admin/live-feed"
        return f"wss://{worker_base}/api/v1/admin/live-feed"

    def _get_auth_token(self) -> str:
        return getattr(settings, 'LIVE_FEED_ADMIN_TOKEN', '') or ''

    def connect(self) -> bool:
        if self.state.connected or self.state.connecting:
            return False

        self.state.connecting = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_connection, daemon=True)
        self._thread.start()
        return True

    def disconnect(self) -> bool:
        self._stop_event.set()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.state.connected = False
        self.state.connecting = False
        self.manager._update_hub_redis(self.hub, self.state)
        self.manager._log_event(
            self.hub, 'disconnect', 'Disconnected from hub'
        )
        return True

    def send(self, message: dict) -> bool:
        if not self.state.connected or not self.ws:
            return False
        try:
            self.ws.send(json.dumps(message))
            self.manager.costs.messages_sent += 1
            self._update_activity()
            return True
        except Exception as e:
            logger.error("Failed to send to %s: %s", self.hub, e)
            return False

    def _update_activity(self):
        self.state.last_activity = datetime.now(timezone.utc)
        self.manager.last_global_activity = self.state.last_activity

    def _run_connection(self):
        import websocket

        ws_url = self._get_ws_url()
        auth_token = self._get_auth_token()

        if not auth_token:
            self.state.connecting = False
            self.state.last_error = "LIVE_FEED_ADMIN_TOKEN not configured"
            self.manager._log_event(
                self.hub, 'error', self.state.last_error,
                level='error'
            )
            return

        headers = {
            'Authorization': f'Token {auth_token}',
            'X-Live-Feed-Hub': self.hub,
        }

        def on_open(ws):
            with self._lock:
                self.state.connected = True
                self.state.connecting = False
                self.state.connected_at = datetime.now(timezone.utc)
                self.state.last_error = None
                self._reconnect_count = 0
            self._update_activity()
            self.manager.costs.connects += 1
            self.manager._update_hub_redis(self.hub, self.state)
            logger.info("Connected to hub: %s", self.hub)

        def on_message(ws, message):
            self._update_activity()
            self.manager.costs.messages_received += 1
            try:
                data = json.loads(message)
                self._handle_message(data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from %s: %s", self.hub, message[:100])

        def on_error(ws, error):
            with self._lock:
                self.state.last_error = str(error)
            logger.error("WebSocket error on %s: %s", self.hub, error)

        def on_close(ws, close_status_code, close_msg):
            was_connected = self.state.connected
            with self._lock:
                self.state.connected = False
                self.state.connecting = False
            self.manager._update_hub_redis(self.hub, self.state)

            if was_connected:
                self.manager._log_event(
                    self.hub, 'disconnect',
                    f'Connection closed (code={close_status_code})'
                )

            if not self._stop_event.is_set():
                self._schedule_reconnect()

        try:
            self.ws = websocket.WebSocketApp(
                ws_url,
                header=headers,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            self.ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            logger.exception("WebSocket run failed for %s", self.hub)
            self.state.connecting = False
            self.state.last_error = str(e)

    def _handle_message(self, data: dict):
        msg_type = data.get('type', '')

        if msg_type == 'connected':
            self.state.snapshot = data.get('snapshot')
            self.state.live_users = data.get('live_users', 0)
            self.state.admin_users = data.get('admin_users', 0)
            self.manager._update_hub_redis(self.hub, self.state)
            self.manager._log_event(
                self.hub, 'connect',
                f"Connected (users={self.state.live_users}, admins={self.state.admin_users})",
                details={'live_users': self.state.live_users, 'admin_users': self.state.admin_users}
            )

        elif msg_type in ('set_broadcast_ack', 'publish_item_ack'):
            self.state.live_users = data.get('live_users', self.state.live_users)
            self.state.admin_users = data.get('admin_users', self.state.admin_users)
            self.manager._update_hub_redis(self.hub, self.state)

        elif msg_type == 'hub_users':
            self.state.live_users = data.get('live_users', 0)
            self.state.admin_users = data.get('admin_users', 0)
            self.manager._update_hub_redis(self.hub, self.state)

        elif msg_type == 'snapshot':
            self.state.snapshot = data
            self.manager._store_snapshot(self.hub, data)

        elif msg_type == 'message':
            self.manager._store_feed_item(self.hub, data)

        elif msg_type == 'error':
            self.manager._log_event(
                self.hub, 'error', data.get('error', 'Unknown error'),
                level='error'
            )

    def _schedule_reconnect(self):
        if self._stop_event.is_set():
            return

        delay = min(
            RECONNECT_BASE_DELAY * (2 ** self._reconnect_count),
            RECONNECT_MAX_DELAY
        )
        self._reconnect_count += 1

        logger.info("Scheduling reconnect for %s in %.1fs", self.hub, delay)

        def reconnect():
            time.sleep(delay)
            if not self._stop_event.is_set():
                self.state.connecting = True
                self._run_connection()

        threading.Thread(target=reconnect, daemon=True).start()


class LiveFeedHubManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.connections: Dict[str, HubConnection] = {}
        self.costs = CostCounters()
        self.last_global_activity: Optional[datetime] = None
        self._inactivity_thread: Optional[threading.Thread] = None
        self._stop_inactivity_check = threading.Event()

        for hub in HUBS:
            self.connections[hub] = HubConnection(hub, self)

    def _redis(self):
        return get_redis_connection("default")

    @staticmethod
    def _decode_redis_value(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _to_bool(value: str) -> bool:
        return value in ("1", "true", "True", "yes", "on")

    @staticmethod
    def _to_int(value: str, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _update_hub_redis(self, hub: str, state: HubState):
        r = self._redis()
        key = f"{REDIS_KEY_PREFIX}{hub}:state"
        data = {
            'connected': '1' if state.connected else '0',
            'connecting': '1' if state.connecting else '0',
            'live_users': str(state.live_users),
            'admin_users': str(state.admin_users),
            'connected_at': state.connected_at.isoformat() if state.connected_at else '',
            'last_activity': state.last_activity.isoformat() if state.last_activity else '',
            'last_error': state.last_error or '',
        }
        r.hset(key, mapping=data)

    def _get_hub_state_redis(self, hub: str) -> Optional[dict]:
        """
        Read hub state from Redis so status is shared across Django workers.
        Returns None if state is not present or Redis is unavailable.
        """
        key = f"{REDIS_KEY_PREFIX}{hub}:state"
        try:
            raw = self._redis().hgetall(key)
        except Exception:
            return None

        if not raw:
            return None

        decoded = {
            self._decode_redis_value(k): self._decode_redis_value(v)
            for k, v in raw.items()
        }
        return {
            'name': HUBS[hub]['name'],
            'location': HUBS[hub]['location'],
            'connected': self._to_bool(decoded.get('connected', '0')),
            'connecting': self._to_bool(decoded.get('connecting', '0')),
            'live_users': self._to_int(decoded.get('live_users', '0')),
            'admin_users': self._to_int(decoded.get('admin_users', '0')),
            'connected_at': decoded.get('connected_at') or None,
            'last_activity': decoded.get('last_activity') or None,
            'last_error': decoded.get('last_error') or None,
        }

    def _store_snapshot(self, hub: str, snapshot: dict):
        r = self._redis()
        key = f"{REDIS_KEY_PREFIX}{hub}:snapshot"
        r.set(key, json.dumps(snapshot))

    def _store_feed_item(self, hub: str, item: dict):
        r = self._redis()
        key = f"{REDIS_KEY_PREFIX}{hub}:items"
        r.lpush(key, json.dumps(item))
        r.ltrim(key, 0, 999)

    def _get_feed_items(self, hub: str, limit: int = 100) -> list:
        r = self._redis()
        key = f"{REDIS_KEY_PREFIX}{hub}:items"
        items = r.lrange(key, 0, limit - 1)
        return [json.loads(item) for item in items]

    def _clear_hub_data(self, hub: str):
        r = self._redis()
        r.delete(f"{REDIS_KEY_PREFIX}{hub}:snapshot")
        r.delete(f"{REDIS_KEY_PREFIX}{hub}:items")

    def _log_event(self, hub: str, event_type: str, message: str,
                   level: str = 'info', details: dict = None):
        from .models import LiveFeedLog

        level_map = {
            'debug': LiveFeedLog.LogLevel.DEBUG,
            'info': LiveFeedLog.LogLevel.INFO,
            'warning': LiveFeedLog.LogLevel.WARNING,
            'error': LiveFeedLog.LogLevel.ERROR,
        }
        LiveFeedLog.log(
            hub=hub,
            event_type=event_type,
            message=message,
            level=level_map.get(level, LiveFeedLog.LogLevel.INFO),
            details=details
        )

    def connect_hub(self, hub: str) -> dict:
        if hub not in self.connections:
            return {'success': False, 'error': f'Unknown hub: {hub}'}

        conn = self.connections[hub]
        if conn.state.connected:
            return {'success': True, 'already_connected': True}

        started = conn.connect()
        self._ensure_inactivity_monitor()
        return {'success': started}

    def connect_all(self) -> dict:
        results = {}
        for hub in HUBS:
            results[hub] = self.connect_hub(hub)
        return results

    def disconnect_hub(self, hub: str) -> dict:
        if hub not in self.connections:
            return {'success': False, 'error': f'Unknown hub: {hub}'}

        conn = self.connections[hub]
        if not conn.state.connected and not conn.state.connecting:
            return {'success': True, 'already_disconnected': True}

        self._clear_hub_data(hub)
        conn.disconnect()
        self.costs.disconnects += 1
        return {'success': True}

    def disconnect_all(self) -> dict:
        results = {}
        for hub in HUBS:
            results[hub] = self.disconnect_hub(hub)
        return results

    def get_hub_states(self) -> Dict[str, dict]:
        states = {}
        for hub, conn in self.connections.items():
            redis_state = self._get_hub_state_redis(hub)
            if redis_state is not None:
                states[hub] = redis_state
                continue

            states[hub] = {
                'name': HUBS[hub]['name'],
                'location': HUBS[hub]['location'],
                'connected': conn.state.connected,
                'connecting': conn.state.connecting,
                'live_users': conn.state.live_users,
                'admin_users': conn.state.admin_users,
                'connected_at': conn.state.connected_at.isoformat() if conn.state.connected_at else None,
                'last_activity': conn.state.last_activity.isoformat() if conn.state.last_activity else None,
                'last_error': conn.state.last_error,
            }
        return states

    def get_snapshot(self, hub: str) -> Optional[dict]:
        if hub not in self.connections:
            return None
        return self.connections[hub].state.snapshot

    def send_to_hub(self, hub: str, message: dict) -> dict:
        if hub not in self.connections:
            return {'success': False, 'error': f'Unknown hub: {hub}'}

        conn = self.connections[hub]
        if not conn.state.connected:
            return {'success': False, 'error': f'Hub {hub} not connected'}

        success = conn.send(message)
        return {'success': success}

    def send_to_all(self, message: dict) -> dict:
        results = {}
        for hub in HUBS:
            if self.connections[hub].state.connected:
                results[hub] = self.send_to_hub(hub, message)
        return results

    def publish_item(self, hub: str, category_id: int, title: str,
                     impact: int = 0, timestamp: str = None) -> dict:
        item = {
            'type': 'message',
            'category_id': category_id,
            'sequence_id': int(datetime.now(timezone.utc).timestamp() * 1000),
            'title': title,
        }
        if impact:
            item['impact'] = impact
        if timestamp:
            item['timestamp'] = timestamp
        else:
            item['timestamp'] = datetime.now(timezone.utc).isoformat()

        message = {
            'type': 'publish_item',
            'item': item,
        }

        if hub == 'all':
            results = self.send_to_all(message)
            success = any(r.get('success') for r in results.values())
            if success:
                self.costs.publishes += 1
                self._log_event(
                    'all', 'publish',
                    f'Published to all hubs: "{title[:50]}"',
                    details={'category_id': category_id, 'hubs': list(results.keys())}
                )
            return {'success': success, 'results': results}
        else:
            result = self.send_to_hub(hub, message)
            if result.get('success'):
                self.costs.publishes += 1
                self._log_event(
                    hub, 'publish',
                    f'Published: "{title[:50]}"',
                    details={'category_id': category_id}
                )
            return result

    def get_costs(self) -> dict:
        return {
            'connects': self.costs.connects,
            'disconnects': self.costs.disconnects,
            'publishes': self.costs.publishes,
            'broadcasts': self.costs.broadcasts,
            'messages_sent': self.costs.messages_sent,
            'messages_received': self.costs.messages_received,
        }

    def reset_costs(self):
        self.costs = CostCounters()

    def _ensure_inactivity_monitor(self):
        if self._inactivity_thread and self._inactivity_thread.is_alive():
            return

        self._stop_inactivity_check.clear()
        self._inactivity_thread = threading.Thread(
            target=self._run_inactivity_monitor,
            daemon=True
        )
        self._inactivity_thread.start()

    def _run_inactivity_monitor(self):
        while not self._stop_inactivity_check.is_set():
            time.sleep(60)

            if self._stop_inactivity_check.is_set():
                break

            any_connected = any(
                conn.state.connected for conn in self.connections.values()
            )
            if not any_connected:
                continue

            if self.last_global_activity:
                elapsed = (datetime.now(timezone.utc) - self.last_global_activity).total_seconds()
                if elapsed > INACTIVITY_TIMEOUT_SECONDS:
                    logger.warning("Disconnecting all hubs due to inactivity (%.1f hours)", elapsed / 3600)
                    self._log_event(
                        'all', 'disconnect',
                        f'Disconnected all hubs due to {elapsed / 3600:.1f}h inactivity',
                        level='warning'
                    )
                    self.disconnect_all()


hub_manager = LiveFeedHubManager()
