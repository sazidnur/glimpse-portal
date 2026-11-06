"""Twice-daily pushes of the two stories an AI editor expects readers to open most (7:00 and 19:00 Bangladesh time)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.utils import timezone

from api.v1.resources import main_feed_news

from ..models import News, PushNotification
from ..openai.client import run_realtime_translation
from . import service

logger = logging.getLogger(__name__)

BANGLADESH = dt_timezone(timedelta(hours=6))
SEND_HOURS = (7, 19)
PICKS = 2
GAP_BETWEEN_PUSHES = timedelta(minutes=5)
CANDIDATE_WINDOW = timedelta(hours=12)
MAX_CANDIDATES = 60
MODEL = 'gpt-6-luna'

PROMPT = """You are the push notification editor of Glimpse, a Bengali news app in Bangladesh.
From the candidate stories, choose exactly 2 to send as push notifications at {slot} Bangladesh time.
The goal is stories that most readers will want to open, without ever misleading them.

Prefer, in this order:
1. News that directly affects many people in Bangladesh: prices, fuel and utilities, exams and results, holidays, weather alerts, transport, major government decisions.
2. Major developing stories that people are already following.
3. Stories with a strong but honest hook.

Rules:
- The two picks must be about different subjects.
- Prefer stories with an image (has_image true).
- {slot_rule}
- Avoid graphic crime or death-only stories, routine party statements, celebrity gossip and minor local incidents.

For each pick write, in natural Bengali, using only facts from its title and summary:
- title: at most 60 characters, the core news, no clickbait and no exaggeration.
- body: at most 160 characters, the key fact that makes the story worth opening."""

SLOT_RULES = {
    7: 'This is the morning push: favour overnight news and what matters for people today.',
    19: 'This is the evening push: favour the biggest developments of the day.',
}


def next_send_time(now: datetime) -> datetime:
    local = now.astimezone(BANGLADESH)
    slots = [(local + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
             for days in (0, 1) for hour in SEND_HOURS]
    return next(slot for slot in slots if slot > local)


def schedule_digest(now: datetime | None = None) -> list[PushNotification]:
    now = now or timezone.now()
    send_at = next_send_time(now)
    keys = [f'digest-{send_at:%Y%m%d%H}-{i}' for i in range(PICKS)]
    if PushNotification.objects.filter(idempotency_key__in=keys).exists():
        return []

    candidates = list(
        main_feed_news()
        .filter(timestamp__gte=now - CANDIDATE_WINDOW, push_notifications__isnull=True)
        .select_related('categoryid', 'topic')
        .order_by('-timestamp')[:MAX_CANDIDATES]
    )
    if len(candidates) < PICKS:
        logger.warning('Push digest for %s skipped: only %d candidate stories', send_at, len(candidates))
        return []

    by_id = {news.id: news for news in candidates}
    scheduled = []
    for pick in _pick(candidates, send_at):
        news = by_id.get(pick['news_id'])
        if not news or news.id in {p.news_id for p in scheduled}:
            continue
        notification = PushNotification(
            source=PushNotification.Source.NEWS,
            news=news,
            title=pick['title'].strip()[:120],
            body=pick['body'].strip()[:300],
            scheduled_at=send_at + GAP_BETWEEN_PUSHES * len(scheduled),
            idempotency_key=keys[len(scheduled)],
            origin=PushNotification.Origin.DIGEST,
        )
        try:
            notification.clean()
            with transaction.atomic():
                scheduled.append(service.submit(notification))
        except IntegrityError:
            break
        if len(scheduled) == PICKS:
            break
    logger.info('Push digest for %s scheduled news %s', send_at, [p.news_id for p in scheduled])
    return scheduled


def _pick(candidates: list[News], send_at: datetime) -> list[dict]:
    payload = {'stories': [
        {
            'id': news.id,
            'title': news.title,
            'summary': news.summary,
            'category': news.categoryid.name if news.categoryid else None,
            'topic': news.topic.name if news.topic else None,
            'has_image': (news.imageurl or '').startswith('https://'),
        }
        for news in candidates
    ]}
    schema = {
        'type': 'object', 'additionalProperties': False, 'required': ['picks'],
        'properties': {'picks': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['news_id', 'title', 'body'],
            'properties': {
                'news_id': {'type': 'integer', 'enum': [news.id for news in candidates]},
                'title': {'type': 'string'},
                'body': {'type': 'string'},
            },
        }}},
    }
    prompt = PROMPT.format(slot=f'{send_at:%-I %p}', slot_rule=SLOT_RULES[send_at.hour])
    try:
        parsed, _, _ = run_realtime_translation(model=MODEL, system_prompt=prompt, user_payload=payload,
                                                response_schema=schema, flex=True)
    except Exception:
        logger.warning('Push digest flex call failed, retrying at standard priority', exc_info=True)
        parsed, _, _ = run_realtime_translation(model=MODEL, system_prompt=prompt, user_payload=payload,
                                                response_schema=schema)
    return [p for p in parsed.get('picks', []) if p.get('title', '').strip() and p.get('body', '').strip()]
