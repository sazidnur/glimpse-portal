"""Serves uploaded and generated media (news video voice, renders, music), with byte ranges so videos can seek."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils._os import safe_join

RANGE = re.compile(r'bytes=(\d*)-(\d*)$')
CHUNK = 256 * 1024


def serve_media(request, path):
    try:
        file = Path(safe_join(settings.MEDIA_ROOT, path))
    except SuspiciousFileOperation:
        raise Http404
    if not file.is_file():
        raise Http404
    size = file.stat().st_size
    content_type = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
    match = RANGE.match(request.headers.get('Range', ''))

    if not match or match.groups() == ('', ''):
        response = FileResponse(file.open('rb'), content_type=content_type)
    else:
        first, last = match.groups()
        if first:
            start, end = int(first), min(int(last) if last else size - 1, size - 1)
        else:
            start, end = max(size - int(last), 0), size - 1
        if start > end:
            return HttpResponse(status=416, headers={'Content-Range': f'bytes */{size}'})
        response = StreamingHttpResponse(_read(file, start, end - start + 1), status=206, content_type=content_type)
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
        response['Content-Length'] = str(end - start + 1)
    response['Accept-Ranges'] = 'bytes'
    # The renderer's browser reads the voice with fetch() to find its pauses; media is public anyway.
    response['Access-Control-Allow-Origin'] = '*'
    # Generated files get unique names, so a cached copy never goes stale.
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


def _read(file: Path, start: int, length: int):
    with file.open('rb') as handle:
        handle.seek(start)
        while length > 0:
            chunk = handle.read(min(CHUNK, length))
            if not chunk:
                return
            length -= len(chunk)
            yield chunk
