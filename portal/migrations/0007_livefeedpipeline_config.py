from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0006_openaijob_openaijoblog'),
    ]

    operations = [
        migrations.AddField(
            model_name='livefeedpipeline',
            name='config',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
