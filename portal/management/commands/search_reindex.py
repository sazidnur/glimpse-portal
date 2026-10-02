import time

from django.core.management.base import BaseCommand, CommandError

from portal.models import News, SearchReindexJob
from portal.search import news_index, reindex
from portal.search.client import MeiliError, get_client


class Command(BaseCommand):
    help = 'Rebuild the Meilisearch news index from the database (zero downtime, via index swap).'

    def add_arguments(self, parser):
        parser.add_argument('--if-needed', action='store_true', help='Skip when the index already matches the database.')
        parser.add_argument('--wait', type=int, default=30, help='Seconds to wait for Meilisearch to become healthy.')

    def handle(self, *args, if_needed, wait, **options):
        deadline = time.monotonic() + wait
        while not get_client().is_healthy():
            if time.monotonic() > deadline:
                raise CommandError('Meilisearch is not reachable')
            time.sleep(1)

        try:
            news_index.ensure_index()
            if if_needed and news_index.document_count() == News.objects.count():
                self.stdout.write('Search index up to date, skipping reindex')
                return
        except MeiliError as exc:
            raise CommandError(f'Search index check failed: {exc}') from exc

        try:
            job = reindex.create_job(reindex.Trigger.DEPLOY)
        except reindex.ReindexAlreadyRunning as exc:
            self.stdout.write(f'Skipping: {exc}')
            return
        reindex.run(job.id)
        job.refresh_from_db()
        if job.status != SearchReindexJob.Status.SUCCEEDED:
            raise CommandError(f'Search reindex #{job.id} {job.status}: {job.error}')
        self.stdout.write(f'Search index rebuilt: {job.indexed} indexed, {job.removed} removed')
