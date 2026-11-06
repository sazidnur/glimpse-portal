from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from portal.models import Categories, Divisions, News, PushNotification

from . import digest

# Tomorrow, so scheduled pushes are always in the future when the tests run.
NOW = (timezone.now() + timedelta(days=1)).replace(hour=0, minute=30, second=0, microsecond=0)  # 06:30 Bangladesh
MORNING = NOW + timedelta(minutes=30)  # 07:00 Bangladesh


def create_news(name, hours_ago=1, **fields):
    return News.objects.create(title=name, summary=f'{name} summary', source=f'https://example.com/{name}',
                               imageurl=f'https://img.example.com/{name}.jpg',
                               timestamp=NOW - timedelta(hours=hours_ago), **fields)


class NextSendTimeTests(TestCase):
    def test_runs_half_an_hour_before_7_and_19_bangladesh_time(self):
        self.assertEqual(digest.next_send_time(NOW), MORNING)
        self.assertEqual(digest.next_send_time(NOW.replace(hour=12)), MORNING.replace(hour=13))
        self.assertEqual(digest.next_send_time(NOW.replace(hour=14)), MORNING + timedelta(days=1))


class ScheduleDigestTests(TestCase):
    def setUp(self):
        patch('portal.tasks.search_index_news.delay').start()
        patch('portal.push.service._enqueue').start()
        self.addCleanup(patch.stopall)
        fact_check = Categories.objects.create(name='ফ্যাক্ট চেক', enabled=False, separate_feed=True)
        self.prices = create_news('prices')
        self.exam = create_news('exam')
        create_news('old', hours_ago=13)
        create_news('division', divisionid=Divisions.objects.create(name='Khulna', order=6))
        create_news('factcheck', categoryid=fact_check)
        pushed = create_news('pushed')
        PushNotification.objects.create(news=pushed, title='t', body='b', status=PushNotification.Status.SENT)

    def schedule(self, picks, **kwargs):
        with patch('portal.push.digest.run_realtime_translation', return_value=({'picks': picks}, 'id', {}), **kwargs) as ai:
            return digest.schedule_digest(now=NOW), ai

    def test_schedules_two_ai_picks_five_minutes_apart_from_fresh_main_feed_news(self):
        picks = [{'news_id': self.prices.id, 'title': 'দাম', 'body': 'দাম বাড়ল'},
                 {'news_id': self.exam.id, 'title': 'ফল', 'body': 'ফল প্রকাশ'}]
        scheduled, ai = self.schedule(picks)

        offered = {story['id'] for story in ai.call_args.kwargs['user_payload']['stories']}
        self.assertEqual(offered, {self.prices.id, self.exam.id})
        self.assertTrue(ai.call_args.kwargs['flex'])
        self.assertEqual([(p.news_id, p.title, p.scheduled_at, p.status, p.origin) for p in scheduled], [
            (self.prices.id, 'দাম', MORNING, PushNotification.Status.SCHEDULED, PushNotification.Origin.DIGEST),
            (self.exam.id, 'ফল', MORNING + timedelta(minutes=5), PushNotification.Status.SCHEDULED, PushNotification.Origin.DIGEST),
        ])
        self.assertEqual(scheduled[0].image_url, 'https://img.example.com/prices.jpg')

    def test_runs_once_per_slot(self):
        picks = [{'news_id': self.prices.id, 'title': 'দাম', 'body': 'দাম বাড়ল'}]
        self.schedule(picks)
        scheduled, ai = self.schedule(picks)

        self.assertEqual(scheduled, [])
        ai.assert_not_called()

    def test_ignores_duplicate_and_empty_picks(self):
        picks = [{'news_id': self.prices.id, 'title': 'দাম', 'body': 'দাম বাড়ল'},
                 {'news_id': self.prices.id, 'title': 'আবার', 'body': 'আবার'},
                 {'news_id': self.exam.id, 'title': ' ', 'body': 'ফাঁকা শিরোনাম'}]
        scheduled, _ = self.schedule(picks)

        self.assertEqual([p.news_id for p in scheduled], [self.prices.id])

    def test_falls_back_to_standard_priority_when_flex_fails(self):
        result = ({'picks': [{'news_id': self.prices.id, 'title': 'দাম', 'body': 'দাম বাড়ল'}]}, 'id', {})
        with patch('portal.push.digest.run_realtime_translation', side_effect=[RuntimeError('flex busy'), result]) as ai:
            scheduled = digest.schedule_digest(now=NOW)

        self.assertEqual(len(scheduled), 1)
        self.assertNotIn('flex', ai.call_args.kwargs)
