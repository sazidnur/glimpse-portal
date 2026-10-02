from django.db import transaction
from django.db.models.signals import post_delete, post_save

from portal.models import News


def _on_news_saved(sender, instance, **kwargs):
    from portal.tasks import search_index_news

    news_id = instance.id
    transaction.on_commit(lambda: search_index_news.delay([news_id]))


def _on_news_deleted(sender, instance, **kwargs):
    from portal.tasks import search_remove_news

    news_id = instance.id
    transaction.on_commit(lambda: search_remove_news.delay([news_id]))


def connect():
    post_save.connect(_on_news_saved, sender=News, dispatch_uid='search_index_news_save')
    post_delete.connect(_on_news_deleted, sender=News, dispatch_uid='search_index_news_delete')
