from __future__ import annotations

import os

from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'openai-submit-batch-jobs': {
        'task': 'portal.tasks.openai_submit_batch_jobs',
        'schedule': 30.0,
    },
    'openai-poll-batch-jobs': {
        'task': 'portal.tasks.openai_poll_batch_jobs',
        'schedule': 60.0,
    },
}
