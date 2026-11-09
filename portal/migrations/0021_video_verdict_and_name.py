from django.db import migrations

DESCRIPTION_RULE = (
    '- description: one or two sentences on what the video covers, then "পুরো খবর পড়ুন Glimpse অ্যাপে।", '
    'then three relevant Bengali hashtags.'
)
VERDICT_RULE = (
    '- verdict: for a fact-check, its verdict: false (গুজব), misleading (বিভ্রান্তিকর) or true (সত্য). '
    'For any other video, none.'
)


def add_verdict(apps, schema_editor):
    VideoSeries = apps.get_model('data', 'VideoSeries')
    VideoSeries.objects.filter(template='DailyFive', name='আজকের ৫ খবর').update(name='আজকের পাঁচ খবর')
    VideoSeries.objects.filter(template='Pocket', name='আপনার পকেটে').update(name='আপনার পকেট')
    VideoSeries.objects.filter(template='FactCheck', name='গুজব না সত্য').update(name='গুজব না সত্য?')
    # The voice runs about 2.1 words a second; Facebook Reels stop at 90 seconds and the voice budget is about 30k
    # characters a month.
    for daily in VideoSeries.objects.filter(template='DailyFive', target_words=200):
        daily.target_words = 150
        daily.script_prompt = daily.script_prompt.replace(
            '30 to 40 words each, three or four sentences', '22 to 28 words each, three short sentences')
        daily.save(update_fields=['target_words', 'script_prompt'])
    for series in VideoSeries.objects.exclude(script_prompt__contains='- verdict:'):
        if DESCRIPTION_RULE in series.script_prompt:
            series.script_prompt = series.script_prompt.replace(DESCRIPTION_RULE, f'{DESCRIPTION_RULE}\n{VERDICT_RULE}')
        else:
            series.script_prompt = f'{series.script_prompt.rstrip()}\n\n{VERDICT_RULE}'
        series.save(update_fields=['script_prompt'])


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0020_video_spoken_prompts'),
    ]

    operations = [
        migrations.RunPython(add_verdict, migrations.RunPython.noop),
    ]
