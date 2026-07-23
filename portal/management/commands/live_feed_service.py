import signal

from django.core.management.base import BaseCommand

from portal.live_feed.service import LiveFeedService


class Command(BaseCommand):
    help = (
        'Run the live feed socket service: owns all hub WebSockets, '
        'answers publish RPCs from web/celery, and hosts pipeline runners.'
    )

    def handle(self, *args, **options):
        service = LiveFeedService()

        def _shutdown(signum, frame):
            service.stop()

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        service.run()
