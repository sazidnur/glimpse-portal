"""Generate/sync Django models from Supabase. Preserves verbose_name_plural & db_table_comment."""

import re
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate/sync Django models from Supabase database schema'

    def add_arguments(self, parser):
        parser.add_argument(
            '--write',
            action='store_true',
            help='Write models to portal/models.py (default: preview only)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Overwrite existing models without confirmation (for sync)',
        )
        parser.add_argument(
            '--table',
            type=str,
            help='Generate model for specific table only',
        )
        parser.add_argument(
            '--include-views',
            action='store_true',
            help='Include database views',
        )

    @staticmethod
    def _parse_existing_meta(models_path):
        """Extract db_table -> {verbose_name_plural, db_table_comment} from existing models.py."""
        meta_map = {}
        if not models_path.exists():
            return meta_map

        content = models_path.read_text(encoding='utf-8')
        class_blocks = re.split(r'(?=^class \w+\(models\.Model\):)', content, flags=re.MULTILINE)

        for block in class_blocks:
            db_table_match = re.search(r"db_table\s*=\s*['\"](.+?)['\"]", block)
            if not db_table_match:
                continue
            db_table = db_table_match.group(1)

            meta_info = {}
            vn_match = re.search(r"verbose_name_plural\s*=\s*['\"](.+?)['\"]", block)
            if vn_match:
                meta_info['verbose_name_plural'] = vn_match.group(1)

            tc_match = re.search(r"db_table_comment\s*=\s*['\"](.+?)['\"]", block)
            if tc_match:
                meta_info['db_table_comment'] = tc_match.group(1)

            if meta_info:
                meta_map[db_table] = meta_info

        return meta_map

    @staticmethod
    def _auto_verbose_plural(class_name):
        """Generate readable verbose_name_plural from CamelCase class name."""
        return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', class_name)

    def _apply_meta_preservations(self, models_content, meta_map):
        """Re-inject preserved Meta attrs into freshly generated models; auto-generate for new ones."""
        lines = models_content.split('\n')
        result_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]

            if line.strip() == 'class Meta:':
                meta_block_lines = [line]
                i += 1
                while i < len(lines) and (lines[i].strip() == '' or lines[i].startswith('        ')):
                    meta_block_lines.append(lines[i])
                    i += 1

                meta_text = '\n'.join(meta_block_lines)
                db_table_match = re.search(r"db_table\s*=\s*['\"](.+?)['\"]", meta_text)
                if db_table_match:
                    db_table = db_table_match.group(1)
                    existing = meta_map.get(db_table, {})

                    class_name = None
                    for prev_line in reversed(result_lines):
                        cls_match = re.match(r'^class (\w+)\(models\.Model\):', prev_line)
                        if cls_match:
                            class_name = cls_match.group(1)
                            break

                    if 'verbose_name_plural' in existing:
                        desired_plural = existing['verbose_name_plural']
                    elif class_name:
                        desired_plural = self._auto_verbose_plural(class_name)
                    else:
                        desired_plural = None

                    desired_comment = existing.get('db_table_comment')

                    cleaned = []
                    for ml in meta_block_lines:
                        if 'verbose_name_plural' in ml:
                            continue
                        if 'db_table_comment' in ml and desired_comment:
                            continue
                        cleaned.append(ml)
                    meta_block_lines = cleaned

                    insert_idx = None
                    for idx, ml in enumerate(meta_block_lines):
                        if 'db_table' in ml and 'db_table_comment' not in ml:
                            insert_idx = idx
                            break

                    if insert_idx is not None:
                        next_idx = insert_idx + 1
                        if next_idx < len(meta_block_lines) and 'db_table_comment' in meta_block_lines[next_idx]:
                            insert_idx = next_idx

                        additions = []
                        if desired_comment:
                            additions.append(f"        db_table_comment = '{desired_comment}'")
                        if desired_plural:
                            additions.append(f"        verbose_name_plural = '{desired_plural}'")

                        for j, add_line in enumerate(additions):
                            meta_block_lines.insert(insert_idx + 1 + j, add_line)

                result_lines.extend(meta_block_lines)
            else:
                result_lines.append(line)
                i += 1

        return '\n'.join(result_lines)

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('🔍 Inspecting Supabase database schema...\n'))

        models_path = Path(__file__).resolve().parent.parent.parent / 'models.py'
        existing_meta = self._parse_existing_meta(models_path)
        if existing_meta:
            self.stdout.write(self.style.NOTICE(
                f'📎 Preserving Meta from {len(existing_meta)} existing model(s): '
                + ', '.join(existing_meta.keys())
            ))

        output = StringIO()
        
        inspectdb_args = ['--database', 'supabase']
        if options['table']:
            inspectdb_args.append(options['table'])
        if options['include_views']:
            inspectdb_args.append('--include-views')

        try:
            call_command('inspectdb', *inspectdb_args, stdout=output)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'❌ Error inspecting database: {e}'))
            self.stderr.write(self.style.WARNING('Make sure SUPABASE_DATABASE_URL is set correctly in .env'))
            return

        models_content = output.getvalue()

        if not models_content.strip() or 'from django.db import models' not in models_content:
            self.stdout.write(self.style.WARNING('⚠️ No tables found in Supabase database'))
            return

        models_content = self._apply_meta_preservations(models_content, existing_meta)

        if options['write']:
            if models_path.exists() and not options['force']:
                backup_path = models_path.with_suffix('.py.backup')
                backup_path.write_text(models_path.read_text())
                self.stdout.write(self.style.SUCCESS(f'📁 Backed up existing models to {backup_path.name}'))

            models_path.write_text(models_content, encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'✅ Models written to supabase/models.py'))
            
            self.stdout.write(self.style.NOTICE('\n📝 Info:'))
            self.stdout.write('  • Models are auto-registered in admin (supabase/admin.py)')
            self.stdout.write('  • managed=False: Django won\'t touch Supabase schema')
            self.stdout.write('  • verbose_name_plural values are preserved across regenerations')
            self.stdout.write('  • Use admin portal to add/edit/delete data')
            self.stdout.write(self.style.NOTICE('\n🔄 To sync after Supabase schema changes:'))
            self.stdout.write('   python manage.py generate_models --write --force')
        else:
            # Preview mode
            self.stdout.write(self.style.NOTICE('📋 Preview of models from Supabase:\n'))
            self.stdout.write('=' * 60)
            self.stdout.write(models_content)
            self.stdout.write('=' * 60)
            self.stdout.write(self.style.NOTICE('\n💡 Commands:'))
            self.stdout.write('   python manage.py generate_models --write         # Save models')
            self.stdout.write('   python manage.py generate_models --write --force # Sync/update models')
