from django.db import migrations, models

# The daily five used to open with its top story, which spoiled it before its own scene.
OLD_HOOK = 'makes the viewer want to stay, with a question, a teaser or the most striking fact.'
NO_SPOILER = ("leads into the stories without telling any of them: no fact, place, person or topic from the day's news, "
              "so no story is given away before its own scene. Its caption names the series or invites the viewer in, "
              "never a story's fact.")
OLD_EXAMPLE = '"আবারও স্বাগতম [series name]-এ। আজ প্রথমেই ঢাকার খবর।"'
EXAMPLE = '"আবারও স্বাগতম [series name]-এ। চলুন শুরু করি।"'

ARFA = '5WbDBNLwAg4h26Km0GgQ'  # the only female voice; repeated so she reads half the videos


def update(apps, schema_editor):
    VideoSeries = apps.get_model('data', 'VideoSeries')
    for series in VideoSeries.objects.filter(template='DailyFive'):
        series.script_prompt = series.script_prompt.replace(OLD_HOOK, NO_SPOILER).replace(OLD_EXAMPLE, EXAMPLE)
        series.save(update_fields=['script_prompt'])
    for series in VideoSeries.objects.filter(voice_id__contains=ARFA):
        ids = [v.strip() for v in series.voice_id.split(',') if v.strip()]
        ids += [ARFA] * (len(ids) - 2 * ids.count(ARFA))
        voice_id = ', '.join(ids)
        if len(voice_id) <= 255:
            series.voice_id = voice_id
            series.save(update_fields=['voice_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0026_news_video_slot_required'),
    ]

    operations = [
        migrations.AlterField(
            model_name='videoseries',
            name='voice_id',
            field=models.CharField(blank=True, help_text='ElevenLabs voice ID, or several separated by commas: each video gets one of them at random. Repeat an ID to pick it more often.', max_length=255),
        ),
        migrations.RunPython(update, migrations.RunPython.noop),
    ]
