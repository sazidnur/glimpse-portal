from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0005_livefeedpipeline_default_impact'),
    ]

    operations = [
        migrations.CreateModel(
            name='OpenAIJob',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('source', models.CharField(db_index=True, max_length=80)),
                ('source_item_id', models.CharField(db_index=True, max_length=120)),
                ('target_lang', models.CharField(db_index=True, default='en', max_length=16)),
                ('target_hub', models.CharField(default='all', max_length=20)),
                ('category_id', models.BigIntegerField(db_index=True)),
                ('impact', models.IntegerField(default=0)),
                ('timestamp', models.CharField(blank=True, default='', max_length=64)),
                ('mode', models.CharField(choices=[('realtime', 'Realtime'), ('batch', 'Batch')], db_index=True, default='realtime', max_length=20)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('realtime_queued', 'Realtime Queued'), ('realtime_running', 'Realtime Running'), ('batch_queued', 'Batch Queued'), ('batch_submitted', 'Batch Submitted'), ('batch_timeout', 'Batch Timeout'), ('completed', 'Completed'), ('published', 'Published'), ('failed', 'Failed'), ('cancel_requested', 'Cancel Requested'), ('cancelled', 'Cancelled')], db_index=True, default='queued', max_length=30)),
                ('cancel_requested', models.BooleanField(db_index=True, default=False)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('system_prompt', models.TextField(blank=True, default='')),
                ('user_payload', models.JSONField(blank=True, default=dict)),
                ('response_schema', models.JSONField(blank=True, default=dict)),
                ('original_title', models.TextField(blank=True, default='')),
                ('translated_title', models.TextField(blank=True, default='')),
                ('provider_batch_id', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('provider_response_id', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('celery_task_id', models.CharField(blank=True, default='', max_length=120)),
                ('batch_deadline_at', models.DateTimeField(blank=True, null=True)),
                ('provider_request', models.JSONField(blank=True, null=True)),
                ('provider_response', models.JSONField(blank=True, null=True)),
                ('publish_result', models.JSONField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, default='')),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('pipeline', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='openai_jobs', to='data.livefeedpipeline')),
            ],
            options={
                'db_table': 'openai_jobs',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['status', 'mode'], name='openai_job_status_mode_idx'),
                    models.Index(fields=['provider_batch_id', 'status'], name='openai_job_batch_status_idx'),
                ],
                'constraints': [
                    models.UniqueConstraint(fields=('source', 'source_item_id', 'target_lang'), name='openai_job_source_item_lang_uniq'),
                ],
            },
        ),
        migrations.CreateModel(
            name='OpenAIJobLog',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('level', models.IntegerField(choices=[(0, 'Debug'), (1, 'Info'), (2, 'Warning'), (3, 'Error')], default=1)),
                ('message', models.TextField()),
                ('details', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='data.openaijob')),
            ],
            options={
                'db_table': 'openai_job_logs',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['job', '-created_at'], name='openai_job_log_job_created_idx'),
                    models.Index(fields=['level', '-created_at'], name='oaj_log_level_created_idx'),
                ],
            },
        ),
    ]
