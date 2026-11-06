from unittest.mock import patch

from django.test import TestCase, override_settings

from portal.models import Categories, LiveFeedPipeline, OpenAIJob
from portal.tasks import openai_process_realtime_job

from .jobs import enqueue_pipeline_translation_job


@override_settings(OPENAI_API_KEY='test-key')
class FlexModeTests(TestCase):
    def setUp(self):
        category = Categories.objects.create(name='Live', enabled=True, live_feed_type=1)
        self.pipeline = LiveFeedPipeline.objects.create(source='aljazeera', category=category, pipeline_type=1)
        self.delay = patch('portal.tasks.openai_process_realtime_job.delay').start()
        self.delay.return_value.id = 'task-1'
        self.publish = patch('portal.tasks.openai_publish_job.delay').start()
        self.addCleanup(patch.stopall)

    def enqueue(self, item_id='1', **config):
        job, _ = enqueue_pipeline_translation_job(
            pipeline_id=self.pipeline.id, source='aljazeera', source_item_id=item_id, category_id=self.pipeline.category_id,
            impact=1, timestamp='', original_title='Headline', system_prompt='Translate', user_payload={'title': 'Headline'},
            response_schema={}, pipeline_config=config,
        )
        return job

    def test_flex_is_the_default_and_runs_as_flex(self):
        job = self.enqueue()

        self.assertEqual((job.mode, job.status), (OpenAIJob.Mode.FLEX, OpenAIJob.Status.REALTIME_QUEUED))
        self.delay.assert_called_once_with(job.id, flex=True)

    def test_batch_mode_still_queues_for_batch(self):
        job = self.enqueue(openai_mode='batch')

        self.assertEqual(job.status, OpenAIJob.Status.BATCH_QUEUED)
        self.delay.assert_not_called()

    def test_flex_success_publishes(self):
        job = self.enqueue()
        with patch('portal.tasks.run_realtime_translation', return_value=({'t': 'শিরোনাম'}, 'resp-1', {})) as run:
            openai_process_realtime_job(job.id, flex=True)

        job.refresh_from_db()
        self.assertEqual((job.status, job.translated_title), (OpenAIJob.Status.COMPLETED, 'শিরোনাম'))
        self.assertTrue(run.call_args.kwargs['flex'])
        self.publish.assert_called_once_with(job.id)

    def test_flex_failure_falls_back_to_the_batch_queue(self):
        job = self.enqueue()
        with patch('portal.tasks.run_realtime_translation', side_effect=RuntimeError('Flex processing is temporarily unavailable')):
            openai_process_realtime_job(job.id, flex=True)

        job.refresh_from_db()
        self.assertEqual(job.status, OpenAIJob.Status.BATCH_QUEUED)
        self.assertIn('Flex failed', job.error_message)

    def test_standard_realtime_failure_still_fails(self):
        job = self.enqueue(openai_mode='realtime')
        with patch('portal.tasks.run_realtime_translation', side_effect=RuntimeError('boom')):
            openai_process_realtime_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, OpenAIJob.Status.FAILED)
