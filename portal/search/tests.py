from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from portal.models import News

from . import news_index
from .client import MeiliError, get_client

SEARCH_URL = '/origin/api/v1/news/search'


def create_news(title, summary='সংক্ষিপ্ত বিবরণ', minutes_ago=0, **fields):
    return News.objects.create(
        title=title,
        summary=summary,
        source=f'https://example.com/{title}-{minutes_ago}',
        timestamp=timezone.now() - timedelta(minutes=minutes_ago),
        **fields,
    )


class DocumentTests(TestCase):
    def test_document_matches_news_api_shape_plus_sort_key(self):
        news = create_news('শিরোনাম', imageurl='https://cdn.example.com/a.jpg')

        document = news_index.to_document(news)

        self.assertEqual(
            set(document),
            set(news_index.DISPLAYED_FIELDS) | {'published_at'},
        )
        self.assertEqual(document['published_at'], int(news.timestamp.timestamp()))
        self.assertNotIn('published_at', news_index.DISPLAYED_FIELDS)
        self.assertEqual(news_index.INDEX_SETTINGS['searchableAttributes'], ['title', 'summary'])


class SignalTests(TestCase):
    def setUp(self):
        self.index = patch('portal.tasks.search_index_news.delay').start()
        self.remove = patch('portal.tasks.search_remove_news.delay').start()
        self.addCleanup(patch.stopall)

    def test_create_update_and_delete_are_synced_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            news = create_news('প্রথম')
        self.index.assert_called_once_with([news.id])

        with self.captureOnCommitCallbacks(execute=True):
            news.title = 'হালনাগাদ'
            news.save()
        self.assertEqual(self.index.call_count, 2)

        news_id = news.id
        with self.captureOnCommitCallbacks(execute=True):
            news.delete()
        self.remove.assert_called_once_with([news_id])

    def test_queryset_delete_syncs_every_story(self):
        with self.captureOnCommitCallbacks(execute=True):
            ids = [create_news(f'খবর {i}', minutes_ago=i).id for i in range(3)]
        with self.captureOnCommitCallbacks(execute=True):
            News.objects.filter(id__in=ids).delete()

        removed = sorted(call.args[0][0] for call in self.remove.call_args_list)
        self.assertEqual(removed, sorted(ids))


@override_settings(ORIGIN_PATH_SECRET='origin-secret')
class SearchViewTests(TestCase):
    def setUp(self):
        user = User.objects.create_user('worker')
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=user).key}',
            HTTP_X_ORIGIN_SECRET='origin-secret',
        )
        patch('portal.tasks.search_index_news.delay').start()
        self.addCleanup(patch.stopall)

    def get(self, **params):
        return self.client.get(SEARCH_URL, params)

    def test_rejects_short_query(self):
        self.assertEqual(self.get(q=' ক ').status_code, 400)

    def test_requires_authentication(self):
        response = APIClient().get(SEARCH_URL, {'q': 'খবর'}, HTTP_X_ORIGIN_SECRET='origin-secret')
        self.assertEqual(response.status_code, 401)

    def test_returns_paginated_shape_from_meilisearch(self):
        hits = {'hits': [{'id': 1, 'title': 'পুলিশ'}], 'totalHits': 41, 'page': 2, 'totalPages': 3}
        with patch.object(news_index, 'get_client') as client:
            client.return_value.request.return_value = hits
            response = self.get(q='  পুলিশ   সদর ', page=2, limit=20)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'items': hits['hits'], 'total': 41, 'page': 2, 'limit': 20, 'pages': 3})
        body = client.return_value.request.call_args.kwargs['json']
        self.assertEqual(body['q'], 'পুলিশ সদর')
        self.assertEqual(body['hitsPerPage'], 20)
        self.assertEqual(response['Cache-Control'], 's-maxage=120')
        self.assertEqual(response['X-SR'], '1')

    def test_limit_is_capped(self):
        with patch.object(news_index, 'search_with_fallback', return_value=({}, '1')) as search:
            self.get(q='খবর', limit=500, page=999)
        self.assertEqual(search.call_args.kwargs, {'page': 50, 'limit': 50})

    def test_falls_back_to_database_when_meilisearch_is_down(self):
        create_news('পুলিশ সদর দপ্তরে বৈঠক', minutes_ago=5)
        newest = create_news('নতুন খবর', summary='পুলিশ জানিয়েছে', minutes_ago=1)
        create_news('অন্য খবর', summary='অর্থনীতি')

        with patch.object(news_index, 'search', side_effect=MeiliError('down')):
            response = self.get(q='পুলিশ')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-SR'], '2')
        self.assertEqual(response.data['total'], 2)
        self.assertEqual(response.data['items'][0]['id'], newest.id)
        self.assertEqual(set(response.data['items'][0]), set(news_index.DISPLAYED_FIELDS))


@skipUnless(get_client().is_healthy(), 'Meilisearch is not reachable')
@override_settings(MEILI_NEWS_INDEX='news_test')
class MeilisearchIntegrationTests(TestCase):
    def setUp(self):
        patch('portal.tasks.search_index_news.delay').start()
        patch('portal.tasks.search_remove_news.delay').start()
        self.addCleanup(patch.stopall)
        get_client().request('DELETE', '/indexes/news_test', missing_ok=True)
        self.addCleanup(get_client().request, 'DELETE', '/indexes/news_test', missing_ok=True)

    def test_reindex_searches_title_and_summary_only_newest_first(self):
        older = create_news('জ্বালানি তেলের দাম বাড়ল', minutes_ago=60)
        newer = create_news('বাজার পরিস্থিতি', summary='জ্বালানি সংকটে পরিবহন খরচ বাড়ছে', minutes_ago=5)
        create_news('খেলার খবর', minutes_ago=1)
        hidden = News.objects.create(
            title='অন্য', summary='অন্য', source='https://example.com/জ্বালানি', timestamp=timezone.now(),
        )

        self.assertEqual(news_index.reindex(), {'indexed': 4, 'removed': 0})
        result = news_index.search('জ্বালানি', page=1, limit=10)

        ids = [item['id'] for item in result['items']]
        self.assertEqual(set(ids), {older.id, newer.id})
        self.assertNotIn(hidden.id, ids)
        self.assertNotIn('published_at', result['items'][0])

        typo = news_index.search('জ্বালনি', page=1, limit=10)
        self.assertIn(older.id, [item['id'] for item in typo['items']])

    def test_reindex_removes_deleted_stories(self):
        keep = create_news('রাখা খবর')
        gone = create_news('মুছে ফেলা খবর')
        news_index.reindex()
        gone.delete()

        self.assertEqual(news_index.reindex(), {'indexed': 1, 'removed': 1})
        self.assertEqual(news_index.document_count(), 1)
        self.assertEqual(news_index.search('খবর', page=1, limit=10)['items'][0]['id'], keep.id)

    def test_upsert_works_before_index_exists_and_reports_failures(self):
        news = create_news('পুলিশ সদর দপ্তর')

        self.assertEqual(news_index.upsert([news.id]), 1)
        self.assertEqual(news_index.document_count(), 1)
        self.assertEqual(get_client().request('GET', '/indexes/news_test')['primaryKey'], 'id')

        with patch.object(news_index, 'PRIMARY_KEY', 'title'):
            with self.assertRaises(MeiliError):
                news_index.upsert([news.id])
