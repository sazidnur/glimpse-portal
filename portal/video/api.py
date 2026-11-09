"""Endpoints for the renderer: it claims the next queued video, renders it, and posts the result back.

The renderer only talks to these endpoints, so it can run on any machine that can reach the portal.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import NewsVideo, Sourcealias
from .pipeline import fail, source_name

Status = NewsVideo.Status
# A render that has not reported back by then is assumed lost (renderer restarted) and is handed out again.
STALE_RENDER = timedelta(minutes=60)


class CanRenderVideos(BasePermission):
    def has_permission(self, request, view):
        return request.user.has_perm('data.change_newsvideo')


class RenderClaimView(APIView):
    permission_classes = [IsAuthenticated, CanRenderVideos]

    def post(self, request):
        with transaction.atomic():
            video = (NewsVideo.objects.select_for_update(skip_locked=True)
                     .filter(Q(status=Status.QUEUED)
                             | Q(status=Status.RENDERING, render_started_at__lt=timezone.now() - STALE_RENDER))
                     .order_by('publish_at').first())
            if not video:
                return Response(status=204)
            video.status = Status.RENDERING
            video.render_started_at = timezone.now()
            video.save(update_fields=['status', 'render_started_at', 'updated_at'])
        return Response({'id': video.id, 'composition': video.series.template, 'props': render_props(video)})


class RenderResultView(APIView):
    permission_classes = [IsAuthenticated, CanRenderVideos]

    def get(self, request, pk):
        video = get_object_or_404(NewsVideo, pk=pk)
        return Response({'id': video.id, 'composition': video.series.template, 'props': render_props(video)})

    def post(self, request, pk):
        video = get_object_or_404(NewsVideo, pk=pk, status=Status.RENDERING)
        error = str(request.data.get('error') or '').strip()
        if error:
            fail(video.id, f'Render failed: {error}')
            return Response({'status': Status.FAILED})
        file, thumbnail = request.FILES.get('video'), request.FILES.get('thumbnail')
        if not file:
            return Response({'error': 'Send the rendered MP4 as "video", or an "error".'}, status=400)

        name = uuid.uuid4().hex
        for field, upload, extension in ((video.video, file, 'mp4'), (video.thumbnail, thumbnail, 'jpg')):
            if field:
                field.delete(save=False)
            if upload:
                field.save(f'{name}.{extension}', upload, save=False)
        video.status = Status.RENDERED
        video.error = ''
        video.save(update_fields=['video', 'thumbnail', 'status', 'error', 'updated_at'])
        return Response({'status': video.status})


def render_props(video: NewsVideo) -> dict:
    """The template's inputs: the script with each scene's image and timing, the voice, and the series' branding."""
    series = video.series
    news = {item.id: item for item in video.news.all()}
    aliases = list(Sourcealias.objects.all())
    timings = video.timings or {}
    scenes = []
    for scene, timing in zip(video.script.get('scenes', []), timings.get('scenes', [])):
        ids = [i for i in scene['news_ids'] if i in news]
        scenes.append({
            'narration': scene['narration'],
            'caption': scene['caption'],
            'imageUrl': next((news[i].imageurl for i in ids if (news[i].imageurl or '').startswith('https://')), None),
            'sources': list(dict.fromkeys(source_name(news[i].source, aliases) for i in ids)),
            'start': timing['start'],
            'end': timing['end'],
        })
    return {
        **series.template_props,
        'series': series.name,
        'title': video.script.get('title', ''),
        'durationInSeconds': timings.get('duration', 0),
        'audioUrl': _url(video.audio),
        'musicUrl': _url(series.music),
        'musicVolume': series.music_volume,
        'logoUrl': _url(series.logo),
        'scenes': scenes,
        'words': timings.get('words', []),
    }


def _url(file) -> str | None:
    return f"{settings.SITE_URL.rstrip('/')}{file.url}" if file else None
