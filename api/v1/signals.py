import logging

from django.db.models.signals import post_save, post_delete
from django.db import transaction

logger = logging.getLogger(__name__)

_registry = {}
_invalidators = {}


def register_cache(model, cache):
    _registry[model] = cache
    post_save.connect(_on_save, sender=model, dispatch_uid=f"cache_sync_save:{model._meta.label_lower}")
    post_delete.connect(_on_delete, sender=model, dispatch_uid=f"cache_sync_delete:{model._meta.label_lower}")


def register_invalidator(model, callback):
    callbacks = _invalidators.setdefault(model, [])
    if callback not in callbacks:
        callbacks.append(callback)
    post_save.connect(_on_invalidate, sender=model, dispatch_uid=f"cache_invalidate_save:{model._meta.label_lower}")
    post_delete.connect(_on_invalidate, sender=model, dispatch_uid=f"cache_invalidate_delete:{model._meta.label_lower}")


def _on_save(sender, instance, **kwargs):
    cache = _registry.get(sender)
    if not cache:
        return
    try:
        cache.add(instance)
    except Exception as e:
        logger.warning("Signal: failed to sync %s:%d to Redis: %s", cache.member_prefix, instance.id, e)


def _on_delete(sender, instance, **kwargs):
    cache = _registry.get(sender)
    if not cache:
        return
    try:
        cache.delete(instance.id)
    except Exception as e:
        logger.warning("Signal: failed to remove %s:%d from Redis: %s", cache.member_prefix, instance.id, e)


def _on_invalidate(sender, using=None, **kwargs):
    callbacks = _invalidators.get(sender, [])
    if not callbacks:
        return

    def _run_callback(cb, db_alias):
        try:
            cb(using=db_alias)
        except Exception as e:
            logger.warning("Signal: metadata invalidator failed for %s: %s", sender.__name__, e)

    for callback in callbacks:
        try:
            transaction.on_commit(lambda cb=callback, db_alias=using: _run_callback(cb, db_alias), using=using)
        except Exception as e:
            logger.warning("Signal: failed to run metadata invalidator for %s: %s", sender.__name__, e)
