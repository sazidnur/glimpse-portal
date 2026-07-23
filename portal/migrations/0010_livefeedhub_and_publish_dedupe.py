from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0009_categories_name_en'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiveFeedHub',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('hub', models.CharField(max_length=20, unique=True)),
                ('should_connect', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'live_feed_hubs',
            },
        ),
        migrations.AddField(
            model_name='livefeedpublisheditem',
            name='dedupe_key',
            field=models.CharField(
                blank=True,
                db_comment='Idempotency key so publish retries never create duplicate items',
                max_length=160,
                null=True,
                unique=True,
            ),
        ),
    ]
