"""
Django management command to generate/sync models from Supabase database.

Usage:
    python manage.py generate_models                    # Preview models
    python manage.py generate_models --write            # Write to portal/models.py
    python manage.py generate_models --write --force    # Overwrite without backup prompt
    python manage.py generate_models --table users      # Specific table only
    
Sync after Supabase schema changes:
    python manage.py generate_models --write --force
"""

import sys
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

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('🔍 Inspecting Supabase database schema...\n'))

        # Capture inspectdb output - using 'supabase' database
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

        # Always keep managed = False for Supabase models (we don't manage their schema)
        # Models are read-only schema, we just use them in admin to manage data

        if options['write']:
            models_path = Path(__file__).resolve().parent.parent.parent / 'models.py'
            
            # Check if models already exist
            if models_path.exists() and not options['force']:
                # Backup existing models
                backup_path = models_path.with_suffix('.py.backup')
                backup_path.write_text(models_path.read_text())
                self.stdout.write(self.style.SUCCESS(f'📁 Backed up existing models to {backup_path.name}'))

            models_path.write_text(models_content)
            self.stdout.write(self.style.SUCCESS(f'✅ Models written to supabase/models.py'))
            
            self.stdout.write(self.style.NOTICE('\n📝 Info:'))
            self.stdout.write('  • Models are auto-registered in admin (supabase/admin.py)')
            self.stdout.write('  • managed=False: Django won\'t touch Supabase schema')
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
