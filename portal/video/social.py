"""Uploads videos to the Facebook Page (as a Reel or a video post) and to YouTube as a Short. Each returns the platform's video ID.

Also makes social posts from a template: transcribes the clip for subtitles if asked, then queues the render."""
from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import NewsVideo, SocialPost

logger = logging.getLogger(__name__)

GRAPH_URL = 'https://graph.facebook.com/v27.0'
GRAPH_VIDEO_URL = 'https://graph-video.facebook.com/v27.0'
# Covers the renderer makes are saved under this prefix, so a re-render replaces them but never an uploaded cover.
RENDERED_THUMBNAIL = 'render-'
ELEVENLABS_STT_URL = 'https://api.elevenlabs.io/v1/speech-to-text'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
YOUTUBE_UPLOAD_URL = 'https://www.googleapis.com/upload/youtube/v3/videos'
YOUTUBE_NEWS_CATEGORY = '25'


def publish_facebook(video: NewsVideo) -> str:
    video_id = facebook_reel(video.video, f"{video.script['title']}\n\n{video.script['description']}")
    if video.thumbnail:
        try:
            facebook_thumbnail(video_id, video.thumbnail)
        except Exception:
            # The Reel is up; a missing cover only means Facebook shows the opening frame, the same intro card.
            logger.warning('Setting the thumbnail of Facebook video %s failed', video_id, exc_info=True)
    return video_id


def facebook_reel(file, caption: str) -> str:
    page_id, token = _settings('FACEBOOK_PAGE_ID', 'FACEBOOK_PAGE_TOKEN')
    reels_url = f'{GRAPH_URL}/{page_id}/video_reels'
    start = _json(httpx.post(reels_url, json={'upload_phase': 'start', 'access_token': token}, timeout=30))
    data = _read(file)
    _json(httpx.post(start['upload_url'], content=data, timeout=600, headers={
        'Authorization': f'OAuth {token}', 'offset': '0', 'file_size': str(len(data)),
        'Content-Type': 'application/octet-stream',
    }))
    _json(httpx.post(reels_url, timeout=60, params={
        'access_token': token, 'video_id': start['video_id'], 'upload_phase': 'finish',
        'video_state': 'PUBLISHED', 'description': caption,
    }))
    return str(start['video_id'])


def facebook_video(file, caption: str) -> str:
    """A normal video post on the Page, for videos that cannot be Reels."""
    page_id, token = _settings('FACEBOOK_PAGE_ID', 'FACEBOOK_PAGE_TOKEN')
    reply = _json(httpx.post(f'{GRAPH_VIDEO_URL}/{page_id}/videos', timeout=600,
                             data={'access_token': token, 'description': caption},
                             files={'source': ('video.mp4', _read(file), 'video/mp4')}))
    return str(reply['id'])


def facebook_photo(file, caption: str) -> str:
    """A photo post on the Page."""
    page_id, token = _settings('FACEBOOK_PAGE_ID', 'FACEBOOK_PAGE_TOKEN')
    reply = _json(httpx.post(f'{GRAPH_URL}/{page_id}/photos', timeout=120,
                             data={'access_token': token, 'message': caption, 'published': 'true'},
                             files={'source': (file.name.rsplit('/', 1)[-1], _read(file))}))
    return str(reply['id'])


def facebook_thumbnail(video_id: str, file) -> None:
    """Makes the image the video's preferred thumbnail."""
    _, token = _settings('FACEBOOK_PAGE_ID', 'FACEBOOK_PAGE_TOKEN')
    _json(httpx.post(f'{GRAPH_URL}/{video_id}/thumbnails', timeout=60,
                     data={'access_token': token, 'is_preferred': 'true'},
                     files={'source': (file.name.rsplit('/', 1)[-1], _read(file))}))


def publish_posts_due(now=None) -> list[int]:
    due = SocialPost.objects.filter(status=SocialPost.Status.SCHEDULED, publish_at__lte=now or timezone.now())
    return [post.id for post in due if publish_post(post)]


def publish_post(post: SocialPost) -> bool:
    claimed = SocialPost.objects.filter(pk=post.pk, status=SocialPost.Status.SCHEDULED).update(
        status=SocialPost.Status.PUBLISHING)
    if not claimed:
        return False
    upload = {SocialPost.Format.REEL: facebook_reel, SocialPost.Format.PHOTO: facebook_photo}.get(
        post.facebook_format, facebook_video)
    try:
        post.facebook_id = upload(post.video, post.caption)
        post.status, post.published_at, post.error = SocialPost.Status.PUBLISHED, timezone.now(), ''
    except Exception as exc:
        post.status, post.error = SocialPost.Status.FAILED, f'Facebook: {exc}'
    if post.facebook_id and post.thumbnail and post.facebook_format != SocialPost.Format.PHOTO:
        try:
            facebook_thumbnail(post.facebook_id, post.thumbnail)
        except Exception as exc:
            post.error = f'Posted, but the thumbnail was not set: {exc}'
    post.save(update_fields=['facebook_id', 'status', 'published_at', 'error'])
    return True


def make(post: SocialPost) -> None:
    """(Re)starts a template post: drops the last render, then transcribes the clip if asked, or else queues the render."""
    for field in (post.video, post.thumbnail if is_rendered_thumbnail(post) else None):
        if field:
            field.delete(save=False)
    transcribe_first = post.subtitles and not post.is_card and not post.words
    post.status = SocialPost.Status.TRANSCRIBING if transcribe_first else SocialPost.Status.QUEUED
    post.error, post.facebook_id = '', ''
    post.save()
    if transcribe_first:
        from ..tasks import social_transcribe

        transaction.on_commit(lambda: social_transcribe.delay(post.id))


def is_rendered_thumbnail(post: SocialPost) -> bool:
    return bool(post.thumbnail) and post.thumbnail.name.rsplit('/', 1)[-1].startswith(RENDERED_THUMBNAIL)


def transcribe(post: SocialPost) -> None:
    """Word times of the clip's speech from ElevenLabs Scribe, then queues the render."""
    (api_key,) = _settings('ELEVENLABS_API_KEY')
    reply = _json(httpx.post(ELEVENLABS_STT_URL, timeout=600, headers={'xi-api-key': api_key},
                             data={'model_id': 'scribe_v1', 'language_code': 'ben', 'tag_audio_events': 'false',
                                   'timestamps_granularity': 'word'},
                             files={'file': (post.source.name.rsplit('/', 1)[-1], _read(post.source))}))
    post.words = [{'text': w['text'], 'startMs': round(w['start'] * 1000), 'endMs': round(w['end'] * 1000)}
                  for w in reply.get('words', []) if w.get('type', 'word') == 'word' and w['text'].strip()]
    post.status = SocialPost.Status.QUEUED
    post.save(update_fields=['words', 'status'])


def render_props(post: SocialPost) -> dict:
    """The template's inputs; reels leave `seconds` out, so the renderer measures the clip."""
    source = f"{settings.SITE_URL.rstrip('/')}{post.source.url}"
    props = {'chip': post.chip, 'headline': post.headline, 'credit': post.credit}
    if post.is_card:
        return {**props, 'image': source}
    return {**props, 'clip': source, 'words': post.words if post.subtitles else []}


def publish_youtube(video: NewsVideo) -> str:
    client_id, client_secret, refresh_token = _settings(
        'YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REFRESH_TOKEN')
    access_token = _json(httpx.post(GOOGLE_TOKEN_URL, timeout=30, data={
        'client_id': client_id, 'client_secret': client_secret,
        'refresh_token': refresh_token, 'grant_type': 'refresh_token',
    }))['access_token']
    data = _read(video.video)
    title = video.script['title'].replace('<', '').replace('>', '')[:100]
    session = httpx.post(YOUTUBE_UPLOAD_URL, params={'uploadType': 'resumable', 'part': 'snippet,status'}, timeout=30,
                         headers={'Authorization': f'Bearer {access_token}', 'X-Upload-Content-Length': str(len(data)),
                                  'X-Upload-Content-Type': 'video/mp4'},
                         json={
                             'snippet': {'title': title, 'description': video.script['description'][:5000],
                                         'categoryId': YOUTUBE_NEWS_CATEGORY, 'defaultLanguage': 'bn',
                                         'defaultAudioLanguage': 'bn'},
                             'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False},
                         })
    _json(session)
    uploaded = httpx.put(session.headers['Location'], content=data, timeout=600,
                         headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'video/mp4'})
    return str(_json(uploaded)['id'])


def missing_settings(series) -> list[str]:
    names = ['OPENAI_API_KEY', 'ELEVENLABS_API_KEY']
    if series.publish_facebook:
        names += ['FACEBOOK_PAGE_ID', 'FACEBOOK_PAGE_TOKEN']
    if series.publish_youtube:
        names += ['YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REFRESH_TOKEN']
    return [name for name in names if not str(getattr(settings, name, '') or '').strip()]


def _settings(*names: str) -> list[str]:
    values = [str(getattr(settings, name, '') or '').strip() for name in names]
    if not all(values):
        raise RuntimeError(f'{", ".join(names)} must be set.')
    return values


def _read(field) -> bytes:
    with field.open('rb') as file:
        return file.read()


def _json(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f'HTTP {response.status_code}: {response.text[:300]}')
    return response.json() if response.content else {}
