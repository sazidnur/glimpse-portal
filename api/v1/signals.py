import logging

from django.db.models.signals import post_save, post_delete

logger = logging.getLogger(__name__)

_registry = {}


def register_cache(model, cache):
    _registry[model] = cache
    post_save.connect(_on_save, sender=model)
    post_delete.connect(_on_delete, sender=model)


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
