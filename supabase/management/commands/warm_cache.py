import logging
import time

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Warm all Redis sorted-set caches from the database"

    def handle(self, *args, **options):
        from supabase.admin import CACHE_REGISTRY
        from api.v1.resources import rebuild_metadata_cache

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

        try:
            start = time.time()
            data = rebuild_metadata_cache()
            elapsed = time.time() - start
            self.stdout.write(self.style.SUCCESS(
                "  Metadata: categories=%d topics=%d divisions=%d publishers=%d source_aliases=%d warmed in %.2fs" % (
                    len(data.get("categories", [])),
                    len(data.get("topics", [])),
                    len(data.get("divisions", [])),
                    len(data.get("publishers", [])),
                    len(data.get("source_aliases", [])),
                    elapsed,
                )
            ))
        except Exception as e:
            self.stderr.write(self.style.WARNING(
                f"  Metadata: warm failed ({e}), will lazy-warm on first metadata request"
            ))
            logger.warning("Cache warm failed for metadata: %s", e)
