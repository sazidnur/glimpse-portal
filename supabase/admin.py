"""
Auto-register all Supabase models in Django admin.

Models are generated from Supabase schema using:
    python manage.py generate_models --write

To sync with Supabase schema changes:
    python manage.py generate_models --write --force
"""

from django.contrib import admin
from django.apps import apps


# Auto-register all models from supabase app
supabase_models = apps.get_app_config('supabase').get_models()

for model in supabase_models:
    try:
        # Create a dynamic admin class with useful defaults
        admin_class = type(
            f'{model.__name__}Admin',
            (admin.ModelAdmin,),
            {
                'list_display': [f.name for f in model._meta.fields[:6]],  # First 6 fields
                'search_fields': [f.name for f in model._meta.fields if f.get_internal_type() in ('CharField', 'TextField')][:3],
                'list_per_page': 25,
            }
        )
        admin.site.register(model, admin_class)
    except admin.sites.AlreadyRegistered:
        pass
