from django.apps import AppConfig
import logging


logger = logging.getLogger(__name__)


class SupabaseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'supabase'
    verbose_name = 'Glimpse Data'

    def ready(self):
        from api.v1.signals import register_cache, register_invalidator
        from api.v1.resources import news_cache, video_cache, rebuild_metadata_cache
        from .models import (
            News,
            Videos,
            Categories,
            Topics,
            Divisions,
            Videopublishers,
            Sourcealias,
        )

        register_cache(News, news_cache)
        register_cache(Videos, video_cache)

        metadata_models = (
            Categories,
            Topics,
            Divisions,
            Videopublishers,
            Sourcealias,
        )
        for model in metadata_models:
            register_invalidator(model, rebuild_metadata_cache)

        # Ensure metadata Redis cache is synchronized from DB on every Django start.
        try:
            logger.info("Metadata startup sync: rebuilding cache from Supabase")
            rebuild_metadata_cache(using="supabase")
            logger.info("Metadata startup sync: done")
        except Exception as exc:
            logger.warning("Metadata startup sync skipped: %s", exc)
