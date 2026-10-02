from __future__ import annotations

import logging

from celery import current_app
from django.db import IntegrityError, transaction
from django.utils import timezone

from portal.models import SearchReindexJob

from . import news_index

logger = logging.getLogger(__name__)

Status = SearchReindexJob.Status
Trigger = SearchReindexJob.Trigger


class ReindexAlreadyRunning(Exception):
    def __init__(self, job: SearchReindexJob | None):
        self.job = job
        super().__init__(f'{job} is still active' if job else 'Another reindex is still active')


def active_job() -> SearchReindexJob | None:
    return SearchReindexJob.objects.filter(is_active=True).first()


def create_job(trigger: str, user=None) -> SearchReindexJob:
    try:
        with transaction.atomic():
            return SearchReindexJob.objects.create(trigger=trigger, created_by=user)
    except IntegrityError:
        raise ReindexAlreadyRunning(active_job()) from None


def start(trigger: str = Trigger.MANUAL, user=None) -> SearchReindexJob:
    job = create_job(trigger, user)
    transaction.on_commit(lambda: _enqueue(job.id))
    return job


def run(job_id: int) -> None:
    claimed = SearchReindexJob.objects.filter(id=job_id, status=Status.QUEUED).update(
        status=Status.RUNNING,
        started_at=timezone.now(),
    )
    if not claimed:
        return

    def on_progress(indexed: int, total: int) -> None:
        SearchReindexJob.objects.filter(id=job_id).update(indexed=indexed, total=total, updated_at=timezone.now())

    def should_stop() -> bool:
        return SearchReindexJob.objects.filter(id=job_id).exclude(status=Status.RUNNING).exists()

    try:
        result = news_index.rebuild(job_id, on_progress=on_progress, should_stop=should_stop)
    except news_index.RebuildCancelled:
        _discard(job_id)
        _finish(job_id, Status.CANCELLED)
    except Exception as exc:
        logger.exception('Search reindex #%s failed', job_id)
        _discard(job_id)
        _finish(job_id, Status.FAILED, error=f'{type(exc).__name__}: {exc}'[:2000])
    else:
        _finish(job_id, Status.SUCCEEDED, indexed=result['indexed'], removed=result['removed'])


def cancel(job: SearchReindexJob) -> str:
    if job.status == Status.QUEUED:
        _revoke(job)
        _finish(job.id, Status.CANCELLED)
        return 'Reindex cancelled.'
    if job.status == Status.RUNNING:
        SearchReindexJob.objects.filter(id=job.id, status=Status.RUNNING).update(status=Status.CANCELLING)
        return 'Cancelling. The current batch finishes first; cancel again to force-stop a stuck job.'
    if job.status == Status.CANCELLING:
        _revoke(job)
        _discard(job.id)
        _finish(job.id, Status.CANCELLED, error='Force-cancelled by admin')
        return 'Reindex force-cancelled.'
    return f'A {job.get_status_display().lower()} reindex cannot be cancelled.'


def _finish(job_id: int, status: str, **fields) -> None:
    SearchReindexJob.objects.filter(id=job_id, is_active=True).update(
        status=status,
        is_active=False,
        finished_at=timezone.now(),
        **fields,
    )


def _discard(job_id: int) -> None:
    try:
        news_index.discard_rebuild(job_id)
    except Exception:
        logger.warning('Could not delete rebuild index for reindex #%s', job_id, exc_info=True)


def _revoke(job: SearchReindexJob) -> None:
    if job.celery_task_id:
        current_app.control.revoke(job.celery_task_id)


def _enqueue(job_id: int) -> None:
    from portal.tasks import search_reindex_job

    result = search_reindex_job.delay(job_id)
    SearchReindexJob.objects.filter(id=job_id).update(celery_task_id=result.id)
