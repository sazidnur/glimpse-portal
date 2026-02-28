import json
import logging

from django_redis import get_redis_connection

logger = logging.getLogger(__name__)


class SortedSetCache:

    def __init__(self, prefix, model, serialize_fn, ttl=60 * 60 * 24 * 7):
        self.sorted_set_key = f"{prefix}:all"
        self.obj_key_prefix = f"{prefix}:obj:"
        self.member_prefix = prefix
        self.model = model
        self.serialize_fn = serialize_fn
        self.ttl = ttl

    def _redis(self):
        return get_redis_connection("default")

    def _score(self, obj):
        ts = getattr(obj, "timestamp", None)
        return ts.timestamp() if ts else 0.0

    def _serialize(self, obj):
        return json.dumps(self.serialize_fn(obj))

    def _deserialize(self, raw):
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def _member_key(self, obj_id):
        return f"{self.member_prefix}:{obj_id}"

    def _obj_key(self, obj_id):
        return f"{self.obj_key_prefix}{obj_id}"

    def _extract_id(self, member):
        return member.decode("utf-8").split(":")[1]

    def _calc_pages(self, total, limit):
        if limit <= 0:
            return 0
        return (total + limit - 1) // limit

    def warm(self):
        r = self._redis()
        qs = self.model.objects.all().order_by("-timestamp")
        count = 0
        pipe = r.pipeline()

        for obj in qs.iterator(chunk_size=500):
            pipe.zadd(self.sorted_set_key, {self._member_key(obj.id): self._score(obj)})
            pipe.set(self._obj_key(obj.id), self._serialize(obj), ex=self.ttl)
            count += 1

            if count % 1000 == 0:
                pipe.execute()
                pipe = r.pipeline()

        if count % 1000 != 0:
            pipe.execute()

        logger.info("%s cache warmed: %d items", self.member_prefix, count)
        return count

    def is_populated(self):
        return self._redis().zcard(self.sorted_set_key) > 0

    def ensure(self):
        if not self.is_populated():
            logger.info("%s cache empty, warming from DB...", self.member_prefix)
            self.warm()

    def _backfill(self, r, members, items):
        missing_ids = []
        raw_objects = r.mget([self._obj_key(self._extract_id(m)) for m in members])

        for i, raw in enumerate(raw_objects):
            if raw is not None:
                items.append(self._deserialize(raw))
            else:
                missing_ids.append(int(self._extract_id(members[i])))

        if missing_ids:
            logger.warning("Backfilling %d missing %s objects from DB", len(missing_ids), self.member_prefix)
            pipe = r.pipeline()
            for obj in self.model.objects.filter(id__in=missing_ids):
                data = self._serialize(obj)
                pipe.set(self._obj_key(obj.id), data, ex=self.ttl)
                items.append(self._deserialize(data))
            pipe.execute()

    def get_paginated(self, page=1, limit=10):
        self.ensure()
        r = self._redis()
        start = (page - 1) * limit
        members = r.zrevrange(self.sorted_set_key, start, start + limit - 1)
        total = r.zcard(self.sorted_set_key)

        items = []
        if members:
            self._backfill(r, members, items)

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": self._calc_pages(total, limit),
        }

    def get_all(self, max_items=10000):
        self.ensure()
        r = self._redis()
        members = r.zrevrange(self.sorted_set_key, 0, max_items - 1)
        total = r.zcard(self.sorted_set_key)

        items = []
        if members:
            self._backfill(r, members, items)

        return {"items": items, "total": total}

    def add(self, obj):
        r = self._redis()
        pipe = r.pipeline()
        pipe.zadd(self.sorted_set_key, {self._member_key(obj.id): self._score(obj)})
        pipe.set(self._obj_key(obj.id), self._serialize(obj), ex=self.ttl)
        pipe.execute()
        logger.info("Added %s:%d to cache", self.member_prefix, obj.id)

    def add_many(self, objects):
        r = self._redis()
        pipe = r.pipeline()
        for obj in objects:
            pipe.zadd(self.sorted_set_key, {self._member_key(obj.id): self._score(obj)})
            pipe.set(self._obj_key(obj.id), self._serialize(obj), ex=self.ttl)
        pipe.execute()
        logger.info("Added %d %s items to cache", len(objects), self.member_prefix)

    def delete(self, obj_id):
        r = self._redis()
        pipe = r.pipeline()
        pipe.zrem(self.sorted_set_key, self._member_key(obj_id))
        pipe.delete(self._obj_key(obj_id))
        pipe.execute()
        logger.info("Deleted %s:%d from cache", self.member_prefix, obj_id)

    def delete_many(self, obj_ids):
        r = self._redis()
        pipe = r.pipeline()
        for obj_id in obj_ids:
            pipe.zrem(self.sorted_set_key, self._member_key(obj_id))
            pipe.delete(self._obj_key(obj_id))
        pipe.execute()
        logger.info("Deleted %d %s items from cache", len(obj_ids), self.member_prefix)

    def update(self, obj):
        self.add(obj)
        logger.info("Updated %s:%d in cache", self.member_prefix, obj.id)

    def flush(self):
        r = self._redis()
        members = r.zrange(self.sorted_set_key, 0, -1)
        pipe = r.pipeline()
        for m in members:
            pipe.delete(self._obj_key(self._extract_id(m)))
        pipe.delete(self.sorted_set_key)
        pipe.execute()
        logger.info("Flushed %s cache", self.member_prefix)

    def stats(self):
        r = self._redis()
        total = r.zcard(self.sorted_set_key)
        mem = r.info("memory")
        return {
            "total_items": total,
            "redis_used_memory": mem.get("used_memory_human", "unknown"),
            "redis_peak_memory": mem.get("used_memory_peak_human", "unknown"),
        }
