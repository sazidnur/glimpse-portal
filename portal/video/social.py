"""Uploads a rendered video as a Facebook Page Reel and a YouTube Short. Each returns the platform's video ID."""
from __future__ import annotations

import httpx
from django.conf import settings

from ..models import NewsVideo

GRAPH_URL = 'https://graph.facebook.com/v27.0'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
YOUTUBE_UPLOAD_URL = 'https://www.googleapis.com/upload/youtube/v3/videos'
YOUTUBE_NEWS_CATEGORY = '25'


def publish_facebook(video: NewsVideo) -> str:
    page_id, token = _settings('FACEBOOK_PAGE_ID', 'FACEBOOK_PAGE_TOKEN')
    reels_url = f'{GRAPH_URL}/{page_id}/video_reels'
    start = _json(httpx.post(reels_url, json={'upload_phase': 'start', 'access_token': token}, timeout=30))
    data = _read(video)
    _json(httpx.post(start['upload_url'], content=data, timeout=600, headers={
        'Authorization': f'OAuth {token}', 'offset': '0', 'file_size': str(len(data)),
        'Content-Type': 'application/octet-stream',
    }))
    _json(httpx.post(reels_url, timeout=60, params={
        'access_token': token, 'video_id': start['video_id'], 'upload_phase': 'finish',
        'video_state': 'PUBLISHED', 'description': f"{video.script['title']}\n\n{video.script['description']}",
    }))
    return str(start['video_id'])


def publish_youtube(video: NewsVideo) -> str:
    client_id, client_secret, refresh_token = _settings(
        'YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REFRESH_TOKEN')
    access_token = _json(httpx.post(GOOGLE_TOKEN_URL, timeout=30, data={
        'client_id': client_id, 'client_secret': client_secret,
        'refresh_token': refresh_token, 'grant_type': 'refresh_token',
    }))['access_token']
    data = _read(video)
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


def _read(video: NewsVideo) -> bytes:
    with video.video.open('rb') as file:
        return file.read()


def _json(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f'HTTP {response.status_code}: {response.text[:300]}')
    return response.json() if response.content else {}
