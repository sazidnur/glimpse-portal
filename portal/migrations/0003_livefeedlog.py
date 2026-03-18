from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0002_alter_videos_publisher'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiveFeedLog',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('hub', models.CharField(db_index=True, max_length=20)),
                ('event_type', models.CharField(
                    choices=[
                        ('connect', 'Hub Connected'),
                        ('disconnect', 'Hub Disconnected'),
                        ('publish', 'Item Published'),
                        ('broadcast', 'Snapshot Broadcast'),
                        ('received', 'Message Received'),
                        ('error', 'Error')
                    ],
                    max_length=20
                )),
                ('level', models.IntegerField(
                    choices=[
                        (0, 'Debug'),
                        (1, 'Info'),
                        (2, 'Warning'),
                        (3, 'Error')
                    ],
                    default=1
                )),
                ('message', models.TextField()),
                ('details', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'db_table': 'live_feed_logs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='livefeedlog',
            index=models.Index(fields=['hub', '-created_at'], name='lfl_hub_created_idx'),
        ),
        migrations.AddIndex(
            model_name='livefeedlog',
            index=models.Index(fields=['event_type', '-created_at'], name='lfl_event_created_idx'),
        ),
    ]
