"""Redis-backed RPC between web/celery processes and the live feed service.

Every call gets a real reply (or a timeout) — there is no fire-and-forget.
When the caller runs inside the service process itself, the handler is
invoked directly and Redis is skipped entirely.
"""

import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

REQUEST_QUEUE_KEY = 'live_feed:rpc:requests'
REPLY_KEY_PREFIX = 'live_feed:rpc:reply:'
REPLY_TTL_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 10.0

_local_handler = None


def register_local_handler(handler):
    global _local_handler
    _local_handler = handler


def unregister_local_handler():
    global _local_handler
    _local_handler = None


def _redis():
    return get_redis_connection('default')


def call(action: str, payload: dict = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict:
    if _local_handler is not None:
        try:
            return _local_handler(action, payload or {})
        except Exception as exc:
            logger.exception("Local live feed RPC handler failed for %s", action)
            return {'success': False, 'error': f'Live feed service error: {exc}'}

    request_id = uuid.uuid4().hex
    reply_key = f'{REPLY_KEY_PREFIX}{request_id}'
    request = {
        'id': request_id,
        'action': action,
        'payload': payload or {},
        'reply_key': reply_key,
        'deadline': time.time() + timeout,
    }

    try:
        redis = _redis()
        redis.lpush(REQUEST_QUEUE_KEY, json.dumps(request))
        item = redis.brpop(reply_key, timeout=max(1, int(round(timeout))))
    except Exception as exc:
        logger.error("Live feed RPC transport failed for %s: %s", action, exc)
        return {'success': False, 'error': f'Live feed RPC transport failed: {exc}'}

    if not item:
        return {
            'success': False,
            'error': 'Live feed service did not respond in time (is the service running?)',
            'timeout': True,
        }

    try:
        reply = json.loads(item[1])
    except (TypeError, ValueError):
        return {'success': False, 'error': 'Live feed service returned an invalid reply'}
    return reply if isinstance(reply, dict) else {'success': False, 'error': 'Malformed reply'}


class RpcServer:
    """Consumes the request queue inside the service process and replies
    per-request. Requests past their deadline are dropped (the caller has
    already given up), so a backlog never causes surprise late publishes."""

    def __init__(self, handler, workers: int = 4):
        self._handler = handler
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='lf-rpc')
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='lf-rpc-consumer')
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._pool.shutdown(wait=False)

    def _run(self):
        while not self._stop.is_set():
            try:
                item = _redis().brpop(REQUEST_QUEUE_KEY, timeout=1)
            except Exception:
                self._stop.wait(1)
                continue
            if not item:
                continue
            try:
                request = json.loads(item[1])
            except (TypeError, ValueError):
                continue
            if not isinstance(request, dict):
                continue
            try:
                self._pool.submit(self._process, request)
            except RuntimeError:
                break

    def _process(self, request: dict):
        deadline = float(request.get('deadline') or 0)
        if deadline and time.time() > deadline:
            logger.warning(
                "Dropping expired live feed RPC request: %s", request.get('action')
            )
            return

        close_old_connections()
        action = str(request.get('action') or '')
        try:
            result = self._handler(action, request.get('payload') or {})
        except Exception as exc:
            logger.exception("Live feed RPC handler failed for %s", action)
            result = {'success': False, 'error': f'Live feed service error: {exc}'}

        reply_key = str(request.get('reply_key') or '')
        if not reply_key:
            return
        try:
            redis = _redis()
            redis.lpush(reply_key, json.dumps(result))
            redis.expire(reply_key, REPLY_TTL_SECONDS)
        except Exception:
            logger.exception("Failed to send live feed RPC reply for %s", action)
