from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from portal.models import Categories, Divisions, News, PushDigestSlot, PushNotification

from . import digest

# Tomorrow, so scheduled pushes are always in the future when the tests run.
NOW = (timezone.now() + timedelta(days=1)).replace(hour=0, minute=30, second=0, microsecond=0)  # 06:30 Bangladesh
MORNING = NOW + timedelta(minutes=30)  # 07:00 Bangladesh


def create_news(name, hours_ago=1, **fields):
    return News.objects.create(title=name, summary=f'{name} summary', source=f'https://example.com/{name}',
                               imageurl=f'https://img.example.com/{name}.jpg',
                               timestamp=NOW - timedelta(hours=hours_ago), **fields)


class DueSlotsTests(TestCase):
    """The migration creates the 7:00 and 19:00 Bangladesh slots."""

    def due(self, now):
        return [send_at for _, send_at in digest.due_slots(now)]

    def test_a_slot_is_due_in_the_half_hour_before_it_sends(self):
        self.assertEqual(self.due(NOW), [MORNING])
        self.assertEqual(self.due(NOW + timedelta(minutes=29)), [MORNING])
        self.assertEqual(self.due(NOW - timedelta(minutes=1)), [])
        self.assertEqual(self.due(MORNING), [])
        self.assertEqual(self.due(NOW + timedelta(hours=12)), [MORNING + timedelta(hours=12)])

    def test_follows_slots_edited_in_the_admin(self):
        PushDigestSlot.objects.filter(send_time=time(7)).update(enabled=False)
        PushDigestSlot.objects.create(send_time=time(0, 10))
        self.assertEqual(self.due(NOW), [])
        # 23:45 Bangladesh: the 00:10 slot of the next day.
        self.assertEqual(self.due(NOW - timedelta(minutes=405)), [NOW - timedelta(minutes=380)])


# Admin pages need a static manifest, which only exists after collectstatic.
@override_settings(STORAGES={'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class DigestSlotAdminTests(TestCase):
    def test_lists_slots_with_their_send_times(self):
        self.client.force_login(User.objects.create_superuser('admin', 'a@example.com', 'x'))
        response = self.client.get(reverse('admin:data_pushdigestslot_changelist'))
        self.assertContains(response, '07:00, 07:05')
        self.assertContains(response, '19:00, 19:05')


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

    def test_uses_the_slot_count_and_gap(self):
        PushDigestSlot.objects.filter(send_time=time(7)).update(pushes=1, gap_minutes=15)
        picks = [{'news_id': self.prices.id, 'title': 'দাম', 'body': 'দাম বাড়ল'},
                 {'news_id': self.exam.id, 'title': 'ফল', 'body': 'ফল প্রকাশ'}]
        scheduled, ai = self.schedule(picks)

        self.assertEqual([(p.news_id, p.scheduled_at) for p in scheduled], [(self.prices.id, MORNING)])
        self.assertIn('choose exactly 1 ', ai.call_args.kwargs['system_prompt'])

    def test_runs_once_per_slot(self):
        picks = [{'news_id': self.prices.id, 'title': 'দাম', 'body': 'দাম বাড়ল'}]
        self.schedule(picks)
        scheduled, ai = self.schedule(picks)

        self.assertEqual(scheduled, [])
        ai.assert_not_called()

    def test_skips_a_slot_scheduled_before_the_key_format_changed(self):
        PushNotification.objects.create(news=self.prices, title='t', body='b', scheduled_at=MORNING,
                                        status=PushNotification.Status.SCHEDULED, origin=PushNotification.Origin.DIGEST,
                                        idempotency_key=f'digest-{MORNING.astimezone(digest.BANGLADESH):%Y%m%d%H}-0')
        scheduled, ai = self.schedule([])

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
