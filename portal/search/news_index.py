from __future__ import annotations

import logging
import math
from collections.abc import Iterable

from django.conf import settings
from django.db.models import Q

from api.v1.resources import _news_serializer
from portal.models import News

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


def index_uid() -> str:
    return settings.MEILI_NEWS_INDEX


def to_document(news: News) -> dict:
    return {
        **_news_serializer(news),
        'published_at': int(news.timestamp.timestamp()) if news.timestamp else 0,
    }


def ensure_index() -> None:
    client = get_client()
    index = client.request('GET', f'/indexes/{index_uid()}', missing_ok=True)
    if index is None:
        client.wait_for_task(client.request('POST', '/indexes', json={'uid': index_uid(), 'primaryKey': PRIMARY_KEY}))
    elif index.get('primaryKey') != PRIMARY_KEY:
        client.wait_for_task(client.request('PATCH', f'/indexes/{index_uid()}', json={'primaryKey': PRIMARY_KEY}))
    client.wait_for_task(client.request('PATCH', f'/indexes/{index_uid()}/settings', json=INDEX_SETTINGS))


def add_documents(documents: list[dict]) -> None:
    client = get_client()
    client.wait_for_task(
        client.request(
            'POST',
            f'/indexes/{index_uid()}/documents',
            json=documents,
            params={'primaryKey': PRIMARY_KEY},
        )
    )


def upsert(news_ids: Iterable[int]) -> int:
    documents = [to_document(news) for news in News.objects.filter(id__in=list(news_ids))]
    if documents:
        add_documents(documents)
    return len(documents)


def remove(news_ids: Iterable[int]) -> None:
    ids = list(news_ids)
    if ids:
        client = get_client()
        client.wait_for_task(client.request('POST', f'/indexes/{index_uid()}/documents/delete-batch', json=ids))


def document_count() -> int:
    stats = get_client().request('GET', f'/indexes/{index_uid()}/stats', missing_ok=True)
    return int((stats or {}).get('numberOfDocuments', 0))


def reindex() -> dict:
    client = get_client()
    ensure_index()
    indexed = 0
    db_ids: set[int] = set()
    queryset = News.objects.order_by('id')
    for start in range(0, queryset.count(), BATCH_SIZE):
        batch = list(queryset[start:start + BATCH_SIZE])
        db_ids.update(news.id for news in batch)
        add_documents([to_document(news) for news in batch])
        indexed += len(batch)

    orphans = [doc_id for doc_id in _indexed_ids() if doc_id not in db_ids]
    for start in range(0, len(orphans), BATCH_SIZE):
        client.wait_for_task(
            client.request(
                'POST',
                f'/indexes/{index_uid()}/documents/delete-batch',
                json=orphans[start:start + BATCH_SIZE],
            )
        )
    return {'indexed': indexed, 'removed': len(orphans)}


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


def _indexed_ids() -> list[int]:
    client = get_client()
    ids: list[int] = []
    offset = 0
    while True:
        page = client.request(
            'GET',
            f'/indexes/{index_uid()}/documents',
            params={'fields': 'id', 'limit': BATCH_SIZE, 'offset': offset},
        )
        ids.extend(int(doc['id']) for doc in page['results'])
        offset += BATCH_SIZE
        if offset >= page['total']:
            return ids
