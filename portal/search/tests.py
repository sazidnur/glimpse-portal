from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from portal.models import News, SearchReindexJob

from . import news_index, reindex
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


class ReindexJobTests(TestCase):
    def setUp(self):
        self.delay = patch('portal.tasks.search_reindex_job.delay').start()
        self.delay.return_value.id = 'task-1'
        self.addCleanup(patch.stopall)

    def test_only_one_active_job_at_a_time(self):
        with self.captureOnCommitCallbacks(execute=True):
            job = reindex.start()
        self.delay.assert_called_once_with(job.id)
        job.refresh_from_db()
        self.assertEqual(job.celery_task_id, 'task-1')

        with self.assertRaises(reindex.ReindexAlreadyRunning) as raised:
            reindex.start()
        self.assertEqual(raised.exception.job, job)

    def test_cancel_queued_job_releases_the_lock(self):
        job = reindex.start()
        with patch.object(reindex, '_revoke') as revoke:
            reindex.cancel(job)
        revoke.assert_called_once()
        job.refresh_from_db()
        self.assertEqual((job.status, job.is_active), (SearchReindexJob.Status.CANCELLED, False))
        self.assertIsNotNone(reindex.start())

    def test_cancel_running_job_stops_then_force_cancel_unlocks(self):
        job = reindex.start()
        SearchReindexJob.objects.filter(id=job.id).update(status=SearchReindexJob.Status.RUNNING)
        job.refresh_from_db()

        reindex.cancel(job)
        job.refresh_from_db()
        self.assertEqual((job.status, job.is_active), (SearchReindexJob.Status.CANCELLING, True))
        with self.assertRaises(reindex.ReindexAlreadyRunning):
            reindex.start()

        with patch.object(reindex, '_discard') as discard, patch.object(reindex, '_revoke'):
            reindex.cancel(job)
        discard.assert_called_once_with(job.id)
        job.refresh_from_db()
        self.assertEqual((job.status, job.is_active), (SearchReindexJob.Status.CANCELLED, False))

    def test_failed_rebuild_is_recorded_and_unlocks(self):
        job = reindex.create_job(reindex.Trigger.MANUAL)
        with patch.object(news_index, 'rebuild', side_effect=MeiliError('boom')), \
                patch.object(reindex, '_discard') as discard:
            reindex.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, SearchReindexJob.Status.FAILED)
        self.assertIn('boom', job.error)
        self.assertFalse(job.is_active)
        discard.assert_called_once_with(job.id)

    def test_nightly_skips_while_another_job_is_active(self):
        from portal.tasks import search_reindex

        reindex.create_job(reindex.Trigger.MANUAL)
        self.assertIn('skipped', search_reindex())


class ReindexAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser('admin', password='x'))
        self.delay = patch('portal.tasks.search_reindex_job.delay').start()
        self.delay.return_value.id = 'task-1'
        self.addCleanup(patch.stopall)

    def test_start_button_queues_once_and_page_shows_status(self):
        url = '/portal/data/searchreindexjob/start_reindex/'
        with self.captureOnCommitCallbacks(execute=True):
            self.client.get(url)
            self.client.get(url)
        self.assertEqual(SearchReindexJob.objects.count(), 1)
        self.delay.assert_called_once()

        page = self.client.get('/portal/data/searchreindexjob/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'refreshes every 3 seconds')


@skipUnless(get_client().is_healthy(), 'Meilisearch is not reachable')
@override_settings(MEILI_NEWS_INDEX='news_test')
class MeilisearchIntegrationTests(TestCase):
    def setUp(self):
        patch('portal.tasks.search_index_news.delay').start()
        patch('portal.tasks.search_remove_news.delay').start()
        self.addCleanup(patch.stopall)
        get_client().request('DELETE', '/indexes/news_test', missing_ok=True)
        self.addCleanup(get_client().request, 'DELETE', '/indexes/news_test', missing_ok=True)

    def rebuild(self):
        job = reindex.create_job(reindex.Trigger.MANUAL)
        reindex.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, SearchReindexJob.Status.SUCCEEDED, job.error)
        return job

    def test_rebuild_searches_title_and_summary_only_newest_first(self):
        older = create_news('জ্বালানি তেলের দাম বাড়ল', minutes_ago=60)
        newer = create_news('বাজার পরিস্থিতি', summary='জ্বালানি সংকটে পরিবহন খরচ বাড়ছে', minutes_ago=5)
        create_news('খেলার খবর', minutes_ago=1)
        hidden = News.objects.create(
            title='অন্য', summary='অন্য', source='https://example.com/জ্বালানি', timestamp=timezone.now(),
        )

        job = self.rebuild()
        self.assertEqual((job.indexed, job.total, job.removed), (4, 4, 0))
        result = news_index.search('জ্বালানি', page=1, limit=10)

        ids = [item['id'] for item in result['items']]
        self.assertEqual(set(ids), {older.id, newer.id})
        self.assertNotIn(hidden.id, ids)
        self.assertNotIn('published_at', result['items'][0])

        typo = news_index.search('জ্বালনি', page=1, limit=10)
        self.assertIn(older.id, [item['id'] for item in typo['items']])

    def test_rebuild_keeps_serving_old_index_then_swaps_and_cleans_up(self):
        keep = create_news('রাখা খবর')
        gone = create_news('মুছে ফেলা খবর')
        first = self.rebuild()
        gone.delete()

        searched_during_rebuild = []
        original = news_index.add_documents

        def add_and_search(documents, uid=None):
            original(documents, uid)
            searched_during_rebuild.append(news_index.search('খবর', page=1, limit=10)['total'])

        with patch.object(news_index, 'add_documents', side_effect=add_and_search):
            second = self.rebuild()

        self.assertEqual(searched_during_rebuild, [2])
        self.assertEqual((second.indexed, second.removed), (1, 0))
        self.assertEqual([item['id'] for item in news_index.search('খবর', page=1, limit=10)['items']], [keep.id])
        indexes = [i['uid'] for i in get_client().request('GET', '/indexes', params={'limit': 100})['results']]
        self.assertNotIn(news_index.rebuild_index_uid(first.id), indexes)
        self.assertNotIn(news_index.rebuild_index_uid(second.id), indexes)

    def test_writes_reach_both_indexes_while_rebuilding(self):
        job = reindex.create_job(reindex.Trigger.MANUAL)
        SearchReindexJob.objects.filter(id=job.id).update(status=SearchReindexJob.Status.RUNNING)
        news_index.ensure_index(news_index.rebuild_index_uid(job.id))
        self.addCleanup(news_index.discard_rebuild, job.id)
        news = create_news('চলমান খবর')

        news_index.upsert([news.id])

        self.assertEqual(news_index.document_count(), 1)
        self.assertEqual(news_index.document_count(news_index.rebuild_index_uid(job.id)), 1)

    def test_cancelled_rebuild_leaves_live_index_untouched(self):
        create_news('প্রথম খবর')
        self.rebuild()
        create_news('দ্বিতীয় খবর')
        job = reindex.create_job(reindex.Trigger.MANUAL)

        def cancel_midway(documents, uid=None):
            SearchReindexJob.objects.filter(id=job.id).update(status=SearchReindexJob.Status.CANCELLING)

        with patch.object(news_index, 'add_documents', side_effect=cancel_midway):
            reindex.run(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, SearchReindexJob.Status.CANCELLED)
        self.assertEqual(news_index.document_count(), 1)

    def test_upsert_works_before_index_exists_and_reports_failures(self):
        news = create_news('পুলিশ সদর দপ্তর')

        self.assertEqual(news_index.upsert([news.id]), 1)
        self.assertEqual(news_index.document_count(), 1)
        self.assertEqual(get_client().request('GET', '/indexes/news_test')['primaryKey'], 'id')

        with patch.object(news_index, 'PRIMARY_KEY', 'title'):
            with self.assertRaises(MeiliError):
                news_index.upsert([news.id])
