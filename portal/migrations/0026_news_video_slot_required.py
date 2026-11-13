from django.db import migrations, models


# Apart from 0025: Postgres cannot alter a table in the transaction that just updated its rows.
class Migration(migrations.Migration):

    dependencies = [
        ('data', '0025_news_video_slot_and_voice_speed'),
    ]

    operations = [
        migrations.AlterField(model_name='newsvideo', name='slot', field=models.DateTimeField(editable=False)),
        migrations.AddConstraint(
            model_name='newsvideo',
            constraint=models.UniqueConstraint(fields=('series', 'slot'), name='news_video_slot_unique'),
        ),
    ]
