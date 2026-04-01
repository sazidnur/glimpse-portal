from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import OpenAIJob, OpenAIJobLog
from .openai.client import (
    create_batch,
    extract_structured_output_from_batch_row,
    fetch_batch_output_lines,
    retrieve_batch,
    run_realtime_translation,
)
from .openai.jobs import (
    DEFAULT_BATCH_MAX_ITEMS,
    log_openai_job,
    publish_completed_job,
    resolve_job_batch_model,
    resolve_job_batch_timeout_minutes,
    resolve_job_realtime_model,
)


def _terminal(status: str) -> bool:
    return status in {
        OpenAIJob.Status.PUBLISHED,
        OpenAIJob.Status.FAILED,
        OpenAIJob.Status.CANCELLED,
    }


def _queue_realtime_for_job(job: OpenAIJob, *, reason: str):
    if job.cancel_requested or _terminal(job.status):
        return
    job.status = OpenAIJob.Status.REALTIME_QUEUED
    job.error_message = reason
    job.save(update_fields=['status', 'error_message', 'updated_at'])
    async_result = openai_process_realtime_job.delay(job.id)
    OpenAIJob.objects.filter(id=job.id).update(celery_task_id=async_result.id)
    log_openai_job(
        job,
        'Queued realtime fallback',
        level=OpenAIJobLog.Level.WARNING,
        details={'reason': reason},
    )


@shared_task(name='portal.tasks.openai_process_realtime_job')
def openai_process_realtime_job(job_id: int):
    with transaction.atomic():
        job = OpenAIJob.objects.select_for_update().filter(id=job_id).first()
        if not job or _terminal(job.status):
            return
        if job.status != OpenAIJob.Status.REALTIME_QUEUED:
            return
        if job.cancel_requested:
            job.status = OpenAIJob.Status.CANCELLED
            job.cancelled_at = timezone.now()
            job.save(update_fields=['status', 'cancelled_at', 'updated_at'])
            return
        job.status = OpenAIJob.Status.REALTIME_RUNNING
        job.error_message = ''
        job.save(update_fields=['status', 'error_message', 'updated_at'])

    try:
        parsed, response_id, raw_response = run_realtime_translation(
            model=resolve_job_realtime_model(job),
            system_prompt=str(job.system_prompt or ''),
            user_payload=job.user_payload or {},
            response_schema=job.response_schema or {},
        )
    except Exception as exc:
        with transaction.atomic():
            failed = OpenAIJob.objects.select_for_update().filter(id=job_id).first()
            if not failed or _terminal(failed.status):
                return
            failed.status = OpenAIJob.Status.FAILED
            failed.error_message = f'Realtime translation failed: {exc}'
            failed.save(update_fields=['status', 'error_message', 'updated_at'])
            log_openai_job(failed, failed.error_message, level=OpenAIJobLog.Level.ERROR)
        return

    translated = str(parsed.get('t') or '').strip()
    with transaction.atomic():
        updated = OpenAIJob.objects.select_for_update().filter(id=job_id).first()
        if not updated or _terminal(updated.status):
            return
        if updated.cancel_requested:
            updated.status = OpenAIJob.Status.CANCELLED
            updated.cancelled_at = timezone.now()
            updated.save(update_fields=['status', 'cancelled_at', 'updated_at'])
            log_openai_job(updated, 'Discarded realtime result because job was cancelled', level=OpenAIJobLog.Level.WARNING)
            return
        if not translated:
            updated.status = OpenAIJob.Status.FAILED
            updated.error_message = 'Realtime translation returned empty "t" value'
            updated.provider_response = raw_response
            updated.provider_response_id = response_id
            updated.save(update_fields=['status', 'error_message', 'provider_response', 'provider_response_id', 'updated_at'])
            log_openai_job(updated, updated.error_message, level=OpenAIJobLog.Level.ERROR)
            return

        updated.status = OpenAIJob.Status.COMPLETED
        updated.translated_title = translated
        updated.provider_response = raw_response
        updated.provider_response_id = response_id
        updated.save(
            update_fields=[
                'status',
                'translated_title',
                'provider_response',
                'provider_response_id',
                'updated_at',
            ]
        )
        log_openai_job(updated, 'Realtime translation completed')
        openai_publish_job.delay(updated.id)


@shared_task(name='portal.tasks.openai_publish_job')
def openai_publish_job(job_id: int):
    publish_completed_job(int(job_id))


@shared_task(name='portal.tasks.openai_submit_batch_jobs')
def openai_submit_batch_jobs():
    if not str(getattr(settings, 'OPENAI_API_KEY', '') or '').strip():
        return

    queued_jobs = list(
        OpenAIJob.objects
        .filter(
            status=OpenAIJob.Status.BATCH_QUEUED,
            cancel_requested=False,
        )
        .order_by('created_at')[:DEFAULT_BATCH_MAX_ITEMS]
    )
    if not queued_jobs:
        return

    jobs_by_model: dict[str, list[OpenAIJob]] = defaultdict(list)
    for job in queued_jobs:
        jobs_by_model[resolve_job_batch_model(job)].append(job)

    for model, grouped_jobs in jobs_by_model.items():
        requests: list[dict[str, Any]] = []
        for job in grouped_jobs:
            requests.append(
                {
                    'custom_id': str(job.id),
                    'system_prompt': str(job.system_prompt or ''),
                    'user_payload': job.user_payload or {},
                    'response_schema': job.response_schema or {},
                }
            )

        try:
            batch_id, input_file_id = create_batch(
                model=str(model),
                requests=requests,
            )
        except Exception as exc:
            for job in grouped_jobs:
                OpenAIJob.objects.filter(id=job.id).update(
                    status=OpenAIJob.Status.FAILED,
                    error_message=f'Batch submission failed: {exc}',
                )
                refreshed = OpenAIJob.objects.filter(id=job.id).first()
                if refreshed:
                    log_openai_job(refreshed, refreshed.error_message, level=OpenAIJobLog.Level.ERROR)
            continue

        for job in grouped_jobs:
            timeout_minutes = resolve_job_batch_timeout_minutes(job)
            deadline = timezone.now() + timedelta(minutes=timeout_minutes)
            provider_request = dict(job.provider_request or {})
            provider_request['input_file_id'] = input_file_id
            OpenAIJob.objects.filter(id=job.id).update(
                status=OpenAIJob.Status.BATCH_SUBMITTED,
                provider_batch_id=batch_id,
                provider_request=provider_request,
                batch_deadline_at=deadline,
                error_message='',
            )
            refreshed = OpenAIJob.objects.filter(id=job.id).first()
            if refreshed:
                log_openai_job(
                    refreshed,
                    'Submitted to OpenAI batch',
                    details={
                        'batch_id': batch_id,
                        'deadline_at': deadline.isoformat(),
                        'batch_model': model,
                    },
                )


def _handle_batch_timeouts():
    now = timezone.now()
    timed_out_jobs = list(
        OpenAIJob.objects
        .filter(
            status=OpenAIJob.Status.BATCH_SUBMITTED,
            cancel_requested=False,
            batch_deadline_at__lt=now,
        )
        .exclude(provider_batch_id='')
    )
    if not timed_out_jobs:
        return

    batch_ids = sorted({job.provider_batch_id for job in timed_out_jobs if job.provider_batch_id})
    for batch_id in batch_ids:
        from .openai.client import cancel_batch

        try:
            cancel_batch(batch_id)
        except Exception:
            pass

    for job in timed_out_jobs:
        job.status = OpenAIJob.Status.BATCH_TIMEOUT
        job.error_message = 'Batch exceeded timeout and was cancelled; falling back to realtime'
        job.save(update_fields=['status', 'error_message', 'updated_at'])
        log_openai_job(job, job.error_message, level=OpenAIJobLog.Level.WARNING)
        _queue_realtime_for_job(job, reason='Fallback from batch timeout')


@shared_task(name='portal.tasks.openai_poll_batch_jobs')
def openai_poll_batch_jobs():
    if not str(getattr(settings, 'OPENAI_API_KEY', '') or '').strip():
        return

    _handle_batch_timeouts()

    batch_ids = list(
        OpenAIJob.objects
        .filter(status=OpenAIJob.Status.BATCH_SUBMITTED, cancel_requested=False)
        .exclude(provider_batch_id='')
        .values_list('provider_batch_id', flat=True)
        .distinct()
    )
    for batch_id in batch_ids:
        try:
            batch = retrieve_batch(str(batch_id))
        except Exception:
            continue

        batch_status = str(batch.get('status') or '').strip().lower()
        jobs = list(
            OpenAIJob.objects.filter(
                provider_batch_id=batch_id,
                status=OpenAIJob.Status.BATCH_SUBMITTED,
            )
        )
        if not jobs:
            continue

        if batch_status == 'completed':
            output_file_id = str(batch.get('output_file_id') or '')
            if not output_file_id:
                for job in jobs:
                    job.status = OpenAIJob.Status.FAILED
                    job.error_message = 'Batch completed without output_file_id'
                    job.save(update_fields=['status', 'error_message', 'updated_at'])
                    log_openai_job(job, job.error_message, level=OpenAIJobLog.Level.ERROR)
                continue

            try:
                rows = fetch_batch_output_lines(output_file_id)
            except Exception as exc:
                for job in jobs:
                    _queue_realtime_for_job(job, reason=f'Batch output fetch failed: {exc}')
                continue

            rows_by_custom_id = {}
            for row in rows:
                custom_id = str(row.get('custom_id') or '')
                if custom_id:
                    rows_by_custom_id[custom_id] = row

            for job in jobs:
                if job.cancel_requested:
                    job.status = OpenAIJob.Status.CANCELLED
                    job.cancelled_at = timezone.now()
                    job.save(update_fields=['status', 'cancelled_at', 'updated_at'])
                    log_openai_job(job, 'Ignored completed batch row because job was cancelled', level=OpenAIJobLog.Level.WARNING)
                    continue

                row = rows_by_custom_id.get(str(job.id))
                if not row:
                    _queue_realtime_for_job(job, reason='Batch output missing row for job')
                    continue

                try:
                    parsed = extract_structured_output_from_batch_row(row)
                except Exception as exc:
                    _queue_realtime_for_job(job, reason=f'Batch row parse failed: {exc}')
                    continue

                translated = str(parsed.get('t') or '').strip()
                if not translated:
                    _queue_realtime_for_job(job, reason='Batch row returned empty "t" value')
                    continue

                job.status = OpenAIJob.Status.COMPLETED
                job.translated_title = translated
                job.provider_response = row
                job.save(update_fields=['status', 'translated_title', 'provider_response', 'updated_at'])
                log_openai_job(job, 'Batch translation completed')
                openai_publish_job.delay(job.id)
            continue

        if batch_status in {'failed', 'expired'}:
            for job in jobs:
                _queue_realtime_for_job(job, reason=f'Batch status={batch_status}; fallback to realtime')
            continue

        if batch_status in {'cancelled', 'cancelling'}:
            for job in jobs:
                job.status = OpenAIJob.Status.CANCELLED
                job.cancelled_at = timezone.now()
                job.error_message = 'Batch cancelled'
                job.save(update_fields=['status', 'cancelled_at', 'error_message', 'updated_at'])
                log_openai_job(job, 'Batch cancelled by provider', level=OpenAIJobLog.Level.WARNING)
