from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0007_livefeedpipeline_config'),
    ]

    operations = [
        # Add config field to Categories
        migrations.AddField(
            model_name='categories',
            name='config',
            field=models.JSONField(blank=True, db_comment='Extra configuration: initial_fanout_limit, etc.', default=dict),
        ),
        
        # Create LiveFeedPublishedItem model
        migrations.CreateModel(
            name='LiveFeedPublishedItem',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('sequence_id', models.BigIntegerField(db_index=True)),
                ('title', models.TextField()),
                ('impact', models.IntegerField(default=0)),
                ('timestamp', models.DateTimeField(db_index=True)),
                ('hub', models.CharField(db_comment='Hub where item was published: all, or specific hub', db_index=True, max_length=20)),
                ('payload', models.JSONField(blank=True, db_comment='Full published payload including any extra fields', default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='published_items', to='data.categories')),
            ],
            options={
                'db_table': 'live_feed_published_items',
                'ordering': ['-created_at'],
            },
        ),
        
        # Add indexes for LiveFeedPublishedItem
        migrations.AddIndex(
            model_name='livefeedpublisheditem',
            index=models.Index(fields=['category', '-created_at'], name='lfpi_cat_created_idx'),
        ),
        migrations.AddIndex(
            model_name='livefeedpublisheditem',
            index=models.Index(fields=['category', '-sequence_id'], name='lfpi_cat_seq_idx'),
        ),
        migrations.AddIndex(
            model_name='livefeedpublisheditem',
            index=models.Index(fields=['-timestamp'], name='lfpi_timestamp_idx'),
        ),
    ]
