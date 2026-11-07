"""Pushes of the stories an AI editor expects readers to open most, at the times set in the admin (AI digest slots)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from api.v1.resources import main_feed_news

from ..models import News, PushDigestSlot, PushNotification
from ..openai.client import run_realtime_translation
from . import service

logger = logging.getLogger(__name__)

BANGLADESH = dt_timezone(timedelta(hours=6))
# Stories are picked this long before the send time, so editors can still edit or cancel them.
LEAD_TIME = timedelta(minutes=30)
CANDIDATE_WINDOW = timedelta(hours=12)
MAX_CANDIDATES = 60
MODEL = 'gpt-6-luna'

PROMPT = """You are the push notification editor of Glimpse, a Bengali news app in Bangladesh.
From the candidate stories, choose exactly {count} to send as push notifications at {slot} Bangladesh time.
The goal is stories that most readers will want to open, without ever misleading them.

Prefer, in this order:
1. News that directly affects many people in Bangladesh: prices, fuel and utilities, exams and results, holidays, weather alerts, transport, major government decisions.
2. Major developing stories that people are already following.
3. Stories with a strong but honest hook.

Rules:
- The picks must be about different subjects.
- Prefer stories with an image (has_image true).
- {slot_rule}
- Avoid graphic crime or death-only stories, routine party statements, celebrity gossip and minor local incidents.

For each pick write, in natural Bengali, using only facts from its title and summary:
- title: at most 60 characters, the core news, no clickbait and no exaggeration.
- body: at most 160 characters, the key fact that makes the story worth opening."""

MORNING_RULE = 'This is the morning push: favour overnight news and what matters for people today.'
EVENING_RULE = 'This is the evening push: favour the biggest developments of the day.'


def due_slots(now: datetime) -> list[tuple[PushDigestSlot, datetime]]:
    """Enabled slots whose send time is less than LEAD_TIME away."""
    local = now.astimezone(BANGLADESH)
    due = []
    for slot in PushDigestSlot.objects.filter(enabled=True):
        for days in (0, 1):
            send_at = datetime.combine(local.date() + timedelta(days=days), slot.send_time, BANGLADESH)
            if send_at - LEAD_TIME <= local < send_at:
                due.append((slot, send_at))
    return due


def schedule_digest(now: datetime | None = None) -> list[PushNotification]:
    now = now or timezone.now()
    return [push for slot, send_at in due_slots(now) for push in schedule_slot(slot, send_at, now)]


def schedule_slot(slot: PushDigestSlot, send_at: datetime, now: datetime) -> list[PushNotification]:
    keys = [f'digest-{send_at:%Y%m%d%H%M}-{i}' for i in range(slot.pushes)]
    already = Q(idempotency_key__in=keys) | Q(origin=PushNotification.Origin.DIGEST, scheduled_at=send_at)
    if PushNotification.objects.filter(already).exists():
        return []

    candidates = list(
        main_feed_news()
        .filter(timestamp__gte=now - CANDIDATE_WINDOW, push_notifications__isnull=True)
        .select_related('categoryid', 'topic')
        .order_by('-timestamp')[:MAX_CANDIDATES]
    )
    if len(candidates) < slot.pushes:
        logger.warning('Push digest for %s skipped: only %d candidate stories', send_at, len(candidates))
        return []

    by_id = {news.id: news for news in candidates}
    scheduled = []
    for pick in _pick(candidates, send_at, slot.pushes):
        news = by_id.get(pick['news_id'])
        if not news or news.id in {p.news_id for p in scheduled}:
            continue
        notification = PushNotification(
            source=PushNotification.Source.NEWS,
            news=news,
            title=pick['title'].strip()[:120],
            body=pick['body'].strip()[:300],
            scheduled_at=send_at + timedelta(minutes=slot.gap_minutes) * len(scheduled),
            idempotency_key=keys[len(scheduled)],
            origin=PushNotification.Origin.DIGEST,
        )
        try:
            notification.clean()
            with transaction.atomic():
                scheduled.append(service.submit(notification))
        except IntegrityError:
            break
        if len(scheduled) == slot.pushes:
            break
    logger.info('Push digest for %s scheduled news %s', send_at, [p.news_id for p in scheduled])
    return scheduled


def _pick(candidates: list[News], send_at: datetime, count: int) -> list[dict]:
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
    prompt = PROMPT.format(count=count, slot=f'{send_at:%-I:%M %p}',
                           slot_rule=MORNING_RULE if send_at.hour < 12 else EVENING_RULE)
    try:
        parsed, _, _ = run_realtime_translation(model=MODEL, system_prompt=prompt, user_payload=payload,
                                                response_schema=schema, flex=True)
    except Exception:
        logger.warning('Push digest flex call failed, retrying at standard priority', exc_info=True)
        parsed, _, _ = run_realtime_translation(model=MODEL, system_prompt=prompt, user_payload=payload,
                                                response_schema=schema)
    return [p for p in parsed.get('picks', []) if p.get('title', '').strip() and p.get('body', '').strip()]
