from unittest import TestCase
from unittest.mock import patch

from portal import posthog


class FillSeriesTests(TestCase):
    def test_minute_buckets_fill_gaps_with_zero_and_end_at_now(self):
        rows = [['2026-11-15T12:58:00+02:00', 3, 1]]
        series = posthog.fill_series(rows, '2026-11-15T13:00:41.5+02:00', 'minute', 3)
        self.assertEqual([p['users'] for p in series], [3, 0, 0])
        self.assertEqual(series[-1]['t'], '2026-11-15T13:00:00+02:00')

    def test_hour_buckets_match_across_offsets(self):
        rows = [['2026-11-15T10:00:00Z', 5, 0]]
        series = posthog.fill_series(rows, '2026-11-15T13:30:00+02:00', 'hour', 3)
        self.assertEqual([p['users'] for p in series], [0, 5, 0])  # 09Z, 10Z, 11Z

    def test_day_buckets_match_on_date_across_dst(self):
        # Europe/Helsinki leaves DST on 2026-10-25, so the two midnights have different offsets.
        rows = [['2026-10-24T00:00:00+03:00', 2, 2], ['2026-10-26T00:00:00+02:00', 4, 1]]
        series = posthog.fill_series(rows, '2026-10-26T09:00:00+02:00', 'day', 3)
        self.assertEqual(series, [
            {'t': '2026-10-24', 'users': 2, 'new': 2},
            {'t': '2026-10-25', 'users': 0, 'new': 0},
            {'t': '2026-10-26', 'users': 4, 'new': 1},
        ])


class GroupLocationsTests(TestCase):
    def test_countries_sum_their_cities_and_unknown_city_skips_markers(self):
        loc = posthog.group_locations([
            ['BD', 'Bangladesh', 'Dhaka', 3, 23.7, 90.4],
            ['FI', 'Finland', 'Helsinki', 5, 60.2, 24.9],
            ['BD', 'Bangladesh', None, 4, None, None],
            [None, None, None, 1, None, None],
        ])
        self.assertEqual([(c['code'], c['users']) for c in loc['countries']], [('BD', 7), ('FI', 5), ('', 1)])
        self.assertEqual([c['name'] for c in loc['countries'][0]['cities']], ['Unknown', 'Dhaka'])
        self.assertEqual([c['name'] for c in loc['cities']], ['Helsinki', 'Dhaka'])


def fake_query(sql, ttl):
    """Canned PostHog rows, picked by a fragment unique to each query in build()."""
    canned = {
        "count(DISTINCT if(timestamp >= now()": [[12, 4, 2, '2026-11-15T13:00:00+00:00']],
        'GROUP BY t ORDER BY t': [['2026-11-15T00:00:00+00:00', 9, 4]],
        'argMax': [['FI', 'Finland', 'Helsinki', 5, 60.2, 24.9]],
        'sum(secs)': [[1200, 4, 3]],
        'UNION ALL': [['os', 'iOS', 100, 7], ['os', 'Android', 50, 5], ['app_version:iOS', '2.4', 80, 6]],
        "countIf(event = 'article saved'), countIf": [['12174', 4, 2, 1, 0]],
        "event = 'screen time'": [['Video', 6, 3, 300.0, 40.0]],
        "countIf(event = 'video watched' AND": [[20, 2, 1, 1, 1, 4, 2, 50.0, 62.5, 1]],
        'groupUniqArray': [[10, 8, 4, 5, 1, 0, 0]],
        'INTERVAL 30 DAY': [[20, 60]],
    }
    for fragment, rows in canned.items():
        if fragment in sql:
            return rows
    raise AssertionError(f'unexpected query: {sql}')


class BuildTests(TestCase):
    @patch.object(posthog, 'query', side_effect=fake_query)
    def test_build_assembles_every_section(self, query):
        d = posthog.build('7d', True, 'android')

        sqls = [c.args[0] for c in query.call_args_list]
        self.assertTrue(all(posthog.TEST_FILTER in s and posthog.PLATFORMS['android'] in s for s in sqls))
        self.assertEqual(len(d['series']), 7)
        self.assertEqual(d['series'][-1], {'t': '2026-11-15', 'users': 9, 'new': 4})
        self.assertEqual(d['totals']['online'], 2)
        self.assertEqual(d['totals']['avg_secs_per_user_day'], 400)
        self.assertEqual(d['totals']['stickiness'], 10.0)  # 60 user-days / 30 / 20 users
        self.assertEqual(d['retention'], {'cohort': 10, 'd1': 50.0, 'd7': 20.0, 'd30': None})
        self.assertEqual(d['features']['os'][0]['name'], 'iOS')
        self.assertEqual(d['screens'][0]['secs_per_user'], 100)
        self.assertEqual(d['engagement']['save_rate'], 10.0)
        self.assertEqual(d['engagement']['completion_rate'], 25.0)
        self.assertEqual(d['articles'][0]['saves'], 1)

    @patch.object(posthog, 'query', side_effect=fake_query)
    def test_filters_are_off_when_not_requested(self, query):
        posthog.build('live', False, 'all')
        self.assertFalse(any(posthog.TEST_FILTER in c.args[0] for c in query.call_args_list))
