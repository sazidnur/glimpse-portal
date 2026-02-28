import logging
import time

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Warm all Redis sorted-set caches from the database"

    def handle(self, *args, **options):
        from supabase.admin import CACHE_REGISTRY

        for entry in CACHE_REGISTRY:
            key = entry["key"]
            label = entry["label"]
            try:
                start = time.time()
                count = entry["cache"].warm()
                elapsed = time.time() - start
                self.stdout.write(self.style.SUCCESS(
                    f"  {label}: {count} items warmed in {elapsed:.2f}s"
                ))
            except Exception as e:
                self.stderr.write(self.style.WARNING(
                    f"  {label}: warm failed ({e}), will lazy-warm on first request"
                ))
                logger.warning("Cache warm failed for %s: %s", key, e)
