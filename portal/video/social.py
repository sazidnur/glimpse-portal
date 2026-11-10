"""Uploads videos to the Facebook Page (as a Reel or a video post) and to YouTube as a Short. Each returns the platform's video ID."""
from __future__ import annotations

import httpx
from django.conf import settings
from django.utils import timezone

from ..models import NewsVideo, SocialPost

GRAPH_URL = 'https://graph.facebook.com/v27.0'
GRAPH_VIDEO_URL = 'https://graph-video.facebook.com/v27.0'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
YOUTUBE_UPLOAD_URL = 'https://www.googleapis.com/upload/youtube/v3/videos'
YOUTUBE_NEWS_CATEGORY = '25'


def publish_facebook(video: NewsVideo) -> str:
    return facebook_reel(video.video, f"{video.script['title']}\n\n{video.script['description']}")


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


def publish_posts_due(now=None) -> list[int]:
    due = SocialPost.objects.filter(status=SocialPost.Status.SCHEDULED, publish_at__lte=now or timezone.now())
    return [post.id for post in due if publish_post(post)]


def publish_post(post: SocialPost) -> bool:
    claimed = SocialPost.objects.filter(pk=post.pk, status=SocialPost.Status.SCHEDULED).update(
        status=SocialPost.Status.PUBLISHING)
    if not claimed:
        return False
    upload = facebook_reel if post.facebook_format == SocialPost.Format.REEL else facebook_video
    try:
        post.facebook_id = upload(post.video, post.caption)
        post.status, post.published_at, post.error = SocialPost.Status.PUBLISHED, timezone.now(), ''
    except Exception as exc:
        post.status, post.error = SocialPost.Status.FAILED, f'Facebook: {exc}'
    post.save(update_fields=['facebook_id', 'status', 'published_at', 'error'])
    return True


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
