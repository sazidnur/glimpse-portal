import re
import logging
import math
import shutil
import subprocess
from urllib.request import (
    urlopen,
    Request,
    build_opener,
    HTTPRedirectHandler,
)
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.parse import urlparse
import json

from django.conf import settings

logger = logging.getLogger(__name__)

YOUTUBE_SHORT_PATTERNS = [
    re.compile(r'youtu\.be/(?P<id>[a-zA-Z0-9_-]{11})'),
    re.compile(r'youtube\.com/shorts/(?P<id>[a-zA-Z0-9_-]{11})'),
    re.compile(r'youtube\.com/watch\?v=(?P<id>[a-zA-Z0-9_-]{11})'),
    re.compile(r'youtube\.com/embed/(?P<id>[a-zA-Z0-9_-]{11})'),
]

YOUTUBE_ALLOWED_HOSTS = {
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'music.youtube.com',
    'youtu.be',
    'www.youtu.be',
}

REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


NO_REDIRECT_OPENER = build_opener(_NoRedirectHandler)


def is_youtube_url(url):
    if not isinstance(url, str) or not url.strip():
        return False

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    if parsed.scheme not in {'http', 'https'}:
        return False

    host = (parsed.hostname or '').lower()
    return host in YOUTUBE_ALLOWED_HOSTS


def is_shorts_video_id(video_id):
    if not video_id:
        return False

    # Preferred path: use curl header check (matches runtime behavior seen in container).
    # A real short returns 2xx on /shorts/{id}; non-short redirects to /watch?v={id}.
    curl_bin = shutil.which('curl')
    if curl_bin:
        shorts_url = f'https://www.youtube.com/shorts/{video_id}'
        cmd = [
            curl_bin,
            '-sS',
            '-I',
            '--max-redirs',
            '0',
            shorts_url,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            raw = (proc.stdout or '') + '\n' + (proc.stderr or '')
            statuses = re.findall(r'(?im)^HTTP/\S+\s+(\d{3})\b', raw)
            locations = re.findall(r'(?im)^location:\s*(.+)$', raw)

            status_code = int(statuses[-1]) if statuses else 0
            location = (locations[-1].strip() if locations else '')

            if 200 <= status_code < 300:
                return True

            if status_code in REDIRECT_STATUS_CODES:
                if '/watch?v=' in location:
                    return False
                if '/shorts/' in location:
                    return True
                if 'consent.youtube.com' in location:
                    raise ValueError('Could not validate YouTube Shorts URL right now')
                return False
        except ValueError:
            raise
        except Exception:
            # Fall through to urllib fallback
            pass

    # Fallback path when curl is unavailable
    shorts_url = f'https://www.youtube.com/shorts/{video_id}'
    req = Request(
        shorts_url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            )
        },
    )

    try:
        with NO_REDIRECT_OPENER.open(req, timeout=10) as resp:
            status_code = int(getattr(resp, 'status', 200))
            return 200 <= status_code < 300
    except HTTPError as exc:
        status_code = int(exc.code)
        location = str((exc.headers or {}).get('Location', ''))
        if status_code in REDIRECT_STATUS_CODES:
            if '/watch?v=' in location:
                return False
            if '/shorts/' in location:
                return True
            if 'consent.youtube.com' in location:
                raise ValueError('Could not validate YouTube Shorts URL right now')
            return False
        if int(exc.code) == 404:
            return False
        raise ValueError('Could not validate YouTube Shorts URL right now')
    except URLError:
        raise ValueError('Could not validate YouTube Shorts URL right now')


def validate_youtube_shorts_url(url):
    if not is_youtube_url(url):
        raise ValueError('Only YouTube URLs are allowed')

    normalized_url = url.strip()
    video_id = extract_video_id(normalized_url)
    if not video_id:
        raise ValueError('Invalid YouTube video URL')

    # Strict mode: always verify by video ID redirect behavior, regardless of URL shape.
    try:
        if is_shorts_video_id(video_id):
            return video_id
    except ValueError:
        raise ValueError('Could not validate YouTube Shorts URL right now')

    raise ValueError('Only YouTube Shorts URLs are allowed')


def extract_video_id(url):
    for pattern in YOUTUBE_SHORT_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group('id')
    return None


def _calculate_score(views, likes):
    if views == 0:
        return 50.0
    rate = likes / views
    if rate >= 0.08:
        return 90.0
    elif rate >= 0.05:
        return 75.0
    elif rate >= 0.03:
        return 60.0
    elif rate >= 0.01:
        return 40.0
    return 20.0


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
        'published_at': snippet.get('publishedAt', ''),
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
        'published_at': '',
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
