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
