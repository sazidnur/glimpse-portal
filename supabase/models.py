# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class Categories(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField()
    enabled = models.BooleanField(db_comment='should be visible to user as separate catory tab')
    order = models.IntegerField(db_comment='app order')

    class Meta:
        managed = False
        db_table = 'categories'
        verbose_name_plural = 'Categories'


class Divisions(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(blank=True, null=True)
    order = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'divisions'
        db_table_comment = 'Eight divisions of BD'
        verbose_name_plural = 'Divisions'


class Extradetails(models.Model):
    id = models.BigAutoField(primary_key=True)
    news = models.ForeignKey('News', models.DO_NOTHING, blank=True, null=True)
    original_news = models.TextField()
    card = models.TextField(unique=True, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'extraDetails'
        verbose_name_plural = 'Extra Details'


class News(models.Model):
    title = models.TextField()
    summary = models.TextField()
    source = models.CharField(unique=True, max_length=255, db_comment='source url')
    imageurl = models.CharField(db_column='imageUrl', blank=True, null=True)  # Field name made lowercase.
    timestamp = models.DateTimeField(blank=True, null=True)
    score = models.FloatField(blank=True, null=True)
    topic = models.ForeignKey('Topics', models.DO_NOTHING, db_column='topic', blank=True, null=True)
    categoryid = models.ForeignKey(Categories, models.DO_NOTHING, db_column='categoryId', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'news'
        verbose_name_plural = 'News'


class Sourcealias(models.Model):
    id = models.BigAutoField(primary_key=True)
    source = models.TextField(unique=True)
    alias = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'sourceAlias'
        db_table_comment = 'News source name alias'
        verbose_name_plural = 'Source Aliases'


class Timelines(models.Model):
    id = models.BigAutoField(primary_key=True)
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    title = models.CharField(blank=True, null=True)
    newslist = models.TextField(db_column='newsList', blank=True, null=True)  # Field name made lowercase. This field type is a guess.
    imgurl = models.TextField(db_column='imgUrl', blank=True, null=True)  # Field name made lowercase.
    isnew = models.BooleanField(db_column='isNew', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'timelines'
        db_table_comment = 'series of news on a given topic'
        verbose_name_plural = 'Timelines'


class Topics(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.TextField(unique=True)
    order = models.IntegerField()
    enabled = models.BooleanField(blank=True, null=True)
    image = models.TextField(unique=True, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'topics'
        db_table_comment = 'contexts or topics'
        verbose_name_plural = 'Topics'


class Videopublishers(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.TextField(unique=True)
    url = models.TextField(unique=True)
    profileiconurl = models.TextField(db_column='profileIconUrl', blank=True, null=True)  # Field name made lowercase.
    platform = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'videoPublishers'
        verbose_name_plural = 'Video publishers'


class Videos(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(blank=True, null=True)
    videourl = models.CharField(db_column='videoUrl', blank=True, null=True)  # Field name made lowercase.
    source = models.CharField(blank=True, null=True)
    publisher = models.ForeignKey(Videopublishers, models.DO_NOTHING, db_column='publisher', blank=True, null=True)
    timestamp = models.DateTimeField()
    score = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'videos'
        db_table_comment = 'video news'
        verbose_name_plural = 'Videos'
