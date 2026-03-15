import logging
import os

from django.core.management.base import BaseCommand, CommandError

from supabase.models import Videos
from supabase.youtube import validate_youtube_shorts_url

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Scan videos and delete non-Short YouTube entries using redirect check. "
        "Dry-run by default; pass --apply to execute deletion. "
        "Can persist candidate IDs and confirmed-shorts IDs for faster future runs."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete rows. Without this flag command runs in dry-run mode.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional max number of rows to scan.",
        )
        parser.add_argument(
            "--last",
            type=int,
            default=None,
            help="Optional max number of newest rows to scan (highest IDs first).",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=10,
            help="DB iterator chunk size (default: 10).",
        )
        parser.add_argument(
            "--sample",
            type=int,
            default=30,
            help="How many candidate rows to print as sample (default: 30).",
        )
        parser.add_argument(
            "--delete-batch-size",
            type=int,
            default=10,
            help="When using --apply, delete after every N candidates (default: 10).",
        )
        parser.add_argument(
            "--delete-ids-file",
            type=str,
            default="tmp/delete_non_shorts_ids.txt",
            help=(
                "Path to append candidate IDs (non-shorts/invalid). "
                "Default: tmp/delete_non_shorts_ids.txt"
            ),
        )
        parser.add_argument(
            "--confirmed-shorts-file",
            type=str,
            default="tmp/confirmed_shorts_ids.txt",
            help=(
                "Path to append IDs confirmed as shorts. "
                "Rows in this file are skipped on next runs. "
                "Default: tmp/confirmed_shorts_ids.txt"
            ),
        )
        parser.add_argument(
            "--log-every",
            type=int,
            default=10,
            help="Print progress after every N processed rows (default: 10).",
        )

    @staticmethod
    def _classify_validation_error(error_message):
        msg = str(error_message or "")
        if "Only YouTube Shorts URLs are allowed" in msg:
            return "non_short"
        if "Could not verify Shorts for non-shorts URL format" in msg:
            return "non_short_unverified_format"
        if "Only YouTube URLs are allowed" in msg:
            return "not_youtube"
        if "Invalid YouTube video URL" in msg:
            return "invalid_video_url"
        return "unknown"

    @staticmethod
    def _load_id_set(path):
        ids = set()
        if not path or not os.path.exists(path):
            return ids

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                value = line.strip()
                if not value:
                    continue
                try:
                    ids.add(int(value))
                except ValueError:
                    logger.warning("Skipping invalid ID in %s: %s", path, value)
        return ids

    @staticmethod
    def _append_ids(path, ids):
        if not path or not ids:
            return 0

        dirpath = os.path.dirname(path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)

        with open(path, "a", encoding="utf-8") as f:
            for row_id in sorted(ids):
                f.write(f"{row_id}\n")

        return len(ids)

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        limit = options["limit"]
        last = options["last"]
        chunk_size = max(int(options["chunk_size"]), 1)
        sample_limit = max(int(options["sample"]), 0)
        delete_batch_size = max(int(options["delete_batch_size"]), 1)
        delete_ids_file = (options["delete_ids_file"] or "").strip()
        confirmed_shorts_file = (options["confirmed_shorts_file"] or "").strip()
        log_every = max(int(options["log_every"]), 1)

        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than 0")
        if last is not None and last <= 0:
            raise CommandError("--last must be greater than 0")
        if limit is not None and last is not None:
            raise CommandError("Use either --limit or --last, not both")

        known_confirmed_short_ids = self._load_id_set(confirmed_shorts_file)
        known_delete_candidate_ids = self._load_id_set(delete_ids_file)

        qs = Videos.objects.all().only("id", "videourl")
        if limit is not None:
            qs = qs.order_by("id")[:limit]
        elif last is not None:
            qs = qs.order_by("-id")[:last]

        scanned = 0
        keep_count = 0
        skipped_known_short_count = 0
        unknown_count = 0
        invalid_url_count = 0
        candidate_count = 0
        pending_delete_ids = []
        new_confirmed_short_ids = set()
        new_delete_candidate_ids = set()
        deleted_total = 0
        delete_reasons = {}
        sample_rows = []

        self.stdout.write(
            f"Scanning video URLs... (known confirmed shorts: {len(known_confirmed_short_ids)})"
        )

        def print_progress():
            self.stdout.write(
                f"[progress] processed={scanned} kept={keep_count} "
                f"candidates={candidate_count} deleted={deleted_total} "
                f"unknown={unknown_count} skipped_known_short={skipped_known_short_count}"
            )

        for video in qs.iterator(chunk_size=chunk_size):
            scanned += 1
            if video.id in known_confirmed_short_ids:
                keep_count += 1
                skipped_known_short_count += 1
                if scanned % log_every == 0:
                    print_progress()
                continue

            url = (video.videourl or "").strip()

            if not url:
                candidate_count += 1
                pending_delete_ids.append(video.id)
                if video.id not in known_delete_candidate_ids:
                    new_delete_candidate_ids.add(video.id)
                invalid_url_count += 1
                delete_reasons["empty_url"] = delete_reasons.get("empty_url", 0) + 1
                if len(sample_rows) < sample_limit:
                    sample_rows.append((video.id, url, "empty_url"))
                if apply_changes and len(pending_delete_ids) >= delete_batch_size:
                    deleted_count, _ = Videos.objects.filter(
                        id__in=pending_delete_ids
                    ).delete()
                    deleted_total += deleted_count
                    pending_delete_ids = []
                    self.stdout.write(
                        f"[delete-batch] processed={scanned} deleted_now={deleted_count} "
                        f"deleted_total={deleted_total}"
                    )
                    print_progress()
                if scanned % log_every == 0:
                    print_progress()
                continue

            try:
                validate_youtube_shorts_url(url)
                keep_count += 1
                if video.id not in known_confirmed_short_ids:
                    new_confirmed_short_ids.add(video.id)
                if scanned % log_every == 0:
                    print_progress()
                continue
            except ValueError as exc:
                reason = self._classify_validation_error(str(exc))
                if reason == "unknown":
                    unknown_count += 1
                    if len(sample_rows) < sample_limit:
                        sample_rows.append((video.id, url, f"unknown:{exc}"))
                    logger.warning(
                        "Non-deterministic shorts check for video id=%s url=%s detail=%s",
                        video.id,
                        url,
                        str(exc),
                    )
                    if scanned % log_every == 0:
                        print_progress()
                    continue

                candidate_count += 1
                pending_delete_ids.append(video.id)
                if video.id not in known_delete_candidate_ids:
                    new_delete_candidate_ids.add(video.id)
                if reason in {"invalid_video_url", "not_youtube"}:
                    invalid_url_count += 1
                delete_reasons[reason] = delete_reasons.get(reason, 0) + 1
                if len(sample_rows) < sample_limit:
                    sample_rows.append((video.id, url, reason))
                if apply_changes and len(pending_delete_ids) >= delete_batch_size:
                    deleted_count, _ = Videos.objects.filter(
                        id__in=pending_delete_ids
                    ).delete()
                    deleted_total += deleted_count
                    pending_delete_ids = []
                    self.stdout.write(
                        f"[delete-batch] processed={scanned} deleted_now={deleted_count} "
                        f"deleted_total={deleted_total}"
                    )
                    print_progress()
                if scanned % log_every == 0:
                    print_progress()
                continue
            except Exception as exc:
                unknown_count += 1
                if len(sample_rows) < sample_limit:
                    sample_rows.append((video.id, url, f"unknown:{exc}"))
                logger.warning(
                    "Unexpected validation error for video id=%s url=%s detail=%s",
                    video.id,
                    url,
                    str(exc),
                )
                if scanned % log_every == 0:
                    print_progress()
                continue

        self.stdout.write("")
        self.stdout.write(f"Scanned: {scanned}")
        self.stdout.write(f"Confirmed shorts kept: {keep_count}")
        self.stdout.write(f"Skipped (already confirmed short): {skipped_known_short_count}")
        self.stdout.write(f"Deletion candidates: {candidate_count}")
        self.stdout.write(f"Invalid URLs among candidates: {invalid_url_count}")
        self.stdout.write(f"Unknown/unverified (not deleted): {unknown_count}")

        appended_candidate_ids = self._append_ids(
            delete_ids_file, new_delete_candidate_ids
        )
        appended_confirmed_short_ids = self._append_ids(
            confirmed_shorts_file, new_confirmed_short_ids
        )
        if delete_ids_file:
            self.stdout.write(
                f"Candidate ID file: {delete_ids_file} (new IDs appended: {appended_candidate_ids})"
            )
        if confirmed_shorts_file:
            self.stdout.write(
                "Confirmed-shorts ID file: "
                f"{confirmed_shorts_file} (new IDs appended: {appended_confirmed_short_ids})"
            )

        if delete_reasons:
            self.stdout.write("Candidate reasons:")
            for reason, count in sorted(delete_reasons.items()):
                self.stdout.write(f"  - {reason}: {count}")

        if sample_rows:
            self.stdout.write("")
            self.stdout.write("Sample rows:")
            for row_id, row_url, row_reason in sample_rows[:sample_limit]:
                self.stdout.write(f"  id={row_id} reason={row_reason} url={row_url}")

        if not apply_changes:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Dry-run mode: no rows deleted. Re-run with --apply to delete candidates."
            ))
            return

        if not candidate_count:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        if pending_delete_ids:
            deleted_count, _ = Videos.objects.filter(
                id__in=pending_delete_ids
            ).delete()
            deleted_total += deleted_count
            self.stdout.write(
                f"[delete-final] processed={scanned} deleted_now={deleted_count} "
                f"deleted_total={deleted_total}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"Deleted {deleted_total} non-shorts/invalid video rows from database."
        ))
