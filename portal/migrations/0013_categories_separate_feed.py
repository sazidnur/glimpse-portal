from django.db import migrations, models


def mark_fact_check(apps, schema_editor):
    apps.get_model('data', 'Categories').objects.filter(name='ফ্যাক্ট চেক').update(separate_feed=True)


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0012_search_reindex_jobs'),
    ]

    operations = [
        migrations.AddField(
            model_name='categories',
            name='separate_feed',
            field=models.BooleanField(default=False, db_comment='news served only by its own feed, kept out of the main feed'),
        ),
        migrations.RunPython(mark_fact_check, migrations.RunPython.noop),
    ]
