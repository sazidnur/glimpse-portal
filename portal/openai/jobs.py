from __future__ import annotations

from typing import Any

from celery import current_app
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..live_feed.manager import hub_manager
from ..models import LiveFeedPipeline, LiveFeedPipelineLog, OpenAIJob, OpenAIJobLog


VALID_OPENAI_MODES = {'off', 'realtime', 'batch'}
DEFAULT_OPENAI_MODE = 'batch'
DEFAULT_REALTIME_MODEL = 'gpt-5.4-mini'
DEFAULT_BATCH_MODEL = 'gpt-5.4-mini'
DEFAULT_BATCH_TIMEOUT_MINUTES = 30
DEFAULT_BATCH_MAX_ITEMS = 100


def _as_config(config: Any) -> dict[str, Any]:
    return config if isinstance(config, dict) else {}


def _clean_model_name(value: Any, *, fallback: str) -> str:
    model = str(value or '').strip()
    return model or fallback


def _clean_positive_int(value: Any, *, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(fallback)
    return max(1, parsed)


def resolve_pipeline_openai_mode(_source_key: str, *, pipeline_config: dict[str, Any] | None = None) -> str:
    config = _as_config(pipeline_config)
    mode = str(config.get('openai_mode') or '').strip().lower()
    if mode not in VALID_OPENAI_MODES:
        mode = DEFAULT_OPENAI_MODE
    return mode


def resolve_pipeline_realtime_model(*, pipeline_config: dict[str, Any] | None = None) -> str:
    config = _as_config(pipeline_config)
    return _clean_model_name(config.get('openai_realtime_model'), fallback=DEFAULT_REALTIME_MODEL)


def resolve_pipeline_batch_model(*, pipeline_config: dict[str, Any] | None = None) -> str:
    config = _as_config(pipeline_config)
    return _clean_model_name(config.get('openai_batch_model'), fallback=DEFAULT_BATCH_MODEL)


def resolve_pipeline_batch_timeout_minutes(*, pipeline_config: dict[str, Any] | None = None) -> int:
    config = _as_config(pipeline_config)
    return _clean_positive_int(config.get('openai_batch_timeout_minutes'), fallback=DEFAULT_BATCH_TIMEOUT_MINUTES)


def resolve_pipeline_batch_max_items(*, pipeline_config: dict[str, Any] | None = None) -> int:
    config = _as_config(pipeline_config)
    return _clean_positive_int(config.get('openai_batch_max_items'), fallback=DEFAULT_BATCH_MAX_ITEMS)


def _job_provider_request(job: OpenAIJob) -> dict[str, Any]:
    return _as_config(job.provider_request)


def resolve_job_realtime_model(job: OpenAIJob) -> str:
    req = _job_provider_request(job)
    return _clean_model_name(req.get('realtime_model'), fallback=DEFAULT_REALTIME_MODEL)


def resolve_job_batch_model(job: OpenAIJob) -> str:
    req = _job_provider_request(job)
    return _clean_model_name(req.get('batch_model'), fallback=DEFAULT_BATCH_MODEL)


def resolve_job_batch_timeout_minutes(job: OpenAIJob) -> int:
    req = _job_provider_request(job)
    return _clean_positive_int(req.get('batch_timeout_minutes'), fallback=DEFAULT_BATCH_TIMEOUT_MINUTES)


def openai_is_available() -> bool:
    return bool(str(getattr(settings, 'OPENAI_API_KEY', '') or '').strip())


def log_openai_job(
    job: OpenAIJob,
    message: str,
    *,
    level: int = OpenAIJobLog.Level.INFO,
    details: dict[str, Any] | None = None,
):
    OpenAIJobLog.log(job=job, message=message, level=level, details=details)
    if job.pipeline_id:
        event_type = LiveFeedPipelineLog.EventType.UPDATE
        pipeline_level = LiveFeedPipelineLog.LogLevel.INFO
        if level >= OpenAIJobLog.Level.WARNING:
            pipeline_level = LiveFeedPipelineLog.LogLevel.WARNING
        if level >= OpenAIJobLog.Level.ERROR:
            event_type = LiveFeedPipelineLog.EventType.ERROR
            pipeline_level = LiveFeedPipelineLog.LogLevel.ERROR
        pipeline = LiveFeedPipeline.objects.filter(id=job.pipeline_id).first()
        if pipeline:
            LiveFeedPipelineLog.log(
                pipeline=pipeline,
                event_type=event_type,
                level=pipeline_level,
                message=message,
                details=details,
            )


def enqueue_pipeline_translation_job(
    *,
    pipeline_id: int,
    source: str,
    source_item_id: str,
    category_id: int,
    impact: int,
    timestamp: str | None,
    original_title: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    response_schema: dict[str, Any],
    target_lang: str = 'en',
    target_hub: str = 'all',
    mode: str | None = None,
    pipeline_config: dict[str, Any] | None = None,
) -> tuple[OpenAIJob | None, bool]:
    config = _as_config(pipeline_config)
    resolved_mode = mode or resolve_pipeline_openai_mode(source, pipeline_config=config)
    if resolved_mode == 'off' or not openai_is_available():
        return None, False

    requested_mode = OpenAIJob.Mode.BATCH if resolved_mode == 'batch' else OpenAIJob.Mode.REALTIME
    initial_status = (
        OpenAIJob.Status.BATCH_QUEUED
        if requested_mode == OpenAIJob.Mode.BATCH
        else OpenAIJob.Status.REALTIME_QUEUED
    )
    provider_request = {
        'realtime_model': resolve_pipeline_realtime_model(pipeline_config=config),
        'batch_model': resolve_pipeline_batch_model(pipeline_config=config),
        'batch_timeout_minutes': resolve_pipeline_batch_timeout_minutes(pipeline_config=config),
    }

    with transaction.atomic():
        job, created = OpenAIJob.objects.get_or_create(
            source=str(source),
            source_item_id=str(source_item_id),
            target_lang=str(target_lang or 'en'),
            defaults={
                'pipeline_id': int(pipeline_id),
                'category_id': int(category_id),
                'impact': int(impact),
                'timestamp': str(timestamp or ''),
                'target_hub': str(target_hub or 'all'),
                'mode': requested_mode,
                'status': initial_status,
                'system_prompt': str(system_prompt or ''),
                'user_payload': user_payload or {},
                'response_schema': response_schema or {},
                'original_title': str(original_title or ''),
                'provider_request': provider_request,
            },
        )

        if not created:
            return job, False

    log_openai_job(
        job,
        f'Created OpenAI job in {requested_mode} mode',
        details={'status': initial_status, 'source_item_id': source_item_id, 'provider_request': provider_request},
    )

    if requested_mode == OpenAIJob.Mode.REALTIME:
        from ..tasks import openai_process_realtime_job

        async_result = openai_process_realtime_job.delay(job.id)
        OpenAIJob.objects.filter(id=job.id).update(celery_task_id=async_result.id)

    return job, True


def cancel_openai_job(job: OpenAIJob, *, reason: str) -> OpenAIJob:
    from .client import cancel_batch

    now = timezone.now()
    details: dict[str, Any] = {'reason': reason}

    if job.celery_task_id:
        try:
            current_app.control.revoke(job.celery_task_id, terminate=False)
            details['celery_revoked'] = True
        except Exception as exc:
            details['celery_revoke_error'] = str(exc)

    job.cancel_requested = True

    batch_states = {
        OpenAIJob.Status.BATCH_QUEUED,
        OpenAIJob.Status.BATCH_SUBMITTED,
        OpenAIJob.Status.BATCH_TIMEOUT,
    }

    if job.status in batch_states and job.provider_batch_id:
        try:
            cancel_resp = cancel_batch(job.provider_batch_id)
            details['batch_cancel_response'] = cancel_resp
            OpenAIJob.objects.filter(
                provider_batch_id=job.provider_batch_id,
                status__in=[
                    OpenAIJob.Status.BATCH_QUEUED,
                    OpenAIJob.Status.BATCH_SUBMITTED,
                    OpenAIJob.Status.BATCH_TIMEOUT,
                ],
            ).update(
                cancel_requested=True,
                status=OpenAIJob.Status.CANCELLED,
                cancelled_at=now,
                error_message='Cancelled manually',
            )
            job.refresh_from_db()
        except Exception as exc:
            job.status = OpenAIJob.Status.CANCEL_REQUESTED
            job.error_message = f'Cancel requested; provider cancel failed: {exc}'
    elif job.status in {OpenAIJob.Status.REALTIME_QUEUED, OpenAIJob.Status.BATCH_QUEUED, OpenAIJob.Status.QUEUED}:
        job.status = OpenAIJob.Status.CANCELLED
        job.cancelled_at = now
        job.error_message = 'Cancelled manually'
    elif job.status == OpenAIJob.Status.REALTIME_RUNNING:
        job.status = OpenAIJob.Status.CANCEL_REQUESTED
        job.error_message = 'Cancel requested while realtime task is running'
    elif not job.is_terminal:
        job.status = OpenAIJob.Status.CANCELLED
        job.cancelled_at = now
        job.error_message = 'Cancelled manually'

    job.save(
        update_fields=[
            'cancel_requested',
            'status',
            'cancelled_at',
            'error_message',
            'updated_at',
        ]
    )
    log_openai_job(job, 'Job cancellation requested', level=OpenAIJobLog.Level.WARNING, details=details)
    return job


def publish_completed_job(job_id: int) -> bool:
    with transaction.atomic():
        job = OpenAIJob.objects.select_for_update().filter(id=job_id).first()
        if not job:
            return False
        if job.cancel_requested:
            job.status = OpenAIJob.Status.CANCELLED
            job.cancelled_at = timezone.now()
            job.save(update_fields=['status', 'cancelled_at', 'updated_at'])
            log_openai_job(job, 'Skipped publish because job was cancelled', level=OpenAIJobLog.Level.WARNING)
            return False
        if job.status != OpenAIJob.Status.COMPLETED:
            return False
        if not job.translated_title.strip():
            job.status = OpenAIJob.Status.FAILED
            job.error_message = 'No translated title to publish'
            job.save(update_fields=['status', 'error_message', 'updated_at'])
            log_openai_job(job, 'Publish failed: missing translated title', level=OpenAIJobLog.Level.ERROR)
            return False

        publish_result = hub_manager.publish_item(
            hub=job.target_hub or 'all',
            category_id=int(job.category_id),
            title=job.translated_title.strip(),
            impact=int(job.impact),
            timestamp=(job.timestamp or None),
        )

        if bool(publish_result.get('success')):
            job.status = OpenAIJob.Status.PUBLISHED
            job.published_at = timezone.now()
            job.publish_result = publish_result
            job.save(update_fields=['status', 'published_at', 'publish_result', 'updated_at'])
            if job.pipeline_id:
                LiveFeedPipeline.objects.filter(id=job.pipeline_id).update(
                    total_published=F('total_published') + 1,
                    last_activity_at=timezone.now(),
                )
                pipeline = LiveFeedPipeline.objects.filter(id=job.pipeline_id).first()
                if pipeline:
                    LiveFeedPipelineLog.log(
                        pipeline=pipeline,
                        event_type=LiveFeedPipelineLog.EventType.PUBLISH,
                        level=LiveFeedPipelineLog.LogLevel.INFO,
                        message=f'Published translated title: "{job.translated_title[:120]}"',
                        details={
                            'source_item_id': job.source_item_id,
                            'impact': int(job.impact),
                            'openai_job_id': job.id,
                        },
                    )
            log_openai_job(job, 'Published translated title to hubs')
            return True

        job.status = OpenAIJob.Status.FAILED
        job.error_message = f'Publish failed: {publish_result}'
        job.publish_result = publish_result
        job.save(update_fields=['status', 'error_message', 'publish_result', 'updated_at'])
        log_openai_job(job, 'Publish failed after translation', level=OpenAIJobLog.Level.ERROR, details=publish_result)
        return False
