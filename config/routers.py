"""
Database Router for multi-database setup.

Routes:
- Supabase app models -> 'supabase' database
- Everything else (Django internals) -> 'default' database
"""


class DatabaseRouter:
    """
    Simple router: supabase app uses Supabase, everything else uses default.
    """
    
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'supabase':
            return 'supabase'
        return 'default'

    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'supabase':
            return 'supabase'
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        # Allow relations within same database
        db1 = 'supabase' if obj1._meta.app_label == 'supabase' else 'default'
        db2 = 'supabase' if obj2._meta.app_label == 'supabase' else 'default'
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == 'portal':
            return db == 'supabase'
        return db == 'default'
