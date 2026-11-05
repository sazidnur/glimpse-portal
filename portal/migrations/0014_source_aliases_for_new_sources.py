from django.db import migrations

ALIASES = [
    ('thedissent', 'দ্য ডিসেন্ট', 'The Dissent'),
    ('khulnagazette', 'খুলনা গেজেট', 'Khulna Gazette'),
    ('silkcitynews', 'সিল্কসিটি নিউজ', 'Silkcity News'),
    ('amaderbarisal', 'আমাদের বরিশাল', 'Amader Barishal'),
    ('ctgpratidin', 'চট্টগ্রাম প্রতিদিন', 'Chattogram Pratidin'),
    ('chattogramnews', 'চট্টগ্রাম নিউজ', 'Chattogram News'),
    ('sylheterdak', 'সিলেটের ডাক', 'Sylheter Dak'),
]


def add_aliases(apps, schema_editor):
    Sourcealias = apps.get_model('data', 'Sourcealias')
    for source, alias, alias_en in ALIASES:
        Sourcealias.objects.get_or_create(source=source, defaults={'alias': alias, 'alias_en': alias_en})


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0013_categories_separate_feed'),
    ]

    operations = [
        migrations.RunPython(add_aliases, migrations.RunPython.noop),
    ]
