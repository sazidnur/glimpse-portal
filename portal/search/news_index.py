from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable

from django.conf import settings
from django.db.models import Q

from api.v1.resources import _news_serializer
from portal.models import News, SearchReindexJob

from .client import MeiliError, get_client

logger = logging.getLogger(__name__)

DISPLAYED_FIELDS = [
    'id', 'title', 'summary', 'source', 'imageurl', 'timestamp',
    'score', 'topic_id', 'category_id', 'division_id',
]
INDEX_SETTINGS = {
    'searchableAttributes': ['title', 'summary'],
    'displayedAttributes': DISPLAYED_FIELDS,
    'filterableAttributes': ['category_id', 'topic_id', 'division_id'],
    'sortableAttributes': ['published_at'],
    'rankingRules': ['words', 'typo', 'proximity', 'attribute', 'sort', 'exactness', 'published_at:desc'],
}
PRIMARY_KEY = 'id'
BATCH_SIZE = 1000
SOURCE_SEARCH_ENGINE = '1'
SOURCE_DATABASE = '2'
MAX_QUERY_LENGTH = 100
MIN_QUERY_LENGTH = 2


class RebuildCancelled(Exception):
    pass


def index_uid() -> str:
    return settings.MEILI_NEWS_INDEX


def rebuild_index_uid(job_id: int) -> str:
    return f'{index_uid()}__rebuild_{job_id}'


def to_document(news: News) -> dict:
    return {
        **_news_serializer(news),
        'published_at': int(news.timestamp.timestamp()) if news.timestamp else 0,
    }


def ensure_index(uid: str | None = None) -> None:
    uid = uid or index_uid()
    client = get_client()
    index = client.request('GET', f'/indexes/{uid}', missing_ok=True)
    if index is None:
        client.wait_for_task(client.request('POST', '/indexes', json={'uid': uid, 'primaryKey': PRIMARY_KEY}))
    elif index.get('primaryKey') != PRIMARY_KEY:
        client.wait_for_task(client.request('PATCH', f'/indexes/{uid}', json={'primaryKey': PRIMARY_KEY}))
    client.wait_for_task(client.request('PATCH', f'/indexes/{uid}/settings', json=INDEX_SETTINGS))


def delete_index(uid: str) -> None:
    client = get_client()
    if client.request('GET', f'/indexes/{uid}', missing_ok=True) is not None:
        client.wait_for_task(client.request('DELETE', f'/indexes/{uid}'))


def add_documents(documents: list[dict], uid: str | None = None) -> None:
    client = get_client()
    client.wait_for_task(
        client.request(
            'POST',
            f'/indexes/{uid or index_uid()}/documents',
            json=documents,
            params={'primaryKey': PRIMARY_KEY},
        )
    )


def delete_documents(ids: list[int], uid: str | None = None) -> None:
    client = get_client()
    client.wait_for_task(client.request('POST', f'/indexes/{uid or index_uid()}/documents/delete-batch', json=ids))


def write_targets() -> list[str]:
    targets = [index_uid()]
    running = SearchReindexJob.objects.filter(status=SearchReindexJob.Status.RUNNING).values_list('id', flat=True)
    targets.extend(rebuild_index_uid(job_id) for job_id in running)
    return targets


def upsert(news_ids: Iterable[int]) -> int:
    documents = [to_document(news) for news in News.objects.filter(id__in=list(news_ids))]
    if documents:
        for uid in write_targets():
            add_documents(documents, uid)
    return len(documents)


def remove(news_ids: Iterable[int]) -> None:
    ids = list(news_ids)
    if ids:
        for uid in write_targets():
            delete_documents(ids, uid)


def document_count(uid: str | None = None) -> int:
    stats = get_client().request('GET', f'/indexes/{uid or index_uid()}/stats', missing_ok=True)
    return int((stats or {}).get('numberOfDocuments', 0))


def rebuild(
    job_id: int,
    *,
    on_progress: Callable[[int, int], None] = lambda indexed, total: None,
    should_stop: Callable[[], bool] = lambda: False,
) -> dict:
    target = rebuild_index_uid(job_id)
    delete_index(target)
    ensure_index(target)

    queryset = News.objects.order_by('id')
    total = queryset.count()
    indexed = 0
    on_progress(indexed, total)
    for start in range(0, total, BATCH_SIZE):
        if should_stop():
            raise RebuildCancelled
        batch = list(queryset[start:start + BATCH_SIZE])
        add_documents([to_document(news) for news in batch], target)
        indexed += len(batch)
        on_progress(indexed, total)

    current_ids = set(News.objects.values_list('id', flat=True))
    orphans = [doc_id for doc_id in indexed_ids(target) if doc_id not in current_ids]
    for start in range(0, len(orphans), BATCH_SIZE):
        delete_documents(orphans[start:start + BATCH_SIZE], target)

    if should_stop():
        raise RebuildCancelled
    ensure_index()
    client = get_client()
    client.wait_for_task(client.request('POST', '/swap-indexes', json=[{'indexes': [index_uid(), target]}]))
    return {'indexed': indexed, 'removed': len(orphans)}


def discard_rebuild(job_id: int) -> None:
    delete_index(rebuild_index_uid(job_id))


def search(query: str, *, page: int, limit: int) -> dict:
    result = get_client().request(
        'POST',
        f'/indexes/{index_uid()}/search',
        json={'q': query, 'page': page, 'hitsPerPage': limit, 'attributesToRetrieve': DISPLAYED_FIELDS},
    )
    return {
        'items': result['hits'],
        'total': result['totalHits'],
        'page': result['page'],
        'limit': limit,
        'pages': result['totalPages'],
    }


def search_database(query: str, *, page: int, limit: int) -> dict:
    condition = Q()
    for word in query.split():
        condition &= Q(title__icontains=word) | Q(summary__icontains=word)
    queryset = News.objects.filter(condition).order_by('-timestamp')
    total = queryset.count()
    start = (page - 1) * limit
    return {
        'items': [_news_serializer(news) for news in queryset[start:start + limit]],
        'total': total,
        'page': page,
        'limit': limit,
        'pages': math.ceil(total / limit) if total else 0,
    }


def search_with_fallback(query: str, *, page: int, limit: int) -> tuple[dict, str]:
    try:
        return search(query, page=page, limit=limit), SOURCE_SEARCH_ENGINE
    except (MeiliError, KeyError) as exc:
        logger.warning('Meilisearch search failed, using database fallback: %s', exc)
        return search_database(query, page=page, limit=limit), SOURCE_DATABASE


def indexed_ids(uid: str | None = None) -> list[int]:
    client = get_client()
    ids: list[int] = []
    offset = 0
    while True:
        page = client.request(
            'GET',
            f'/indexes/{uid or index_uid()}/documents',
            params={'fields': 'id', 'limit': BATCH_SIZE, 'offset': offset},
        )
        ids.extend(int(doc['id']) for doc in page['results'])
        offset += BATCH_SIZE
        if offset >= page['total']:
            return ids
