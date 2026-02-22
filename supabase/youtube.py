import re
import logging
import math
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import json

from django.conf import settings

logger = logging.getLogger(__name__)

YOUTUBE_SHORT_PATTERNS = [
    re.compile(r'youtu\.be/(?P<id>[a-zA-Z0-9_-]{11})'),
    re.compile(r'youtube\.com/shorts/(?P<id>[a-zA-Z0-9_-]{11})'),
    re.compile(r'youtube\.com/watch\?v=(?P<id>[a-zA-Z0-9_-]{11})'),
    re.compile(r'youtube\.com/embed/(?P<id>[a-zA-Z0-9_-]{11})'),
]


def extract_video_id(url):
    for pattern in YOUTUBE_SHORT_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group('id')
    return None


def _calculate_score(views, likes):
    if views == 0:
        return 0
    reach = min(math.log10(views + 1) / 8, 1.0)
    engagement = min(math.log10(likes + 1) / 6, 1.0) if likes > 0 else 0
    return min(round(reach * 60 + engagement * 40, 1), 100)


def fetch_video_data(url):
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError('Invalid YouTube URL')

    api_key = getattr(settings, 'YOUTUBE_API_KEY', None)
    if not api_key:
        return _fetch_via_oembed(video_id, url)
    return _fetch_via_api(video_id, api_key, url)


def _fetch_via_api(video_id, api_key, original_url):
    params = urlencode({
        'part': 'snippet,statistics',
        'id': video_id,
        'key': api_key,
    })
    api_url = f'https://www.googleapis.com/youtube/v3/videos?{params}'
    req = Request(api_url, headers={'Accept': 'application/json'})

    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    items = data.get('items', [])
    if not items:
        raise ValueError('Video not found')

    snippet = items[0]['snippet']
    stats = items[0].get('statistics', {})
    thumbnails = snippet.get('thumbnails', {})
    thumbnail_url = (
        thumbnails.get('maxres', {}).get('url')
        or thumbnails.get('high', {}).get('url')
        or thumbnails.get('medium', {}).get('url')
        or thumbnails.get('default', {}).get('url', '')
    )

    views = int(stats.get('viewCount', 0))
    likes = int(stats.get('likeCount', 0))
    score = _calculate_score(views, likes)

    return {
        'video_id': video_id,
        'title': snippet.get('title', ''),
        'channel_title': snippet.get('channelTitle', ''),
        'channel_id': snippet.get('channelId', ''),
        'thumbnail_url': thumbnail_url,
        'video_url': original_url,
        'score': score,
    }


def _fetch_via_oembed(video_id, original_url):
    params = urlencode({
        'url': f'https://www.youtube.com/watch?v={video_id}',
        'format': 'json',
    })
    oembed_url = f'https://www.youtube.com/oembed?{params}'
    req = Request(oembed_url, headers={'Accept': 'application/json'})

    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    return {
        'video_id': video_id,
        'title': data.get('title', ''),
        'channel_title': data.get('author_name', ''),
        'channel_id': '',
        'thumbnail_url': data.get('thumbnail_url', ''),
        'video_url': original_url,
        'score': 0,
    }


def fetch_channel_icon(channel_url):
    api_key = getattr(settings, 'YOUTUBE_API_KEY', None)
    if not api_key:
        return None

    channel_id = None
    handle = None
    if '/channel/' in channel_url:
        channel_id = channel_url.split('/channel/')[-1].split('/')[0]
    elif '/@' in channel_url:
        handle = channel_url.split('/@')[-1].split('/')[0]

    if channel_id:
        params = urlencode({'part': 'snippet', 'id': channel_id, 'key': api_key})
    elif handle:
        params = urlencode({'part': 'snippet', 'forHandle': handle, 'key': api_key})
    else:
        return None

    api_url = f'https://www.googleapis.com/youtube/v3/channels?{params}'
    req = Request(api_url, headers={'Accept': 'application/json'})

    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        items = data.get('items', [])
        if not items:
            return None
        thumbnails = items[0]['snippet'].get('thumbnails', {})
        return (
            thumbnails.get('high', {}).get('url')
            or thumbnails.get('medium', {}).get('url')
            or thumbnails.get('default', {}).get('url')
        )
    except Exception:
        logger.exception('Failed to fetch channel icon')
        return None
