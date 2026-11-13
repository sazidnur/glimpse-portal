"""News videos: picks the stories for each video series, writes and reviews the script, and publishes the rendered video.

A video moves drafting → review (an editor approves) → voicing → queued → rendering (the renderer) → rendered → published.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from api.v1.resources import main_feed_news

from ..models import News, NewsArticle, NewsVideo, PushNotification, Sourcealias, VideoSeries
from ..openai.client import run_realtime_translation
from ..push.digest import BANGLADESH

logger = logging.getLogger(__name__)

Status = NewsVideo.Status
MAX_CANDIDATES = 300
ARTICLE_CHARS = 6000
STUCK_AFTER = timedelta(minutes=30)
KEEP_FILES = timedelta(days=30)


def due_publish_times(series: VideoSeries, now: datetime) -> list[datetime]:
    """Publish times of the series whose writing window (lead_minutes before) is open now."""
    local = now.astimezone(BANGLADESH)
    lead = timedelta(minutes=series.lead_minutes)
    due = []
    for days in (0, 1):
        day = local.date() + timedelta(days=days)
        if series.weekdays and day.weekday() not in series.weekdays:
            continue
        for at in series.times():
            publish_at = datetime.combine(day, at, BANGLADESH)
            if publish_at - lead <= local < publish_at:
                due.append(publish_at)
    return due


def schedule(now: datetime | None = None) -> list[NewsVideo]:
    now = now or timezone.now()
    created = []
    for series in VideoSeries.objects.filter(enabled=True):
        for publish_at in due_publish_times(series, now):
            video, new = NewsVideo.objects.get_or_create(series=series, slot=publish_at, defaults={'publish_at': publish_at})
            if new:
                created.append(video)
    return created


def draft(video: NewsVideo) -> None:
    series = video.series
    pool = _pool(series)
    pickable = [news for news in pool if news.pickable]
    picks = _pick(series, pool) if pickable else []
    if not picks:
        _update(video, status=Status.SKIPPED, error='No story fits this series right now.')
        return

    by_id = {news.id: news for news in pool}
    articles = dict(NewsArticle.objects.filter(news_id__in=[i for p in picks for i in p]).values_list('news_id', 'text'))
    stories = [
        {**_story(by_id[main], articles), 'related': [_story(by_id[i], articles) for i in related]}
        for main, *related in picks
    ]
    used = [i for p in picks for i in p]
    script = _ask(series.model, series.script_prompt, {
        'series': series.name,
        'target_words': series.target_words,
        'stories': stories,
        'previous': _previous_openings(video),
    }, _script_schema(used))
    script['scenes'] = [s for s in script['scenes'] if s['narration'].strip()]
    if not script['scenes']:
        raise RuntimeError('The script has no narration.')

    issues = []
    if series.ai_review and series.review_prompt.strip():
        edited = _ask(series.model, series.review_prompt, {'script': script, 'stories': stories}, _edit_schema(used))
        issues = edited['issues']
        if _same_shape(script, edited['script']):
            script = edited['script']
        else:
            issues = [{**issue, 'fixed': False} for issue in issues]

    with transaction.atomic():
        video.news.set(used)
        _update(video, script=script, issues=issues, error='',
                status=Status.VOICING if series.auto_approve and all(i['fixed'] for i in issues) else Status.REVIEW)


def approve(video: NewsVideo, user) -> bool:
    if video.status != Status.REVIEW:
        return False
    _update(video, status=Status.VOICING, approved_by=user, error='')
    return True


def retry(video: NewsVideo) -> bool:
    """Continues a failed, skipped or cancelled video from the furthest step it reached."""
    if video.status not in (Status.FAILED, Status.SKIPPED, Status.CANCELLED):
        return False
    if video.video:
        status = Status.RENDERED
    elif video.audio:
        status = Status.QUEUED
    elif video.script:
        status = Status.VOICING
    else:
        status = Status.DRAFTING
    _update(video, status=status, error='')
    return True


def cancel(video: NewsVideo) -> bool:
    if video.status in (Status.PUBLISHING, Status.PUBLISHED, Status.CANCELLED):
        return False
    _update(video, status=Status.CANCELLED)
    return True


def fail(video_id: int, error: str) -> None:
    NewsVideo.objects.filter(pk=video_id).update(status=Status.FAILED, error=error[:2000], updated_at=timezone.now())


def publish_due(now: datetime | None = None) -> list[int]:
    now = now or timezone.now()
    due = NewsVideo.objects.filter(status=Status.RENDERED, publish_at__lte=now).filter(
        Q(series__publish_facebook=True) | Q(series__publish_youtube=True))
    return [video.id for video in due if publish(video)]


def publish(video: NewsVideo) -> bool:
    from . import social

    claimed = NewsVideo.objects.filter(pk=video.pk, status=Status.RENDERED).update(
        status=Status.PUBLISHING, updated_at=timezone.now())
    if not claimed:
        return False
    errors = []
    for enabled, field, platform, upload in (
        (video.series.publish_facebook, 'facebook_id', 'Facebook', social.publish_facebook),
        (video.series.publish_youtube, 'youtube_id', 'YouTube', social.publish_youtube),
    ):
        if enabled and not getattr(video, field):
            try:
                setattr(video, field, upload(video))
            except Exception as exc:
                logger.warning('Publishing video %s to %s failed', video.id, platform, exc_info=True)
                errors.append(f'{platform}: {exc}')
    ids = {'facebook_id': video.facebook_id, 'youtube_id': video.youtube_id}
    if errors:
        _update(video, status=Status.FAILED, error='\n'.join(errors), **ids)
    else:
        _update(video, status=Status.PUBLISHED, published_at=timezone.now(), error='', **ids)
    return True


def stuck(now: datetime | None = None) -> list[NewsVideo]:
    """Videos whose drafting or voicing task was lost, e.g. to a worker restart."""
    cutoff = (now or timezone.now()) - STUCK_AFTER
    return list(NewsVideo.objects.filter(status__in=(Status.DRAFTING, Status.VOICING), updated_at__lt=cutoff))


def delete_old_files(now: datetime | None = None) -> int:
    """Frees disk: keeps each video's record and script, drops its audio and renders after KEEP_FILES."""
    old = NewsVideo.objects.filter(publish_at__lt=(now or timezone.now()) - KEEP_FILES).exclude(
        audio='', video='', thumbnail='')
    count = 0
    for video in old:
        for field in (video.audio, video.video, video.thumbnail):
            if field:
                field.delete(save=False)
        video.save(update_fields=['audio', 'video', 'thumbnail', 'updated_at'])
        count += 1
    return count


def source_name(url: str, aliases: list[Sourcealias]) -> str:
    lowered = (url or '').lower()
    match = next((alias.alias for alias in aliases if alias.source.lower() in lowered), None)
    return match or urlsplit(url or '').netloc.removeprefix('www.')


def _update(video: NewsVideo, **fields) -> None:
    for name, value in fields.items():
        setattr(video, name, value)
    video.save(update_fields=[*fields, 'updated_at'])


def _pool(series: VideoSeries) -> list[News]:
    since = timezone.now() - timedelta(hours=series.candidate_hours)
    feed = main_feed_news()
    if series.category_id:
        feed = feed | News.objects.filter(categoryid=series.category_id)
    pool = list(feed.filter(timestamp__gte=since).select_related('categoryid', 'topic')
                .order_by('-timestamp')[:MAX_CANDIDATES])
    ids = [news.id for news in pool]
    # A story used by any series is not used again by another, so the channel never repeats it.
    used = set(NewsVideo.news.through.objects.filter(news_id__in=ids)
               .exclude(newsvideo__status=Status.CANCELLED).values_list('news_id', flat=True))
    pushed = set(PushNotification.objects.filter(news_id__in=ids).exclude(status=PushNotification.Status.CANCELLED)
                 .values_list('news_id', flat=True))
    aliases = list(Sourcealias.objects.all())
    for news in pool:
        news.pickable = news.id not in used and (not series.category_id or news.categoryid_id == series.category_id)
        news.pushed = news.id in pushed
        news.source_name = source_name(news.source, aliases)
    return pool


def _pick(series: VideoSeries, pool: list[News]) -> list[list[int]]:
    """[[main story id, ids of other articles on the same event], …], at most story_count."""
    pickable = [news.id for news in pool if news.pickable]
    payload = {
        'series': series.name,
        'max_stories': series.story_count,
        'now': f'{timezone.now().astimezone(BANGLADESH):%Y-%m-%d %H:%M}',
        'articles': [{
            'id': news.id,
            'title': news.title,
            'summary': news.summary if news.pickable else None,  # the rest are only matched as coverage, by title
            'source': news.source_name,
            'category': news.categoryid.name if news.categoryid else None,
            'topic': news.topic.name if news.topic else None,
            'published': f'{news.timestamp.astimezone(BANGLADESH):%Y-%m-%d %H:%M}',
            'importance': news.score,
            'pushed': news.pushed,
            'has_image': (news.imageurl or '').startswith('https://'),
            'pickable': news.pickable,
        } for news in pool],
    }
    schema = {
        'type': 'object', 'additionalProperties': False, 'required': ['stories'],
        'properties': {'stories': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['news_id', 'related_ids'],
            'properties': {
                'news_id': {'type': 'integer', 'enum': pickable},
                'related_ids': {'type': 'array', 'items': {'type': 'integer', 'enum': [news.id for news in pool]}},
            },
        }}},
    }
    picks, seen = [], set()
    for story in _ask(series.model, series.pick_prompt, payload, schema)['stories']:
        ids = [i for i in dict.fromkeys([story['news_id'], *story['related_ids']]) if i not in seen]
        if ids and ids[0] == story['news_id']:
            picks.append(ids)
            seen.update(ids)
    return picks[:series.story_count]


def _previous_openings(video: NewsVideo, count: int = 7) -> list[dict]:
    """The series' recent openings and closings, so the next script says them differently."""
    recent = NewsVideo.objects.filter(series=video.series).exclude(pk=video.pk).exclude(script={}).order_by('-publish_at')
    return [{'opening': v.script['scenes'][0]['narration'], 'closing': v.script['scenes'][-1]['narration']}
            for v in recent[:count] if v.script.get('scenes')]


def _story(news: News, articles: dict[int, str]) -> dict:
    return {
        'id': news.id,
        'source': news.source_name,
        'published': f'{news.timestamp.astimezone(BANGLADESH):%Y-%m-%d %H:%M}',
        'title': news.title,
        'summary': news.summary,
        'article': articles[news.id][:ARTICLE_CHARS] if news.id in articles else None,
        'has_image': (news.imageurl or '').startswith('https://'),
    }


def _script_schema(news_ids: list[int]) -> dict:
    return {
        'type': 'object', 'additionalProperties': False, 'required': ['title', 'description', 'verdict', 'scenes'],
        'properties': {
            'title': {'type': 'string'},
            'description': {'type': 'string'},
            'verdict': {'type': 'string', 'enum': ['false', 'misleading', 'true', 'none']},
            'scenes': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['narration', 'caption', 'news_ids'],
                'properties': {
                    'narration': {'type': 'string'},
                    'caption': {'type': 'string'},
                    'news_ids': {'type': 'array', 'items': {'type': 'integer', 'enum': news_ids}},
                },
            }},
        },
    }


def _edit_schema(news_ids: list[int]) -> dict:
    """The AI editor's answer: what it found, and the script with its fixes."""
    return {
        'type': 'object', 'additionalProperties': False, 'required': ['issues', 'script'],
        'properties': {
            'issues': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['scene', 'problem', 'fixed'],
                'properties': {'scene': {'type': 'integer'}, 'problem': {'type': 'string'}, 'fixed': {'type': 'boolean'}},
            }},
            'script': _script_schema(news_ids),
        },
    }


def _same_shape(script: dict, edited: dict) -> bool:
    """The editor may reword scenes but not add, drop or reorder them, or change which stories they show."""
    return [s['news_ids'] for s in script['scenes']] == [s['news_ids'] for s in edited['scenes']] and all(
        s['narration'].strip() and s['caption'].strip() for s in edited['scenes'])


def _ask(model: str, prompt: str, payload: dict, schema: dict) -> dict:
    try:
        parsed, _, _ = run_realtime_translation(model=model, system_prompt=prompt, user_payload=payload,
                                                response_schema=schema, flex=True)
    except Exception:
        logger.warning('Video flex call failed, retrying at standard priority', exc_info=True)
        parsed, _, _ = run_realtime_translation(model=model, system_prompt=prompt, user_payload=payload,
                                                response_schema=schema)
    return parsed
