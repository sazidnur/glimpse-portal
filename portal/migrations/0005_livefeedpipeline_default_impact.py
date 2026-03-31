from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0004_livefeedpipeline_and_logs'),
    ]

    operations = [
        migrations.AddField(
            model_name='livefeedpipeline',
            name='default_impact',
            field=models.IntegerField(default=2),
        ),
    ]
