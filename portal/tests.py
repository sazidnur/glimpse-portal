from unittest import TestCase
from unittest.mock import patch

from portal.live_feed.pipelines.aljazeera_live import AlJazeeraLiveClient


class AlJazeeraLiveDiscoveryTests(TestCase):
    def setUp(self):
        self.client = AlJazeeraLiveClient()

    def _discover(self, ticker_link, homepage_links, post_id):
        payload = {
            'data': {
                'breakingNews': {
                    'link': ticker_link,
                    'post': post_id,
                },
            },
        }
        with (
            patch.object(self.client, 'graphql_get', return_value=payload),
            patch.object(
                self.client,
                'fetch_homepage_live_links',
                return_value=homepage_links,
            ),
        ):
            return self.client.discover_latest_live_target()

    def test_newer_homepage_liveblog_wins_over_stale_ticker(self):
        target = self._discover(
            'https://www.aljazeera.com/news/liveblog/2026/7/24/yesterday',
            ['https://www.aljazeera.com/news/liveblog/2026/7/25/today'],
            123,
        )

        self.assertEqual(target.slug, 'today')
        self.assertIsNone(target.post_id)

    def test_newer_ticker_liveblog_wins_over_stale_homepage(self):
        target = self._discover(
            'https://www.aljazeera.com/news/liveblog/2026/7/25/today',
            ['https://www.aljazeera.com/news/liveblog/2026/7/24/yesterday'],
            456,
        )

        self.assertEqual(target.slug, 'today')
        self.assertEqual(target.post_id, 456)


class LiveItemTimestampTests(TestCase):
    def test_zoneless_source_date_becomes_utc_iso(self):
        from portal.live_feed.service import iso_utc

        self.assertEqual(iso_utc('2026-11-08T03:57:12'), '2026-11-08T03:57:12+00:00')
        self.assertEqual(iso_utc('2026-11-08T09:57:12+06:00'), '2026-11-08T09:57:12+06:00')
        self.assertTrue(iso_utc('').endswith('+00:00'))
        self.assertTrue(iso_utc('not a date').endswith('+00:00'))
