"""Narration with ElevenLabs, plus when each scene and word is spoken, so the template can sync images and captions."""
from __future__ import annotations

import base64
import random
import uuid

import httpx
from django.conf import settings
from django.core.files.base import ContentFile

from ..models import NewsVideo

API_URL = 'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps'


def record(video: NewsVideo) -> None:
    api_key = str(getattr(settings, 'ELEVENLABS_API_KEY', '') or '').strip()
    if not api_key:
        raise RuntimeError('ELEVENLABS_API_KEY is not set, so voice is off.')
    series = video.series
    if not series.voice_id:
        raise RuntimeError(f'Set an ElevenLabs voice ID on the "{series}" series.')

    voice_id = random.choice([v.strip() for v in series.voice_id.split(',') if v.strip()])
    narrations = [scene['narration'].strip() for scene in video.script['scenes']]
    body = {'text': '\n'.join(narrations), 'model_id': series.voice_model, 'language_code': 'bn'}
    if series.voice_speed != 1:
        body['voice_settings'] = {'speed': series.voice_speed}
    response = httpx.post(API_URL.format(voice_id=voice_id), json=body,
                          headers={'xi-api-key': api_key}, timeout=180)
    if response.status_code >= 400:
        raise RuntimeError(f'ElevenLabs HTTP {response.status_code}: {response.text[:300]}')
    data = response.json()

    video.audio.save(f'{uuid.uuid4().hex}.mp3', ContentFile(base64.b64decode(data['audio_base64'])), save=False)
    video.timings = {**align(data['alignment'], narrations), 'voice': voice_id}
    video.status = NewsVideo.Status.QUEUED
    video.error = ''
    video.save(update_fields=['audio', 'timings', 'status', 'error', 'updated_at'])


def align(alignment: dict, narrations: list[str]) -> dict:
    """Scene and word times in seconds from ElevenLabs' per-character alignment.

    Scenes are back to back from 0 to the end of the audio, so the template can cut on the scene boundaries.
    """
    chars = alignment['characters']
    starts = alignment['character_start_times_seconds']
    ends = alignment['character_end_times_seconds']
    spoken = ''.join(chars)
    duration = round(ends[-1], 3) if ends else 0.0

    words, current, in_tag = [], None, False
    for char, start, end in zip(chars, starts, ends):
        # Audio tags such as [serious] steer the voice but are not spoken, so they never become caption words.
        if char in '[]' or in_tag:
            in_tag = char != ']' and (in_tag or char == '[')
            current = None
        elif char.isspace():
            current = None
        elif current is None:
            current = {'text': char, 'start': round(start, 3), 'end': round(end, 3)}
            words.append(current)
        else:
            current['text'] += char
            current['end'] = round(end, 3)

    total = sum(len(text) for text in narrations) or 1
    cursor, offset, scene_starts = 0, 0, []
    for text in narrations:
        found = spoken.find(text, cursor)
        if found >= 0 and starts:
            start = starts[found]
            cursor = found + len(text)
        else:
            start = duration * offset / total
        scene_starts.append(round(max(start, scene_starts[-1] if scene_starts else 0.0), 3))
        offset += len(text)
    scene_starts[0] = 0.0
    scenes = [{'start': start, 'end': scene_starts[i + 1] if i + 1 < len(scene_starts) else duration}
              for i, start in enumerate(scene_starts)]
    return {'duration': duration, 'scenes': scenes, 'words': words}
