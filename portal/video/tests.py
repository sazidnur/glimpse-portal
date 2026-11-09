import base64
import shutil
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import httpx

from django.contrib.auth.models import Permission, User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.v1.serializers import NewsDetailSerializer
from portal.models import Categories, News, NewsArticle, NewsVideo, PushNotification, Sourcealias, VideoSeries
from portal.push.digest import BANGLADESH
from portal.tasks import video_draft

from . import pipeline, social, voice

Status = NewsVideo.Status


def create_news(name, hours_ago=1, source=None, **fields):
    return News.objects.create(title=f'{name} title', summary=f'{name} summary',
                               source=source or f'https://www.prothomalo.com/{name}',
                               imageurl=f'https://img.example.com/{name}.jpg',
                               timestamp=timezone.now() - timedelta(hours=hours_ago), **fields)


def create_series(**fields):
    defaults = dict(name='Test series', enabled=True, template='Test', publish_times='20:00', lead_minutes=120,
                    story_count=2, pick_prompt='pick', script_prompt='write', review_prompt='review', voice_id='voice')
    return VideoSeries.objects.create(**{**defaults, **fields})


def script(*news_ids):
    return {'title': 'শিরোনাম', 'description': 'বিবরণ', 'scenes': [
        {'narration': 'প্রথম দৃশ্য।', 'caption': 'এক', 'news_ids': list(news_ids[:1])},
        {'narration': 'দ্বিতীয় দৃশ্য।', 'caption': 'দুই', 'news_ids': list(news_ids)},
    ]}


class MediaTestCase(TestCase):
    def setUp(self):
        patch('portal.tasks.search_index_news.delay').start()
        patch('portal.tasks.search_remove_news.delay').start()
        self.addCleanup(patch.stopall)
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media, SITE_URL='https://glimpseapp.net')
        override.enable()
        self.addCleanup(override.disable)


class ScheduleTests(MediaTestCase):
    def at(self, hour, minute, day=10):
        return datetime(2026, 11, day, hour, minute, tzinfo=BANGLADESH)

    def test_a_video_starts_once_when_its_lead_time_opens(self):
        series = create_series()
        self.assertEqual(pipeline.schedule(self.at(17, 59)), [])
        [video] = pipeline.schedule(self.at(18, 0))
        self.assertEqual(video.publish_at, self.at(20, 0))
        self.assertEqual(pipeline.schedule(self.at(18, 5)), [])
        self.assertEqual(video.series, series)

    def test_only_on_the_chosen_weekdays(self):
        create_series(weekdays=[1])  # 2026-11-10 is a Tuesday
        self.assertEqual(len(pipeline.schedule(self.at(19, 0, day=10))), 1)
        self.assertEqual(pipeline.schedule(self.at(19, 0, day=11)), [])

    def test_disabled_series_never_start(self):
        create_series(enabled=False)
        self.assertEqual(pipeline.schedule(self.at(19, 0)), [])


class DraftTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        Sourcealias.objects.create(source='prothomalo', alias='প্রথম আলো', alias_en='Prothom Alo')
        Sourcealias.objects.create(source='tbsnews', alias='দ্য বিজনেস স্ট্যান্ডার্ড', alias_en='TBS')
        self.fuel = create_news('fuel')
        self.fuel_tbs = create_news('fuel-tbs', source='https://www.tbsnews.net/fuel')
        self.exam = create_news('exam')
        create_news('old', hours_ago=30)
        NewsArticle.objects.create(news=self.fuel, text='পুরো খবর')
        PushNotification.objects.create(news=self.fuel, title='t', body='b', status=PushNotification.Status.SENT)

    def draft(self, series, picks, issues=(), script_ids=None, edited=None):
        written = script(*(script_ids or [picks[0]['news_id']]))
        answers = [{'stories': picks}, written, {'issues': list(issues), 'script': edited or written}]
        video = NewsVideo.objects.create(series=series, publish_at=timezone.now() + timedelta(hours=1))
        with patch('portal.video.pipeline.run_realtime_translation',
                   side_effect=[(answer, 'id', {}) for answer in answers]) as ai:
            pipeline.draft(video)
        video.refresh_from_db()
        return video, ai

    def test_picks_stories_with_their_coverage_and_waits_for_an_editor(self):
        video, ai = self.draft(create_series(), [{'news_id': self.fuel.id, 'related_ids': [self.fuel_tbs.id]}],
                               script_ids=[self.fuel.id, self.fuel_tbs.id])
        self.assertEqual(video.status, Status.REVIEW)
        self.assertEqual(set(video.news.values_list('id', flat=True)), {self.fuel.id, self.fuel_tbs.id})

        articles = {a['id']: a for a in ai.call_args_list[0].kwargs['user_payload']['articles']}
        self.assertNotIn('old title', [a['title'] for a in articles.values()])
        self.assertTrue(articles[self.fuel.id]['pushed'])
        self.assertEqual(articles[self.fuel_tbs.id]['source'], 'দ্য বিজনেস স্ট্যান্ডার্ড')

        [story] = ai.call_args_list[1].kwargs['user_payload']['stories']
        self.assertEqual((story['source'], story['article']), ('প্রথম আলো', 'পুরো খবর'))
        self.assertEqual(story['related'][0]['id'], self.fuel_tbs.id)

    def test_used_stories_are_not_picked_again_by_the_same_series(self):
        series = create_series()
        first, _ = self.draft(series, [{'news_id': self.fuel.id, 'related_ids': []}])
        _, ai = self.draft(series, [{'news_id': self.exam.id, 'related_ids': []}])
        articles = {a['id']: a for a in ai.call_args_list[0].kwargs['user_payload']['articles']}
        self.assertFalse(articles[self.fuel.id]['pickable'])
        self.assertTrue(articles[self.exam.id]['pickable'])

        pipeline.cancel(first)
        _, ai = self.draft(series, [{'news_id': self.fuel.id, 'related_ids': []}])
        articles = {a['id']: a for a in ai.call_args_list[0].kwargs['user_payload']['articles']}
        self.assertTrue(articles[self.fuel.id]['pickable'])

    def test_the_script_sees_recent_openings_and_closings_so_it_varies_them(self):
        series = create_series()
        _, ai = self.draft(series, [{'news_id': self.fuel.id, 'related_ids': []}])
        self.assertEqual(ai.call_args_list[1].kwargs['user_payload']['previous'], [])
        _, ai = self.draft(series, [{'news_id': self.exam.id, 'related_ids': []}])
        self.assertEqual(ai.call_args_list[1].kwargs['user_payload']['previous'],
                         [{'opening': 'প্রথম দৃশ্য।', 'closing': 'দ্বিতীয় দৃশ্য।'}])

    def test_auto_approve_goes_straight_to_voice_unless_the_ai_editor_left_a_problem(self):
        series = create_series(auto_approve=True)
        video, _ = self.draft(series, [{'news_id': self.fuel.id, 'related_ids': []}],
                              issues=[{'scene': 1, 'problem': 'Hard word', 'fixed': True}])
        self.assertEqual(video.status, Status.VOICING)
        video, _ = self.draft(series, [{'news_id': self.exam.id, 'related_ids': []}],
                              issues=[{'scene': 1, 'problem': 'Number not in the sources', 'fixed': False}])
        self.assertEqual(video.status, Status.REVIEW)
        self.assertEqual(video.issues[0]['scene'], 1)

    def test_the_ai_editor_fixes_the_script_but_cannot_change_its_scenes(self):
        series = create_series()
        fixed = script(self.fuel.id)
        fixed['scenes'][0]['narration'] = 'ঠিক করা দৃশ্য।'
        video, _ = self.draft(series, [{'news_id': self.fuel.id, 'related_ids': []}], edited=fixed,
                              issues=[{'scene': 1, 'problem': 'Hard word', 'fixed': True}])
        self.assertEqual(video.script['scenes'][0]['narration'], 'ঠিক করা দৃশ্য।')

        dropped = script(self.exam.id)
        dropped['scenes'] = dropped['scenes'][:1]
        video, _ = self.draft(series, [{'news_id': self.exam.id, 'related_ids': []}], edited=dropped,
                              issues=[{'scene': 2, 'problem': 'Too long', 'fixed': True}])
        self.assertEqual(len(video.script['scenes']), 2)
        self.assertEqual(video.issues, [{'scene': 2, 'problem': 'Too long', 'fixed': False}])

    def test_skips_without_calling_the_ai_when_nothing_is_pickable(self):
        series = create_series(category=Categories.objects.create(name='ফ্যাক্ট চেক', enabled=False, separate_feed=True))
        video = NewsVideo.objects.create(series=series, publish_at=timezone.now())
        with patch('portal.video.pipeline.run_realtime_translation') as ai:
            pipeline.draft(video)
        ai.assert_not_called()
        self.assertEqual(video.status, Status.SKIPPED)

    def test_a_category_series_picks_from_its_category_and_sees_main_feed_coverage(self):
        fact_check = Categories.objects.create(name='ফ্যাক্ট চেক', enabled=False, separate_feed=True)
        claim = create_news('claim', categoryid=fact_check)
        video, ai = self.draft(create_series(category=fact_check), [{'news_id': claim.id, 'related_ids': [self.exam.id]}])
        articles = {a['id']: a for a in ai.call_args_list[0].kwargs['user_payload']['articles']}
        self.assertTrue(articles[claim.id]['pickable'])
        self.assertFalse(articles[self.exam.id]['pickable'])
        self.assertIsNone(articles[self.exam.id]['summary'])
        self.assertEqual(video.status, Status.REVIEW)

    def test_a_failing_step_marks_the_video_failed_with_the_reason(self):
        video = NewsVideo.objects.create(series=create_series(), publish_at=timezone.now())
        with patch('portal.video.pipeline.run_realtime_translation', side_effect=RuntimeError('OpenAI down')):
            video_draft(video.id)
        video.refresh_from_db()
        self.assertEqual((video.status, video.error), (Status.FAILED, 'OpenAI down'))


class VoiceTests(MediaTestCase):
    def test_scene_and_word_times_follow_the_alignment(self):
        text = 'এক দুই\nতিন'
        alignment = {'characters': list(text),
                     'character_start_times_seconds': [i * 0.1 for i in range(len(text))],
                     'character_end_times_seconds': [i * 0.1 + 0.1 for i in range(len(text))]}
        timings = voice.align(alignment, ['এক দুই', 'তিন'])
        self.assertEqual(timings['duration'], 1.0)
        self.assertEqual(timings['scenes'], [{'start': 0.0, 'end': 0.7}, {'start': 0.7, 'end': 1.0}])
        self.assertEqual([w['text'] for w in timings['words']], ['এক', 'দুই', 'তিন'])
        self.assertEqual((timings['words'][1]['start'], timings['words'][1]['end']), (0.3, 0.6))

    def test_audio_tags_steer_the_voice_but_are_not_caption_words(self):
        text = '[serious] এক [brief pause] দুই'
        alignment = {'characters': list(text),
                     'character_start_times_seconds': [i * 0.1 for i in range(len(text))],
                     'character_end_times_seconds': [i * 0.1 + 0.1 for i in range(len(text))]}
        self.assertEqual([w['text'] for w in voice.align(alignment, [text])['words']], ['এক', 'দুই'])

    @override_settings(ELEVENLABS_API_KEY='key')
    def test_records_the_narration_and_queues_the_render(self):
        news = create_news('fuel')
        video = NewsVideo.objects.create(series=create_series(voice_id='voice-a, voice-b'), publish_at=timezone.now(),
                                         status=Status.VOICING, script=script(news.id))
        spoken = 'প্রথম দৃশ্য।\nদ্বিতীয় দৃশ্য।'
        reply = {'audio_base64': base64.b64encode(b'mp3').decode(), 'alignment': {
            'characters': list(spoken), 'character_start_times_seconds': [0.1] * len(spoken),
            'character_end_times_seconds': [2.0] * len(spoken)}}
        with patch('portal.video.voice.httpx.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = reply
            voice.record(video)
        self.assertEqual(post.call_args.kwargs['json']['text'], spoken)
        self.assertEqual(post.call_args.kwargs['json']['language_code'], 'bn')
        used = post.call_args.args[0].split('/')[-2]
        self.assertIn(used, ('voice-a', 'voice-b'))
        self.assertEqual(post.call_args.kwargs['headers'], {'xi-api-key': 'key'})
        video.refresh_from_db()
        self.assertEqual(video.status, Status.QUEUED)
        self.assertEqual(video.audio.read(), b'mp3')
        self.assertEqual(video.timings['voice'], used)

    @override_settings(ELEVENLABS_API_KEY='')
    def test_says_what_is_missing_without_a_key(self):
        video = NewsVideo.objects.create(series=create_series(), publish_at=timezone.now(), script=script())
        with self.assertRaisesMessage(RuntimeError, 'ELEVENLABS_API_KEY is not set'):
            voice.record(video)


class RendererApiTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user('renderer')
        user.user_permissions.add(Permission.objects.get(codename='change_newsvideo'))
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=user).key}')
        self.news = create_news('fuel')
        self.video = NewsVideo.objects.create(
            series=create_series(music_volume=0.2, template_props={'accent': '#c33'}), publish_at=timezone.now(),
            status=Status.QUEUED, script=script(self.news.id),
            timings={'duration': 4.0, 'scenes': [{'start': 0, 'end': 1.5}, {'start': 1.5, 'end': 4.0}], 'words': []})
        self.video.news.set([self.news])
        self.video.audio.save('voice.mp3', ContentFile(b'mp3'))

    def claim(self):
        return self.api.post(reverse('api_video_render_claim'))

    def test_hands_out_each_queued_video_once_with_its_template_inputs(self):
        response = self.claim()
        self.assertEqual(response.status_code, 200)
        props = response.json()['props']
        self.assertEqual(response.json()['composition'], 'Test')
        self.assertTrue(props['audioUrl'].startswith('https://glimpseapp.net/portal/media/video/audio/'))
        self.assertEqual((props['accent'], props['musicVolume'], props['durationInSeconds']), ('#c33', 0.2, 4.0))
        self.assertEqual(props['scenes'][1]['imageUrl'], self.news.imageurl)
        self.assertEqual(props['scenes'][1]['imageSource'], 'prothomalo.com')
        self.assertEqual(props['scenes'][1]['images'], [{'url': self.news.imageurl, 'source': 'prothomalo.com'}])
        self.assertEqual(props['verdict'], 'none')
        self.assertTrue(props['publishAt'])
        self.assertEqual(props['scenes'][1]['start'], 1.5)
        self.assertEqual(self.claim().status_code, 204)

    def test_a_lost_render_is_handed_out_again(self):
        self.claim()
        NewsVideo.objects.filter(pk=self.video.pk).update(render_started_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(self.claim().status_code, 200)

    def test_stores_the_render(self):
        self.claim()
        response = self.api.post(reverse('api_video_render_result', args=[self.video.pk]), {
            'video': SimpleUploadedFile('out.mp4', b'mp4', content_type='video/mp4'),
            'thumbnail': SimpleUploadedFile('out.jpg', b'jpg', content_type='image/jpeg'),
        })
        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Status.RENDERED)
        self.assertEqual(self.video.video.read(), b'mp4')

    def test_a_render_error_fails_the_video(self):
        self.claim()
        self.api.post(reverse('api_video_render_result', args=[self.video.pk]), {'error': 'Chrome crashed'})
        self.video.refresh_from_db()
        self.assertEqual((self.video.status, self.video.error), (Status.FAILED, 'Render failed: Chrome crashed'))

    def test_needs_the_video_permission(self):
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=User.objects.create_user("x")).key}')
        self.assertEqual(api.post(reverse('api_video_render_claim')).status_code, 403)


class PublishTests(MediaTestCase):
    def rendered(self, **series_fields):
        video = NewsVideo.objects.create(series=create_series(**series_fields), status=Status.RENDERED,
                                         publish_at=timezone.now() - timedelta(minutes=1), script=script())
        video.video.save('out.mp4', ContentFile(b'mp4'))
        return video

    def test_publishes_due_videos_to_the_chosen_platforms(self):
        video = self.rendered(publish_facebook=True)
        with patch('portal.video.social.publish_facebook', return_value='fb1') as facebook, \
                patch('portal.video.social.publish_youtube') as youtube:
            self.assertEqual(pipeline.publish_due(), [video.id])
        youtube.assert_not_called()
        video.refresh_from_db()
        self.assertEqual((video.status, video.facebook_id), (Status.PUBLISHED, 'fb1'))
        self.assertEqual(facebook.call_count, 1)

    def test_a_failed_platform_is_retried_alone(self):
        video = self.rendered(publish_facebook=True, publish_youtube=True)
        with patch('portal.video.social.publish_facebook', return_value='fb1'), \
                patch('portal.video.social.publish_youtube', side_effect=RuntimeError('HTTP 401')):
            pipeline.publish_due()
        video.refresh_from_db()
        self.assertEqual((video.status, video.facebook_id, video.error), (Status.FAILED, 'fb1', 'YouTube: HTTP 401'))

        self.assertTrue(pipeline.retry(video))
        with patch('portal.video.social.publish_facebook') as facebook, \
                patch('portal.video.social.publish_youtube', return_value='yt1'):
            pipeline.publish_due()
        facebook.assert_not_called()
        video.refresh_from_db()
        self.assertEqual((video.status, video.youtube_id), (Status.PUBLISHED, 'yt1'))

    def test_without_platforms_the_video_waits_for_download(self):
        self.rendered()
        self.assertEqual(pipeline.publish_due(), [])

    def test_old_files_are_deleted_but_the_record_stays(self):
        video = self.rendered()
        NewsVideo.objects.filter(pk=video.pk).update(publish_at=timezone.now() - timedelta(days=31))
        self.assertEqual(pipeline.delete_old_files(), 1)
        video.refresh_from_db()
        self.assertFalse(video.video)
        self.assertEqual(video.script['title'], 'শিরোনাম')


class SocialTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.video = NewsVideo.objects.create(series=create_series(), publish_at=timezone.now(), script=script())
        self.video.video.save('out.mp4', ContentFile(b'mp4'))

    def reply(self, body=None, status=200, headers=None):
        return httpx.Response(status, json=body or {}, headers=headers or {})

    @override_settings(FACEBOOK_PAGE_ID='page', FACEBOOK_PAGE_TOKEN='token')
    def test_facebook_uploads_then_publishes_the_reel(self):
        replies = [self.reply({'video_id': 'v1', 'upload_url': 'https://rupload.facebook.com/video-upload/v1'}),
                   self.reply({'success': True}), self.reply({'success': True})]
        with patch('portal.video.social.httpx.post', side_effect=replies) as post:
            self.assertEqual(social.publish_facebook(self.video), 'v1')
        start, upload, finish = post.call_args_list
        self.assertEqual(start.kwargs['json'], {'upload_phase': 'start', 'access_token': 'token'})
        self.assertEqual((upload.args[0], upload.kwargs['content']), ('https://rupload.facebook.com/video-upload/v1', b'mp4'))
        self.assertEqual(upload.kwargs['headers']['file_size'], '3')
        self.assertEqual((finish.kwargs['params']['upload_phase'], finish.kwargs['params']['video_state']),
                         ('finish', 'PUBLISHED'))

    @override_settings(YOUTUBE_CLIENT_ID='id', YOUTUBE_CLIENT_SECRET='secret', YOUTUBE_REFRESH_TOKEN='refresh')
    def test_youtube_refreshes_the_token_and_uploads_the_short(self):
        posts = [self.reply({'access_token': 'access'}),
                 self.reply(headers={'Location': 'https://upload.example/session'})]
        with patch('portal.video.social.httpx.post', side_effect=posts) as post, \
                patch('portal.video.social.httpx.put', return_value=self.reply({'id': 'yt1'})) as put:
            self.assertEqual(social.publish_youtube(self.video), 'yt1')
        self.assertEqual(post.call_args_list[0].kwargs['data']['grant_type'], 'refresh_token')
        self.assertEqual(post.call_args_list[1].kwargs['json']['status']['privacyStatus'], 'public')
        self.assertEqual((put.call_args.args[0], put.call_args.kwargs['content']), ('https://upload.example/session', b'mp4'))

    def test_missing_keys_are_reported(self):
        with self.assertRaisesMessage(RuntimeError, 'FACEBOOK_PAGE_ID, FACEBOOK_PAGE_TOKEN must be set.'):
            social.publish_facebook(self.video)


class MediaViewTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        with open(f'{self.media}/clip.mp4', 'wb') as file:
            file.write(b'0123456789')

    def test_serves_whole_files_and_byte_ranges(self):
        whole = self.client.get('/portal/media/clip.mp4')
        self.assertEqual((whole.status_code, b''.join(whole.streaming_content)), (200, b'0123456789'))
        part = self.client.get('/portal/media/clip.mp4', HTTP_RANGE='bytes=2-4')
        self.assertEqual((part.status_code, part['Content-Range']), (206, 'bytes 2-4/10'))
        self.assertEqual(b''.join(part.streaming_content), b'234')
        tail = self.client.get('/portal/media/clip.mp4', HTTP_RANGE='bytes=-3')
        self.assertEqual(b''.join(tail.streaming_content), b'789')

    def test_never_leaves_the_media_folder(self):
        self.assertEqual(self.client.get('/portal/media/../manage.py').status_code, 404)


class ArticleTests(MediaTestCase):
    def test_news_create_keeps_the_full_article(self):
        serializer = NewsDetailSerializer(data={'title': 't', 'summary': 's', 'source': 'https://x.com/1',
                                                'original_news': ' পুরো খবর '})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        news = serializer.save()
        self.assertEqual(news.article.text, 'পুরো খবর')
        self.assertNotIn('original_news', serializer.data)


@override_settings(STORAGES={'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class VideoAdminTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser('admin', 'a@example.com', 'x'))
        self.news = create_news('fuel')
        self.video = NewsVideo.objects.create(series=create_series(), publish_at=timezone.now(), status=Status.REVIEW,
                                              script=script(self.news.id),
                                              issues=[{'scene': 2, 'problem': 'Unsupported number', 'fixed': False}])
        self.video.news.set([self.news])

    @override_settings(OPENAI_API_KEY='')
    def test_pages_show_the_series_setup_and_the_review(self):
        self.assertContains(self.client.get(reverse('admin:data_videoseries_changelist')), 'Missing:')
        page = self.client.get(reverse('admin:data_newsvideo_change', args=[self.video.pk]))
        self.assertContains(page, 'Scene 2: Unsupported number')
        self.assertContains(page, 'fuel title')

    def test_approving_records_the_voice_next(self):
        with patch('portal.tasks.video_voice.delay') as voice_task, self.captureOnCommitCallbacks(execute=True):
            self.client.get(reverse('admin:data_newsvideo_approve', args=[self.video.pk]))
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Status.VOICING)
        voice_task.assert_called_once_with(self.video.pk)
