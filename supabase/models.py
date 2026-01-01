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


class Extradetails(models.Model):
    id = models.BigAutoField(primary_key=True)
    news = models.ForeignKey('News', models.DO_NOTHING, blank=True, null=True)
    original_news = models.TextField()
    card = models.TextField(unique=True, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'extraDetails'


class News(models.Model):
    title = models.TextField()
    summary = models.TextField()
    source = models.CharField(unique=True, max_length=255, db_comment='source url')
    imageurl = models.CharField(db_column='imageUrl', blank=True, null=True)  # Field name made lowercase.
    timestamp = models.DateTimeField(blank=True, null=True)
    score = models.FloatField(blank=True, null=True)
    context = models.TextField(blank=True, null=True)
    categoryid = models.ForeignKey(Categories, models.DO_NOTHING, db_column='categoryId', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'news'


class Sourcealias(models.Model):
    id = models.BigAutoField(primary_key=True)
    source = models.TextField(unique=True)
    alias = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'sourceAlias'
        db_table_comment = 'News source name alias'


class Timelines(models.Model):
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField()
    title = models.CharField(blank=True, null=True)
    news_list = models.TextField(blank=True, null=True)  # This field type is a guess.
    imgurl = models.TextField(db_column='imgUrl', blank=True, null=True)  # Field name made lowercase.
    isnew = models.BooleanField(db_column='isNew', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'timelines'
        db_table_comment = 'series of news on a given topic'


class Videos(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(blank=True, null=True)
    videourl = models.CharField(db_column='videoUrl', blank=True, null=True)  # Field name made lowercase.
    source = models.CharField(blank=True, null=True)
    publisher = models.CharField(blank=True, null=True)
    timestamp = models.DateTimeField()
    score = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'videos'
        db_table_comment = 'video news'
