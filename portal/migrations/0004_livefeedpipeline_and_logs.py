from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0003_livefeedlog'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiveFeedPipeline',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('source', models.CharField(db_index=True, max_length=60)),
                ('pipeline_type', models.IntegerField(db_index=True)),
                ('should_run', models.BooleanField(db_index=True, default=False)),
                ('status', models.CharField(choices=[('stopped', 'Stopped'), ('starting', 'Starting'), ('running', 'Running'), ('stopping', 'Stopping'), ('error', 'Error')], db_index=True, default='stopped', max_length=20)),
                ('owner_instance', models.CharField(blank=True, default='', max_length=80)),
                ('last_started_at', models.DateTimeField(blank=True, null=True)),
                ('last_stopped_at', models.DateTimeField(blank=True, null=True)),
                ('last_activity_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('total_seen', models.BigIntegerField(default=0)),
                ('total_published', models.BigIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='live_feed_pipelines', to='data.categories')),
            ],
            options={
                'db_table': 'live_feed_pipelines',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='LiveFeedPipelineLog',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('event_type', models.CharField(choices=[('start', 'Start'), ('stop', 'Stop'), ('update', 'Update'), ('publish', 'Publish'), ('error', 'Error')], max_length=20)),
                ('level', models.IntegerField(choices=[(0, 'Debug'), (1, 'Info'), (2, 'Warning'), (3, 'Error')], default=1)),
                ('message', models.TextField()),
                ('details', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('pipeline', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='data.livefeedpipeline')),
            ],
            options={
                'db_table': 'live_feed_pipeline_logs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='livefeedpipeline',
            index=models.Index(fields=['should_run', 'status'], name='lfp_run_status_idx'),
        ),
        migrations.AddIndex(
            model_name='livefeedpipeline',
            index=models.Index(fields=['source', 'pipeline_type'], name='lfp_source_type_idx'),
        ),
        migrations.AddConstraint(
            model_name='livefeedpipeline',
            constraint=models.UniqueConstraint(fields=('source', 'category'), name='lfp_source_category_uniq'),
        ),
        migrations.AddIndex(
            model_name='livefeedpipelinelog',
            index=models.Index(fields=['pipeline', '-created_at'], name='lfpl_pipe_created_idx'),
        ),
        migrations.AddIndex(
            model_name='livefeedpipelinelog',
            index=models.Index(fields=['event_type', '-created_at'], name='lfpl_event_created_idx'),
        ),
    ]
