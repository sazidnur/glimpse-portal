from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from django.db import close_old_connections
from django.db.models import F
from django_redis import get_redis_connection
from websocket import WebSocketTimeoutException

from .manager import hub_manager
from .models import LiveFeedPipeline, LiveFeedPipelineLog
from .pipelines import (
    extract_children_from_ws_message,
    get_pipeline_client,
    is_breaking_item,
    parse_ws_message,
)


logger = logging.getLogger(__name__)

PIPELINE_OWNER_PREFIX = 'live_feed:pipeline:'
PIPELINE_OWNER_SUFFIX = ':owner'
OWNER_TTL_SECONDS = 180
MONITOR_INTERVAL_SECONDS = 3.0
RECONNECT_BASE_DELAY = 2.0
RECONNECT_MAX_DELAY = 45.0
POLL_INTERVAL_SECONDS = 20.0
DISCOVERY_INTERVAL_SECONDS = 300.0


class RestartPipelineLoop(Exception):
    pass


@dataclass
class PipelineStats:
    seen: int = 0
    published: int = 0


class LiveFeedPipelineRunner:
    def __init__(
        self,
        manager: 'LiveFeedPipelineManager',
        *,
        pipeline_id: int,
    ):
        self.manager = manager
        self.pipeline_id = int(pipeline_id)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name=f'lf-pipeline-{pipeline_id}')
        self.ws = None
        self.stats = PipelineStats()
        self.known_ids: set[int] = set()
        self.last_slug = ''

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def _pipeline(self) -> LiveFeedPipeline | None:
        return LiveFeedPipeline.objects.filter(id=self.pipeline_id).select_related('category').first()

    def _refresh_owner(self):
        self.manager.refresh_owner(self.pipeline_id)

    def _check_should_run(self) -> bool:
        record = LiveFeedPipeline.objects.filter(id=self.pipeline_id).values('should_run').first()
        return bool(record and record['should_run'])

    @staticmethod
    def _has_connected_hubs() -> bool:
        try:
            states = hub_manager.get_hub_states()
        except Exception:
            return True
        return any(bool(data.get('connected')) for data in states.values())

    def _set_status(
        self,
        status: str,
        *,
        error: str = '',
        stopped: bool = False,
        started: bool = False,
    ):
        now = datetime.now(timezone.utc)
        updates: dict[str, Any] = {
            'status': status,
            'last_error': error or '',
            'last_activity_at': now,
            'owner_instance': self.manager.instance_id if status in (
                LiveFeedPipeline.Status.STARTING,
                LiveFeedPipeline.Status.RUNNING,
                LiveFeedPipeline.Status.ERROR,
            ) else '',
        }
        if started:
            updates['last_started_at'] = now
        if stopped:
            updates['last_stopped_at'] = now
        LiveFeedPipeline.objects.filter(id=self.pipeline_id).update(**updates)

    def _auto_stop(self, reason: str):
        now = datetime.now(timezone.utc)
        LiveFeedPipeline.objects.filter(id=self.pipeline_id).update(
            should_run=False,
            status=LiveFeedPipeline.Status.STOPPED,
            last_error=reason,
            last_stopped_at=now,
            last_activity_at=now,
            owner_instance='',
        )
        self.manager.log(
            self.pipeline_id,
            event_type=LiveFeedPipelineLog.EventType.STOP,
            level=LiveFeedPipelineLog.LogLevel.WARNING,
            message=reason,
        )

    def _increment_seen(self):
        self.stats.seen += 1
        LiveFeedPipeline.objects.filter(id=self.pipeline_id).update(
            total_seen=F('total_seen') + 1,
            last_activity_at=datetime.now(timezone.utc),
        )

    def _increment_published(self):
        self.stats.published += 1
        LiveFeedPipeline.objects.filter(id=self.pipeline_id).update(
            total_published=F('total_published') + 1,
            last_activity_at=datetime.now(timezone.utc),
        )

    def _current_default_impact(self, fallback: int = 2) -> int:
        row = LiveFeedPipeline.objects.filter(id=self.pipeline_id).values('default_impact').first()
        if not row:
            return max(0, min(2, int(fallback)))
        raw_impact = row.get('default_impact')
        if raw_impact is None:
            raw_impact = fallback
        return max(0, min(2, int(raw_impact)))

    def _process_child_ids(
        self,
        client,
        *,
        child_ids: list[int],
        category_id: int,
    ):
        default_impact = self._current_default_impact()
        new_ids = [child_id for child_id in child_ids if child_id not in self.known_ids]
        if not new_ids:
            return

        for child_id in reversed(new_ids):
            if self.stop_event.is_set() or not self._check_should_run():
                return

            self.known_ids.add(child_id)
            self._increment_seen()

            item = client.fetch_live_item(child_id=child_id)
            if not item:
                continue

            if not is_breaking_item(item):
                continue

            title = str(item.get('title') or '').strip()
            if not title:
                continue

            timestamp = item.get('date') or item.get('timestamp')
            publish_result = hub_manager.publish_item(
                hub='all',
                category_id=category_id,
                title=title,
                impact=max(0, min(2, int(default_impact))),
                timestamp=timestamp,
            )
            success = bool(publish_result.get('success'))
            result_map = publish_result.get('results') if isinstance(publish_result, dict) else {}
            successful_hubs = []
            failed_hubs = []
            if isinstance(result_map, dict):
                for hub_name, hub_result in result_map.items():
                    if isinstance(hub_result, dict) and hub_result.get('success'):
                        successful_hubs.append(hub_name)
                    else:
                        failed_hubs.append(hub_name)
            if success:
                self._increment_published()
                self.manager.log(
                    self.pipeline_id,
                    event_type=LiveFeedPipelineLog.EventType.PUBLISH,
                    level=LiveFeedPipelineLog.LogLevel.INFO,
                    message=f'Published breaking title: "{title[:120]}"',
                    details={
                        'child_id': child_id,
                        'category_id': category_id,
                        'impact': max(0, min(2, int(default_impact))),
                        'successful_hubs': successful_hubs,
                        'failed_hubs': failed_hubs,
                    },
                )
                if failed_hubs:
                    self.manager.log(
                        self.pipeline_id,
                        event_type=LiveFeedPipelineLog.EventType.UPDATE,
                        level=LiveFeedPipelineLog.LogLevel.WARNING,
                        message='Partial publish: some hubs did not receive item',
                        details={'child_id': child_id, 'failed_hubs': failed_hubs},
                    )
            else:
                self.manager.log(
                    self.pipeline_id,
                    event_type=LiveFeedPipelineLog.EventType.ERROR,
                    level=LiveFeedPipelineLog.LogLevel.ERROR,
                    message='Failed to publish breaking title to hubs',
                    details={
                        'child_id': child_id,
                        'category_id': category_id,
                        'result': publish_result,
                    },
                )

    def run(self):
        close_old_connections()
        reconnect_delay = RECONNECT_BASE_DELAY
        self._set_status(LiveFeedPipeline.Status.STARTING, started=True)
        self.manager.log(
            self.pipeline_id,
            event_type=LiveFeedPipelineLog.EventType.START,
            level=LiveFeedPipelineLog.LogLevel.INFO,
            message='Pipeline worker started',
        )

        try:
            while not self.stop_event.is_set():
                close_old_connections()
                self._refresh_owner()

                if not self._check_should_run():
                    break

                pipeline = self._pipeline()
                if not pipeline:
                    break
                try:
                    client = get_pipeline_client(pipeline.source)
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc

                if not self._has_connected_hubs():
                    self._auto_stop('Auto-stopped: all hubs are disconnected')
                    break

                try:
                    target = client.discover_latest_live_target()
                    if self.last_slug and self.last_slug != target.slug:
                        self.known_ids.clear()
                    self.last_slug = target.slug
                    parent_id, current_children = client.fetch_parent_and_children(
                        slug=target.slug,
                        fallback_post_id=target.post_id,
                    )
                    if not self.known_ids:
                        self.known_ids.update(current_children)
                    else:
                        self._process_child_ids(
                            client,
                            child_ids=current_children,
                            category_id=int(pipeline.category_id),
                        )
                        self.known_ids.update(current_children)

                    self.ws = client.connect_live_ws(post_id=parent_id)
                    reconnect_delay = RECONNECT_BASE_DELAY
                    self._set_status(LiveFeedPipeline.Status.RUNNING)
                    self.manager.log(
                        self.pipeline_id,
                        event_type=LiveFeedPipelineLog.EventType.UPDATE,
                        level=LiveFeedPipelineLog.LogLevel.INFO,
                        message=f'Subscribed to {target.slug}',
                        details={'parent_id': parent_id, 'known_children': len(self.known_ids)},
                    )

                    next_poll = time.time() + POLL_INTERVAL_SECONDS
                    next_discovery = time.time() + DISCOVERY_INTERVAL_SECONDS

                    while not self.stop_event.is_set():
                        self._refresh_owner()
                        if not self._check_should_run():
                            return
                        if not self._has_connected_hubs():
                            self._auto_stop('Auto-stopped: all hubs are disconnected')
                            return

                        now = time.time()
                        recv_timeout = max(0.5, min(client.ws_timeout, max(0.1, next_poll - now)))
                        self.ws.settimeout(recv_timeout)

                        try:
                            message = parse_ws_message(self.ws.recv())
                            message_type = str(message.get('type') or '')
                            if message_type == 'ping':
                                self.ws.send(json.dumps({'type': 'pong'}))
                            elif message_type == 'next':
                                child_ids = extract_children_from_ws_message(message)
                                self._process_child_ids(
                                    client,
                                    child_ids=child_ids,
                                    category_id=int(pipeline.category_id),
                                )
                                self.known_ids.update(child_ids)
                            elif message_type == 'complete':
                                raise RestartPipelineLoop()
                        except WebSocketTimeoutException:
                            pass

                        now = time.time()
                        if now >= next_poll:
                            polled_children = client.fetch_children_only(slug=target.slug)
                            self._process_child_ids(
                                client,
                                child_ids=polled_children,
                                category_id=int(pipeline.category_id),
                            )
                            self.known_ids.update(polled_children)
                            next_poll = now + POLL_INTERVAL_SECONDS

                        if now >= next_discovery:
                            refreshed = client.discover_latest_live_target()
                            if refreshed.slug != target.slug:
                                raise RestartPipelineLoop()
                            next_discovery = now + DISCOVERY_INTERVAL_SECONDS

                except RestartPipelineLoop:
                    if self.ws is not None:
                        try:
                            self.ws.close()
                        except Exception:
                            pass
                        self.ws = None
                    continue
                except Exception as exc:
                    self._set_status(LiveFeedPipeline.Status.ERROR, error=str(exc))
                    self.manager.log(
                        self.pipeline_id,
                        event_type=LiveFeedPipelineLog.EventType.ERROR,
                        level=LiveFeedPipelineLog.LogLevel.ERROR,
                        message=f'Pipeline runtime error: {exc}',
                    )
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(RECONNECT_MAX_DELAY, reconnect_delay * 2)
                finally:
                    if self.ws is not None:
                        try:
                            self.ws.close()
                        except Exception:
                            pass
                        self.ws = None
        finally:
            close_old_connections()
            snapshot = LiveFeedPipeline.objects.filter(id=self.pipeline_id).values('should_run', 'last_error').first()
            should_run = bool(snapshot and snapshot.get('should_run'))
            preserved_error = str((snapshot or {}).get('last_error') or '')
            self._set_status(
                LiveFeedPipeline.Status.STOPPED if not should_run else LiveFeedPipeline.Status.ERROR,
                error=preserved_error if not should_run else 'Pipeline stopped unexpectedly',
                stopped=True,
            )
            self.manager.release_owner(self.pipeline_id)
            self.manager.log(
                self.pipeline_id,
                event_type=LiveFeedPipelineLog.EventType.STOP,
                level=LiveFeedPipelineLog.LogLevel.INFO,
                message='Pipeline worker stopped',
                details={'seen': self.stats.seen, 'published': self.stats.published},
            )


class LiveFeedPipelineManager:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.instance_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._runners: dict[int, LiveFeedPipelineRunner] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _decode(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='ignore')
        if value is None:
            return ''
        return str(value)

    @staticmethod
    def _owner_key(pipeline_id: int) -> str:
        return f"{PIPELINE_OWNER_PREFIX}{int(pipeline_id)}{PIPELINE_OWNER_SUFFIX}"

    @staticmethod
    def _redis():
        return get_redis_connection('default')

    def start_monitor(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._run_monitor,
            daemon=True,
            name='lf-pipeline-monitor',
        )
        self._monitor_thread.start()

    def stop_monitor(self):
        self._stop_event.set()
        with self._lock:
            runners = list(self._runners.values())
        for runner in runners:
            runner.stop()

    def get_owner(self, pipeline_id: int) -> str:
        key = self._owner_key(pipeline_id)
        try:
            return self._decode(self._redis().get(key)).strip()
        except Exception:
            return ''

    def claim_owner(self, pipeline_id: int) -> bool:
        key = self._owner_key(pipeline_id)
        try:
            redis = self._redis()
            current = self._decode(redis.get(key)).strip()
            if current == self.instance_id:
                redis.expire(key, OWNER_TTL_SECONDS)
                return True
            return bool(redis.set(key, self.instance_id, nx=True, ex=OWNER_TTL_SECONDS))
        except Exception:
            return False

    def refresh_owner(self, pipeline_id: int):
        key = self._owner_key(pipeline_id)
        try:
            redis = self._redis()
            current = self._decode(redis.get(key)).strip()
            if current in ('', self.instance_id):
                redis.set(key, self.instance_id, ex=OWNER_TTL_SECONDS)
        except Exception:
            pass

    def release_owner(self, pipeline_id: int):
        key = self._owner_key(pipeline_id)
        try:
            redis = self._redis()
            current = self._decode(redis.get(key)).strip()
            if current == self.instance_id:
                redis.delete(key)
        except Exception:
            pass

    def log(self, pipeline_id: int, *, event_type: str, level: int, message: str, details: dict | None = None):
        pipeline = LiveFeedPipeline.objects.filter(id=pipeline_id).first()
        if not pipeline:
            return
        LiveFeedPipelineLog.log(
            pipeline=pipeline,
            event_type=event_type,
            level=level,
            message=message,
            details=details,
        )

    def request_reconcile(self):
        self._reconcile_once()

    def stop_local_runner(self, pipeline_id: int):
        with self._lock:
            runner = self._runners.get(int(pipeline_id))
        if runner:
            runner.stop()

    def _run_monitor(self):
        while not self._stop_event.is_set():
            try:
                self._reconcile_once()
            except Exception:
                logger.exception("Pipeline monitor reconcile failed")
            time.sleep(MONITOR_INTERVAL_SECONDS)

    def _cleanup_finished(self):
        with self._lock:
            dead_ids = [pid for pid, runner in self._runners.items() if not runner.is_alive()]
            for pid in dead_ids:
                self._runners.pop(pid, None)

    def _reconcile_once(self):
        close_old_connections()
        self._cleanup_finished()

        desired_ids = set(
            LiveFeedPipeline.objects
            .filter(should_run=True)
            .values_list('id', flat=True)
        )

        with self._lock:
            running_ids = set(self._runners.keys())

        # stop local runners no longer requested
        for pipeline_id in sorted(running_ids - desired_ids):
            self.stop_local_runner(pipeline_id)

        # start requested pipelines when this instance can own
        for pipeline_id in sorted(desired_ids):
            with self._lock:
                if pipeline_id in self._runners and self._runners[pipeline_id].is_alive():
                    continue
            if not self.claim_owner(pipeline_id):
                continue

            LiveFeedPipeline.objects.filter(id=pipeline_id).update(
                owner_instance=self.instance_id,
                status=LiveFeedPipeline.Status.STARTING,
                last_error='',
            )
            runner = LiveFeedPipelineRunner(self, pipeline_id=pipeline_id)
            with self._lock:
                self._runners[pipeline_id] = runner
            runner.start()


pipeline_manager = LiveFeedPipelineManager()
