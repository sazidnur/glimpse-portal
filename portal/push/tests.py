from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from portal.models import News, PushDevice, PushNotification

from . import apns, fcm, service
from .apns import APNsResult
from .fcm import FCMResult
from .message import PushMessage

DEVICE = {
    'token': 'a' * 64,
    'platform': 'ios',
    'provider': 'apns',
    'environment': 'sandbox',
    'enabled': True,
    'topics': ['breaking_news', 'unknown'],
    'locale': 'bn',
    'app_version': '1.4',
}


def api_client(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=user).key}')
    return client


DEVICES_URL = '/origin/api/v1/devices'


@override_settings(ORIGIN_PATH_SECRET='origin-secret')
class DeviceRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = api_client(User.objects.create_user('worker'))

    def register(self, **overrides):
        return self.client.post(DEVICES_URL, {**DEVICE, **overrides}, format='json', HTTP_X_ORIGIN_SECRET='origin-secret')

    def test_upserts_by_token_and_drops_unknown_topics(self):
        self.assertEqual(self.register().status_code, 204)
        self.assertEqual(self.register(enabled=False, locale='en').status_code, 204)

        device = PushDevice.objects.get()
        self.assertFalse(device.enabled)
        self.assertEqual(device.locale, 'en')
        self.assertEqual(device.topics, ['breaking_news'])

    def test_accepts_null_previous_token_and_normalizes_locale(self):
        self.assertEqual(self.register(previous_token=None, locale='en-US').status_code, 204)

        self.assertEqual(PushDevice.objects.get().locale, 'en')

    def test_rotated_token_replaces_previous_row(self):
        self.register()
        self.register(token='b' * 64, previous_token='a' * 64)

        self.assertEqual(list(PushDevice.objects.values_list('token', flat=True)), ['b' * 64])

    def test_reregistration_revives_invalidated_device(self):
        self.register()
        PushDevice.objects.update(invalidated_at=timezone.now(), last_error='Unregistered')
        self.register()

        device = PushDevice.objects.get()
        self.assertIsNone(device.invalidated_at)
        self.assertEqual(device.last_error, '')

    def test_rejects_provider_mismatch_and_android_sandbox(self):
        self.assertEqual(self.register(provider='fcm').status_code, 400)
        self.assertEqual(
            self.register(platform='android', provider='fcm', environment='sandbox').status_code,
            400,
        )

    def test_requires_authentication(self):
        response = APIClient().post(DEVICES_URL, DEVICE, format='json', HTTP_X_ORIGIN_SECRET='origin-secret')
        self.assertEqual(response.status_code, 401)


class PushApiTests(TestCase):
    def setUp(self):
        self.client = api_client(User.objects.create_superuser('admin', password='x'))
        self.news = News.objects.create(
            title='শিরোনাম',
            summary='সংক্ষিপ্ত বিবরণ ' * 30,
            source='https://example.com/story',
            imageurl='https://cdn.example.com/cover.jpg',
            timestamp=timezone.now(),
        )
        self.delay = patch('portal.tasks.push_deliver.delay').start()
        self.addCleanup(patch.stopall)

    def create(self, payload):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post('/portal/api/push/', payload, format='json')

    def test_custom_push_is_queued_for_both_platforms(self):
        response = self.create({'title': 'Hello', 'body': 'World'})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'queued')
        self.assertEqual(response.data['target'], 'all')
        self.assertEqual(response.data['origin'], 'api')
        self.delay.assert_called_once_with(response.data['id'])

    def test_news_push_fills_content_from_story(self):
        response = self.create({'news_id': self.news.id, 'target': 'android'})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['source'], 'news')
        self.assertEqual(response.data['title'], self.news.title)
        self.assertLessEqual(len(response.data['body']), 180)
        self.assertEqual(response.data['image_url'], self.news.imageurl)

    def test_validation_errors(self):
        self.assertIn('title', self.create({'body': 'x'}).data)
        self.assertIn('news', self.create({'source': 'news'}).data)
        self.assertIn('image_url', self.create({'title': 't', 'body': 'b', 'image_url': 'http://x.com/a.jpg'}).data)
        past = (timezone.now() - timedelta(minutes=1)).isoformat()
        self.assertIn('scheduled_at', self.create({'title': 't', 'body': 'b', 'scheduled_at': past}).data)

    def test_idempotency_key_returns_existing_notification(self):
        first = self.create({'title': 't', 'body': 'b', 'idempotency_key': 'story-1'})
        second = self.create({'title': 't', 'body': 'b', 'idempotency_key': 'story-1'})

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(self.delay.call_count, 1)

    def test_scheduled_push_is_released_when_due_and_can_be_cancelled(self):
        send_at = timezone.now() + timedelta(hours=1)
        scheduled = self.create({'title': 't', 'body': 'b', 'scheduled_at': send_at.isoformat()})
        other = self.create({'title': 't2', 'body': 'b2', 'scheduled_at': send_at.isoformat()})
        self.assertEqual(scheduled.data['status'], 'scheduled')
        self.delay.assert_not_called()

        cancelled = self.client.post(f"/portal/api/push/{other.data['id']}/cancel/")
        self.assertEqual(cancelled.data['status'], 'cancelled')

        with patch('portal.push.service.timezone.now', return_value=send_at + timedelta(seconds=1)):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(service.release_due(), 1)
        self.delay.assert_called_once_with(scheduled.data['id'])

    def test_requires_push_permission(self):
        user = User.objects.create_user('editor')
        client = api_client(user)
        self.assertEqual(client.post('/portal/api/push/', {'title': 't', 'body': 'b'}, format='json').status_code, 403)

        user.user_permissions.add(Permission.objects.get(codename='add_pushnotification'))
        with self.captureOnCommitCallbacks(execute=True):
            response = client.post('/portal/api/push/', {'title': 't', 'body': 'b'}, format='json')
        self.assertEqual(response.status_code, 201)


class DeliveryTests(TestCase):
    def setUp(self):
        self.good = PushDevice.objects.create(token='good', platform='ios', provider='apns', topics=['breaking_news'])
        self.dead = PushDevice.objects.create(
            token='dead', platform='ios', provider='apns', environment='sandbox', topics=['breaking_news'],
        )
        PushDevice.objects.create(token='off', platform='ios', provider='apns', enabled=False, topics=['breaking_news'])
        PushDevice.objects.create(token='android', platform='android', provider='fcm', topics=['breaking_news'])
        self.fcm_client = patch('portal.push.service.fcm.FCMClient').start().return_value.__enter__.return_value
        self.apns_client = patch('portal.push.service.APNsClient').start().return_value
        self.addCleanup(patch.stopall)

    def notification(self, **fields):
        return PushNotification.objects.create(title='Title', body='Body', source='custom', **fields)

    def test_broadcast_uses_fcm_topic_and_ios_tokens(self):
        self.fcm_client.send.return_value = FCMResult(ok=True, message_id='projects/p/messages/1')
        self.apns_client.send.return_value = [
            APNsResult(token='good', ok=True),
            APNsResult(token='dead', ok=False, reason='Unregistered', invalid=True),
        ]
        notification = self.notification()

        service.deliver(notification.id)

        message = self.fcm_client.send.call_args.args[0]
        self.assertEqual(message['topic'], 'breaking_news')
        self.assertNotIn('token', message)
        audience = self.apns_client.send.call_args.args[0]
        self.assertEqual(audience, {'production': ['good'], 'sandbox': ['dead']})

        notification.refresh_from_db()
        self.assertEqual(notification.status, PushNotification.Status.PARTIAL)
        self.assertEqual((notification.ios_sent, notification.ios_failed, notification.ios_invalidated), (1, 1, 1))
        self.assertEqual(notification.ios_error, 'Unregistered ×1')
        self.dead.refresh_from_db()
        self.assertIsNotNone(self.dead.invalidated_at)
        self.assertEqual(self.dead.last_error, 'Unregistered')

    def test_android_only_success(self):
        self.fcm_client.send.return_value = FCMResult(ok=True, message_id='m1')
        notification = self.notification(target='android')

        service.deliver(notification.id)

        notification.refresh_from_db()
        self.assertEqual(notification.status, PushNotification.Status.SENT)
        self.apns_client.send.assert_not_called()

    def test_fcm_failure_marks_failed(self):
        self.fcm_client.send.return_value = FCMResult(ok=False, error='HTTP 401 UNAUTHENTICATED')
        notification = self.notification(target='android')

        service.deliver(notification.id)

        notification.refresh_from_db()
        self.assertEqual(notification.status, PushNotification.Status.FAILED)
        self.assertEqual(notification.fcm_error, 'HTTP 401 UNAUTHENTICATED')

    def test_ios_only_push_without_devices_fails(self):
        PushDevice.objects.filter(platform='ios').update(enabled=False)
        notification = self.notification(target='ios')

        service.deliver(notification.id)

        notification.refresh_from_db()
        self.assertEqual(notification.status, PushNotification.Status.FAILED)
        self.assertEqual(notification.ios_error, 'No active iOS devices')
        self.apns_client.send.assert_not_called()

    def test_only_queued_notifications_are_delivered(self):
        notification = self.notification(status=PushNotification.Status.CANCELLED)

        service.deliver(notification.id)

        self.fcm_client.send.assert_not_called()
        notification.refresh_from_db()
        self.assertEqual(notification.status, PushNotification.Status.CANCELLED)


class PayloadTests(TestCase):
    def test_fcm_message_uses_string_data_and_channel(self):
        message = PushMessage(title='T', body='B', collapse_id='news_7', news_id=7, image_url='https://x/i.jpg')

        payload = fcm.build_message(message, topic='breaking_news')

        self.assertEqual(payload['data'], {'news_id': '7', 'image': 'https://x/i.jpg'})
        self.assertEqual(payload['notification']['image'], 'https://x/i.jpg')
        self.assertEqual(payload['android']['notification']['channel_id'], 'breaking_news')
        self.assertEqual(payload['android']['collapse_key'], 'news_7')

    def test_apns_mutable_content_only_with_image(self):
        plain = apns.build_payload(PushMessage(title='T', body='B', collapse_id='push_1'))
        rich = apns.build_payload(PushMessage(title='T', body='B', collapse_id='push_1', image_url='https://x/i.jpg'))

        self.assertNotIn('mutable-content', plain['aps'])
        self.assertNotIn('news_id', plain)
        self.assertEqual(rich['aps']['mutable-content'], 1)
        self.assertEqual(rich['image'], 'https://x/i.jpg')
