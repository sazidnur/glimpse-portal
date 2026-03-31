from django.apps import AppConfig
import logging
import os
import sys
from django.conf import settings


logger = logging.getLogger(__name__)


class PortalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'portal'
    label = 'data'
    verbose_name = 'Glimpse Data'

    @staticmethod
    def _should_start_pipeline_monitor() -> bool:
        disable_flag = os.environ.get('DISABLE_LIVE_FEED_PIPELINES', '').strip().lower()
        if disable_flag in {'1', 'true', 'yes', 'on'}:
            return False

        blocked_commands = {
            'makemigrations',
            'migrate',
            'collectstatic',
            'shell',
            'dbshell',
            'test',
        }
        if len(sys.argv) > 1 and sys.argv[1] in blocked_commands:
            return False

        if settings.DEBUG:
            # In runserver autoreload, only start once in the serving process.
            if len(sys.argv) > 1 and sys.argv[1] == 'runserver':
                if os.environ.get('RUN_MAIN') != 'true':
                    return False
        return True

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
            logger.info("Metadata startup sync: rebuilding cache from database")
            rebuild_metadata_cache()
            logger.info("Metadata startup sync: done")
        except Exception as exc:
            logger.warning("Metadata startup sync skipped: %s", exc)

        if self._should_start_pipeline_monitor():
            try:
                from .live_feed.pipeline_manager import pipeline_manager
                pipeline_manager.start_monitor()
                logger.info("Live feed pipeline monitor started")
            except Exception as exc:
                logger.warning("Live feed pipeline monitor not started: %s", exc)
