from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import PushDevice, PushNotification
from . import fcm
from .apns import APNsClient, APNsConfigError, APNsResult
from .message import PushMessage

logger = logging.getLogger(__name__)

Status = PushNotification.Status

INVALIDATED_RETENTION = timedelta(days=7)
STALE_DEVICE_AGE = timedelta(days=270)


def submit(notification: PushNotification) -> PushNotification:
    is_future = notification.scheduled_at and notification.scheduled_at > timezone.now()
    notification.status = Status.SCHEDULED if is_future else Status.QUEUED
    notification.save()
    if notification.status == Status.QUEUED:
        _enqueue(notification.id)
    return notification


def send_now(notification: PushNotification) -> bool:
    updated = PushNotification.objects.filter(id=notification.id, status=Status.SCHEDULED).update(
        status=Status.QUEUED,
        scheduled_at=timezone.now(),
    )
    if updated:
        _enqueue(notification.id)
    return bool(updated)


def cancel(notification: PushNotification) -> bool:
    return bool(
        PushNotification.objects
        .filter(id=notification.id, status__in=PushNotification.PENDING_STATUSES)
        .update(status=Status.CANCELLED, finished_at=timezone.now())
    )


def release_due() -> int:
    due_ids = list(
        PushNotification.objects
        .filter(status=Status.SCHEDULED, scheduled_at__lte=timezone.now())
        .values_list('id', flat=True)
    )
    released = 0
    for notification_id in due_ids:
        if PushNotification.objects.filter(id=notification_id, status=Status.SCHEDULED).update(status=Status.QUEUED):
            _enqueue(notification_id)
            released += 1
    return released


def deliver(notification_id: int) -> None:
    with transaction.atomic():
        notification = (
            PushNotification.objects
            .select_for_update()
            .filter(id=notification_id, status=Status.QUEUED)
            .first()
        )
        if not notification:
            return
        notification.status = Status.SENDING
        notification.started_at = timezone.now()
        notification.save(update_fields=['status', 'started_at', 'updated_at'])

    message = PushMessage(
        title=notification.title,
        body=notification.body,
        image_url=notification.image_url,
        news_id=notification.news_id,
        collapse_id=notification.collapse_id,
    )
    if notification.includes_android:
        _deliver_android(notification, message)
    if notification.includes_ios:
        _deliver_ios(notification, message)

    notification.status = _final_status(notification)
    notification.finished_at = timezone.now()
    notification.save()
    logger.info(
        'Push %s finished: status=%s fcm=%s ios_sent=%s ios_failed=%s',
        notification.id,
        notification.status,
        notification.fcm_message_id or notification.fcm_error or '-',
        notification.ios_sent,
        notification.ios_failed,
    )


def cleanup_devices() -> int:
    now = timezone.now()
    deleted, _ = PushDevice.objects.filter(invalidated_at__lt=now - INVALIDATED_RETENTION).delete()
    stale, _ = PushDevice.objects.filter(updated_at__lt=now - STALE_DEVICE_AGE).delete()
    return deleted + stale


def ios_audience(topic: str) -> dict[str, list[str]]:
    tokens_by_environment: dict[str, list[str]] = defaultdict(list)
    devices = PushDevice.objects.filter(
        platform=PushDevice.Platform.IOS,
        enabled=True,
        invalidated_at__isnull=True,
        topics__contains=[topic],
    ).values_list('token', 'environment')
    for token, environment in devices:
        tokens_by_environment[environment].append(token)
    return dict(tokens_by_environment)


def _deliver_android(notification: PushNotification, message: PushMessage) -> None:
    try:
        with fcm.FCMClient(
            project_id=settings.FCM_PROJECT_ID,
            service_account_file=settings.FCM_SERVICE_ACCOUNT_FILE,
        ) as client:
            result = client.send(fcm.build_message(message, topic=notification.topic))
    except fcm.FCMConfigError as exc:
        notification.fcm_error = str(exc)
        return
    except Exception as exc:
        logger.exception('FCM send failed for push %s', notification.id)
        notification.fcm_error = f'{type(exc).__name__}: {exc}'
        return
    notification.fcm_message_id = result.message_id
    notification.fcm_error = result.error


def _deliver_ios(notification: PushNotification, message: PushMessage) -> None:
    audience = ios_audience(notification.topic)
    if not audience:
        if notification.target == PushNotification.Target.IOS:
            notification.ios_error = 'No active iOS devices'
        return
    try:
        client = APNsClient(
            key_file=settings.APNS_KEY_FILE,
            key_id=settings.APNS_KEY_ID,
            team_id=settings.APNS_TEAM_ID,
            topic=settings.APNS_TOPIC,
        )
        results = client.send(audience, message)
    except APNsConfigError as exc:
        notification.ios_failed = sum(len(tokens) for tokens in audience.values())
        notification.ios_error = str(exc)
        return
    except Exception as exc:
        logger.exception('APNs send failed for push %s', notification.id)
        notification.ios_failed = sum(len(tokens) for tokens in audience.values())
        notification.ios_error = f'{type(exc).__name__}: {exc}'
        return

    failures = [result for result in results if not result.ok]
    notification.ios_sent = len(results) - len(failures)
    notification.ios_failed = len(failures)
    notification.ios_invalidated = sum(1 for result in failures if result.invalid)
    notification.ios_error = ', '.join(
        f'{reason} ×{count}' for reason, count in Counter(result.reason for result in failures).most_common()
    )
    _record_device_failures(failures)


def _record_device_failures(failures: list[APNsResult]) -> None:
    now = timezone.now()
    tokens_by_reason: dict[tuple[str, bool], list[str]] = defaultdict(list)
    for result in failures:
        tokens_by_reason[(result.reason[:64], result.invalid)].append(result.token)
    for (reason, invalid), tokens in tokens_by_reason.items():
        fields = {'last_error': reason}
        if invalid:
            fields['invalidated_at'] = now
        PushDevice.objects.filter(token__in=tokens).update(**fields)


def _final_status(notification: PushNotification) -> str:
    outcomes = []
    if notification.includes_android:
        outcomes.append(bool(notification.fcm_message_id))
    if notification.includes_ios:
        outcomes.append(not notification.ios_error)
    if all(outcomes):
        return Status.SENT
    if any(outcomes) or notification.ios_sent:
        return Status.PARTIAL
    return Status.FAILED


def _enqueue(notification_id: int) -> None:
    from ..tasks import push_deliver

    transaction.on_commit(lambda: push_deliver.delay(notification_id))
