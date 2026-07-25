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
