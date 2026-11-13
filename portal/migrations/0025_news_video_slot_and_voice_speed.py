import django.core.validators
from django.db import migrations, models


def copy_publish_at(apps, schema_editor):
    apps.get_model('data', 'NewsVideo').objects.update(slot=models.F('publish_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0024_social_post_thumbnail'),
    ]

    operations = [
        migrations.AlterField(
            model_name='videoseries',
            name='voice_speed',
            field=models.FloatField(default=1.4, help_text="0.5 to 2. 1 is the voice's normal pace.", validators=[django.core.validators.MinValueValidator(0.5), django.core.validators.MaxValueValidator(2)]),
        ),
        migrations.RemoveConstraint(model_name='newsvideo', name='news_video_slot_unique'),
        migrations.AddField(model_name='newsvideo', name='slot', field=models.DateTimeField(editable=False, null=True)),
        migrations.RunPython(copy_publish_at, migrations.RunPython.noop),
    ]
