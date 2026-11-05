from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from portal.models import Categories, Divisions, News

from .resources import main_feed_news, news_cache

NEWS_URL = '/origin/api/v1/news/'
DIVISIONS_URL = '/origin/api/v1/news/divisions'


def create_news(name, minutes_ago=0, **fields):
    return News.objects.create(
        title=name,
        summary='সংক্ষিপ্ত বিবরণ',
        source=f'https://example.com/{name}',
        timestamp=timezone.now() - timedelta(minutes=minutes_ago),
        **fields,
    )


@override_settings(ORIGIN_PATH_SECRET='origin-secret')
class SeparateFeedTests(TestCase):
    def setUp(self):
        patch('portal.tasks.search_index_news.delay').start()
        self.addCleanup(patch.stopall)
        news_cache.flush()
        self.addCleanup(news_cache.flush)

        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=User.objects.create_user("worker")).key}',
            HTTP_X_ORIGIN_SECRET='origin-secret',
        )
        self.politics = Categories.objects.create(name='Politics', enabled=True)
        self.fact_check = Categories.objects.create(name='ফ্যাক্ট চেক', enabled=True, separate_feed=True)
        self.khulna = Divisions.objects.create(name='Khulna', order=1)
        self.sylhet = Divisions.objects.create(name='Sylhet', order=2)

        self.plain = create_news('plain')
        self.politic = create_news('politics', categoryid=self.politics)
        self.checked = create_news('fact-check', categoryid=self.fact_check)
        self.local = create_news('khulna', divisionid=self.khulna)

    def ids(self, response):
        self.assertEqual(response.status_code, 200)
        return [item['id'] for item in response.json()['items']]

    def test_main_feed_keeps_division_and_separate_category_news_out(self):
        self.assertCountEqual(main_feed_news(), [self.plain, self.politic])
        self.assertCountEqual(self.ids(self.client.get(NEWS_URL)), [self.plain.id, self.politic.id])

    def test_saving_news_into_a_separate_feed_removes_it_from_the_cached_main_feed(self):
        self.client.get(NEWS_URL)
        self.politic.divisionid = self.sylhet
        self.politic.save()

        self.assertEqual(self.ids(self.client.get(NEWS_URL)), [self.plain.id])

    def test_filters_by_category_and_division_in_cache_shape(self):
        response = self.client.get(NEWS_URL, {'category': self.fact_check.id})
        self.assertEqual(self.ids(response), [self.checked.id])
        self.assertEqual(response.json()['items'][0]['category_id'], self.fact_check.id)
        self.assertEqual(self.ids(self.client.get(NEWS_URL, {'division': self.khulna.id})), [self.local.id])

    def test_rejects_non_integer_filter(self):
        self.assertEqual(self.client.get(NEWS_URL, {'division': 'x'}).status_code, 400)

    def test_divisions_returns_latest_per_division(self):
        older = create_news('khulna-older', minutes_ago=5, divisionid=self.khulna)
        create_news('khulna-oldest', minutes_ago=10, divisionid=self.khulna)
        sylhet = create_news('sylhet', minutes_ago=60, divisionid=self.sylhet)

        ids = self.ids(self.client.get(DIVISIONS_URL, {'limit': 2}))

        self.assertEqual(ids, [self.local.id, older.id, sylhet.id])
