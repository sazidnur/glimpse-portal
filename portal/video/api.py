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

from ..models import NewsVideo, SocialRender, Sourcealias
from . import social
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
        # A published video rendered again stays published; it is not posted a second time.
        video.status = Status.PUBLISHED if video.published_at else Status.RENDERED
        video.error = ''
        video.save(update_fields=['video', 'thumbnail', 'status', 'error', 'updated_at'])
        return Response({'status': video.status})


class SocialRenderClaimView(APIView):
    """Hands out the next reel or card that waits for its template render."""
    permission_classes = [IsAuthenticated, CanRenderVideos]

    def post(self, request):
        Render = SocialRender.Status
        with transaction.atomic():
            render = (SocialRender.objects.select_for_update(skip_locked=True)
                      .filter(Q(status=Render.QUEUED)
                              | Q(status=Render.RENDERING, render_started_at__lt=timezone.now() - STALE_RENDER))
                      .order_by('created_at').first())
            if not render:
                return Response(status=204)
            render.status, render.render_started_at = Render.RENDERING, timezone.now()
            render.save(update_fields=['status', 'render_started_at'])
        return Response({'id': render.id, 'composition': render.template, 'still': render.is_card,
                         'props': social.render_props(render)})


class SocialRenderResultView(APIView):
    permission_classes = [IsAuthenticated, CanRenderVideos]

    def post(self, request, pk):
        render = get_object_or_404(SocialRender, pk=pk, status=SocialRender.Status.RENDERING)
        error = str(request.data.get('error') or '').strip()
        file = request.FILES.get('image' if render.is_card else 'video')
        if not error and not file:
            return Response({'error': 'Send the render as "video" (or "image" for a card), or an "error".'}, status=400)
        if error:
            render.status, render.error = SocialRender.Status.FAILED, f'Render failed: {error}'
            render.save(update_fields=['status', 'error'])
            return Response({'status': render.status})
        name = uuid.uuid4().hex
        render.file.save(f'{name}.{"jpg" if render.is_card else "mp4"}', file, save=False)
        if thumbnail := request.FILES.get('thumbnail'):
            render.thumbnail.save(f'{name}.jpg', thumbnail, save=False)
        render.status, render.error = SocialRender.Status.READY, ''
        render.save(update_fields=['file', 'thumbnail', 'status', 'error'])
        return Response({'status': render.status})


def render_props(video: NewsVideo) -> dict:
    """The template's inputs: the script with each scene's image and timing, the voice, and the series' branding."""
    series = video.series
    news = {item.id: item for item in video.news.all()}
    aliases = list(Sourcealias.objects.all())
    timings = video.timings or {}
    scenes = []
    for scene, timing in zip(video.script.get('scenes', []), timings.get('scenes', [])):
        ids = [i for i in scene['news_ids'] if i in news]
        images = []
        for i in ids:
            url = news[i].imageurl or ''
            if url.startswith('https://') and url not in (image['url'] for image in images):
                images.append({'url': url, 'source': source_name(news[i].source, aliases)})
        scenes.append({
            'narration': scene['narration'],
            'caption': scene['caption'],
            'imageUrl': images[0]['url'] if images else None,
            'imageSource': images[0]['source'] if images else None,
            'images': images,
            'sources': list(dict.fromkeys(source_name(news[i].source, aliases) for i in ids)),
            'start': timing['start'],
            'end': timing['end'],
        })
    return {
        **series.template_props,
        'series': series.name,
        'title': video.script.get('title', ''),
        'publishAt': video.publish_at.isoformat(),
        'verdict': video.script.get('verdict', 'none'),
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
