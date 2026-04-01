from django.db import models


class Categories(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.TextField(unique=True)
    enabled = models.BooleanField(db_comment='should be visible to user as separate catory tab')
    order = models.IntegerField(blank=True, null=True, db_comment='app order')
    live_feed_type = models.IntegerField(default=0, db_comment='0=not live feed, 1+=live feed type ID')

    class Meta:
        db_table = 'categories'
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Divisions(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.TextField()
    order = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = 'divisions'
        verbose_name_plural = 'Divisions'

    def __str__(self):
        return self.name


class Extradetails(models.Model):
    id = models.BigAutoField(primary_key=True)
    news = models.ForeignKey('News', models.DO_NOTHING, blank=True, null=True)
    original_news = models.TextField()
    card = models.TextField(unique=True, blank=True, null=True)

    class Meta:
        db_table = 'extraDetails'
        verbose_name_plural = 'Extra Details'

    def __str__(self):
        return self.card or f"Extradetails {self.id}"


class News(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.TextField()
    summary = models.TextField()
    source = models.CharField(unique=True, max_length=255, db_comment='source url')
    imageurl = models.TextField(db_column='imageUrl', blank=True, null=True)  # Field name made lowercase.
    timestamp = models.DateTimeField()
    score = models.FloatField(blank=True, null=True)
    topic = models.ForeignKey('Topics', models.DO_NOTHING, db_column='topic', blank=True, null=True)
    categoryid = models.ForeignKey(Categories, models.DO_NOTHING, db_column='categoryId', blank=True, null=True)  # Field name made lowercase.
    divisionid = models.ForeignKey(Divisions, models.DO_NOTHING, db_column='divisionId', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        db_table = 'news'
        verbose_name_plural = 'News'

    def __str__(self):
        return self.title


class Sourcealias(models.Model):
    id = models.BigAutoField(primary_key=True)
    source = models.TextField(unique=True)
    alias = models.TextField()
    alias_en = models.TextField()

    class Meta:
        db_table = 'sourceAlias'
        verbose_name_plural = 'Source Aliases'

    def __str__(self):
        return self.alias


class Timelines(models.Model):
    id = models.BigAutoField(primary_key=True)
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    title = models.TextField(blank=True, null=True)
    newslist = models.TextField(db_column='newsList', blank=True, null=True)  # Field name made lowercase. This field type is a guess.
    imgurl = models.TextField(db_column='imgUrl', blank=True, null=True)  # Field name made lowercase.
    isnew = models.BooleanField(db_column='isNew', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        db_table = 'timelines'
        verbose_name_plural = 'Timelines'

    def __str__(self):
        return self.title or f"Timeline {self.id}"


class Topics(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.TextField(unique=True)
    order = models.IntegerField()
    enabled = models.BooleanField(blank=True, null=True)
    image = models.TextField(unique=True, blank=True, null=True)

    class Meta:
        db_table = 'topics'
        verbose_name_plural = 'Topics'

    def __str__(self):
        return self.name


class Videopublishers(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.TextField(unique=True)
    url = models.TextField(unique=True)
    profileiconurl = models.TextField(db_column='profileIconUrl', blank=True, null=True)  # Field name made lowercase.
    platform = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'videoPublishers'
        verbose_name_plural = 'Video publishers'

    def __str__(self):
        return self.title


class Videos(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.TextField(blank=True, null=True)
    videourl = models.TextField(db_column='videoUrl', blank=True, null=True)  # Field name made lowercase.
    source = models.TextField(blank=True, null=True)
    publisher = models.ForeignKey(Videopublishers, models.SET_NULL, db_column='publisher', blank=True, null=True)
    timestamp = models.DateTimeField()
    score = models.FloatField(blank=True, null=True)
    thumbnailurl = models.TextField(db_column='thumbnailUrl', blank=True, null=True, db_comment='thumbnailUrl')  # Field name made lowercase.

    class Meta:
        db_table = 'videos'
        verbose_name_plural = 'Videos'

    def __str__(self):
        return self.title or self.videourl or f"Video {self.id}"


class LiveFeedLog(models.Model):
    class LogLevel(models.IntegerChoices):
        DEBUG = 0, 'Debug'
        INFO = 1, 'Info'
        WARNING = 2, 'Warning'
        ERROR = 3, 'Error'

    class EventType(models.TextChoices):
        CONNECT = 'connect', 'Hub Connected'
        DISCONNECT = 'disconnect', 'Hub Disconnected'
        PUBLISH = 'publish', 'Item Published'
        BROADCAST = 'broadcast', 'Snapshot Broadcast'
        RECEIVED = 'received', 'Message Received'
        ERROR = 'error', 'Error'

    id = models.BigAutoField(primary_key=True)
    hub = models.CharField(max_length=20, db_index=True)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    level = models.IntegerField(choices=LogLevel.choices, default=LogLevel.INFO)
    message = models.TextField()
    details = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'live_feed_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['hub', '-created_at'], name='lfl_hub_created_idx'),
            models.Index(fields=['event_type', '-created_at'], name='lfl_event_created_idx'),
        ]

    def __str__(self):
        return f"[{self.get_level_display()}] {self.hub}: {self.message[:50]}"

    @classmethod
    def cleanup_if_needed(cls, threshold=1_000_000, delete_count=10_000):
        total = cls.objects.count()
        if total > threshold:
            oldest_ids = list(
                cls.objects.order_by('created_at')
                .values_list('id', flat=True)[:delete_count]
            )
            if oldest_ids:
                cls.objects.filter(id__in=oldest_ids).delete()
                return len(oldest_ids)
        return 0

    @classmethod
    def log(cls, hub, event_type, message, level=None, details=None):
        if level is None:
            level = cls.LogLevel.INFO
        entry = cls.objects.create(
            hub=hub,
            event_type=event_type,
            level=level,
            message=message,
            details=details
        )
        cls.cleanup_if_needed()
        return entry


class LiveFeedPipeline(models.Model):
    class Status(models.TextChoices):
        STOPPED = 'stopped', 'Stopped'
        STARTING = 'starting', 'Starting'
        RUNNING = 'running', 'Running'
        STOPPING = 'stopping', 'Stopping'
        ERROR = 'error', 'Error'

    id = models.BigAutoField(primary_key=True)
    source = models.CharField(max_length=60, db_index=True)
    category = models.ForeignKey(Categories, on_delete=models.CASCADE, related_name='live_feed_pipelines')
    pipeline_type = models.IntegerField(db_index=True)
    default_impact = models.IntegerField(default=2)
    config = models.JSONField(default=dict, blank=True)
    should_run = models.BooleanField(default=False, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STOPPED, db_index=True)
    owner_instance = models.CharField(max_length=80, blank=True, default='')
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_stopped_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')
    total_seen = models.BigIntegerField(default=0)
    total_published = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'live_feed_pipelines'
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'category'],
                name='lfp_source_category_uniq',
            )
        ]
        indexes = [
            models.Index(fields=['should_run', 'status'], name='lfp_run_status_idx'),
            models.Index(fields=['source', 'pipeline_type'], name='lfp_source_type_idx'),
        ]

    def __str__(self):
        return f"{self.source} -> {self.category_id} ({self.status})"


class LiveFeedPipelineLog(models.Model):
    class LogLevel(models.IntegerChoices):
        DEBUG = 0, 'Debug'
        INFO = 1, 'Info'
        WARNING = 2, 'Warning'
        ERROR = 3, 'Error'

    class EventType(models.TextChoices):
        START = 'start', 'Start'
        STOP = 'stop', 'Stop'
        UPDATE = 'update', 'Update'
        PUBLISH = 'publish', 'Publish'
        ERROR = 'error', 'Error'

    id = models.BigAutoField(primary_key=True)
    pipeline = models.ForeignKey(
        LiveFeedPipeline,
        on_delete=models.CASCADE,
        related_name='logs',
        db_index=True,
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    level = models.IntegerField(choices=LogLevel.choices, default=LogLevel.INFO)
    message = models.TextField()
    details = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'live_feed_pipeline_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['pipeline', '-created_at'], name='lfpl_pipe_created_idx'),
            models.Index(fields=['event_type', '-created_at'], name='lfpl_event_created_idx'),
        ]

    def __str__(self):
        return f"[{self.get_level_display()}] pipeline={self.pipeline_id}: {self.message[:50]}"

    @classmethod
    def cleanup_if_needed(cls, threshold=250_000, delete_count=5_000):
        total = cls.objects.count()
        if total > threshold:
            oldest_ids = list(
                cls.objects.order_by('created_at')
                .values_list('id', flat=True)[:delete_count]
            )
            if oldest_ids:
                cls.objects.filter(id__in=oldest_ids).delete()
                return len(oldest_ids)
        return 0

    @classmethod
    def log(cls, pipeline, event_type, message, level=None, details=None):
        if level is None:
            level = cls.LogLevel.INFO
        entry = cls.objects.create(
            pipeline=pipeline,
            event_type=event_type,
            level=level,
            message=message,
            details=details,
        )
        cls.cleanup_if_needed()
        return entry


class OpenAIJob(models.Model):
    class Mode(models.TextChoices):
        REALTIME = 'realtime', 'Realtime'
        BATCH = 'batch', 'Batch'

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        REALTIME_QUEUED = 'realtime_queued', 'Realtime Queued'
        REALTIME_RUNNING = 'realtime_running', 'Realtime Running'
        BATCH_QUEUED = 'batch_queued', 'Batch Queued'
        BATCH_SUBMITTED = 'batch_submitted', 'Batch Submitted'
        BATCH_TIMEOUT = 'batch_timeout', 'Batch Timeout'
        COMPLETED = 'completed', 'Completed'
        PUBLISHED = 'published', 'Published'
        FAILED = 'failed', 'Failed'
        CANCEL_REQUESTED = 'cancel_requested', 'Cancel Requested'
        CANCELLED = 'cancelled', 'Cancelled'

    id = models.BigAutoField(primary_key=True)
    pipeline = models.ForeignKey(
        LiveFeedPipeline,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='openai_jobs',
    )
    source = models.CharField(max_length=80, db_index=True)
    source_item_id = models.CharField(max_length=120, db_index=True)
    target_lang = models.CharField(max_length=16, default='en', db_index=True)
    target_hub = models.CharField(max_length=20, default='all')
    category_id = models.BigIntegerField(db_index=True)
    impact = models.IntegerField(default=0)
    timestamp = models.CharField(max_length=64, blank=True, default='')
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.REALTIME, db_index=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.QUEUED, db_index=True)
    cancel_requested = models.BooleanField(default=False, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    system_prompt = models.TextField(blank=True, default='')
    user_payload = models.JSONField(default=dict, blank=True)
    response_schema = models.JSONField(default=dict, blank=True)
    original_title = models.TextField(blank=True, default='')
    translated_title = models.TextField(blank=True, default='')

    provider_batch_id = models.CharField(max_length=120, blank=True, default='', db_index=True)
    provider_response_id = models.CharField(max_length=120, blank=True, default='', db_index=True)
    celery_task_id = models.CharField(max_length=120, blank=True, default='')
    batch_deadline_at = models.DateTimeField(null=True, blank=True)

    provider_request = models.JSONField(null=True, blank=True)
    provider_response = models.JSONField(null=True, blank=True)
    publish_result = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'openai_jobs'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'source_item_id', 'target_lang'],
                name='openai_job_source_item_lang_uniq',
            )
        ]
        indexes = [
            models.Index(fields=['status', 'mode'], name='openai_job_status_mode_idx'),
            models.Index(fields=['provider_batch_id', 'status'], name='openai_job_batch_status_idx'),
        ]

    def __str__(self):
        return f"{self.source}:{self.source_item_id} [{self.mode}/{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            self.Status.PUBLISHED,
            self.Status.FAILED,
            self.Status.CANCELLED,
        }


class OpenAIJobLog(models.Model):
    class Level(models.IntegerChoices):
        DEBUG = 0, 'Debug'
        INFO = 1, 'Info'
        WARNING = 2, 'Warning'
        ERROR = 3, 'Error'

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(OpenAIJob, on_delete=models.CASCADE, related_name='logs', db_index=True)
    level = models.IntegerField(choices=Level.choices, default=Level.INFO)
    message = models.TextField()
    details = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'openai_job_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job', '-created_at'], name='openai_job_log_job_created_idx'),
            models.Index(fields=['level', '-created_at'], name='oaj_log_level_created_idx'),
        ]

    def __str__(self):
        return f"[{self.get_level_display()}] job={self.job_id}: {self.message[:50]}"

    @classmethod
    def log(cls, job: OpenAIJob, message: str, *, level: int = Level.INFO, details: dict | None = None):
        return cls.objects.create(
            job=job,
            level=level,
            message=message,
            details=details,
        )
