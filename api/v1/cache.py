import json
import logging
from datetime import datetime, timezone

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
        self._populated = False  # avoids redundant ZCARD on every request

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
        if self._populated:
            return
        if not self.is_populated():
            logger.info("%s cache empty, warming from DB...", self.member_prefix)
            self.warm()
        self._populated = True

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

        # Guard: if Redis was wiped externally, re-warm automatically
        if total == 0 and self._populated:
            logger.warning("%s Redis appears wiped, re-warming...", self.member_prefix)
            self._populated = False
            self.ensure()
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

        # Guard: if Redis was wiped externally, re-warm automatically
        if total == 0 and self._populated:
            logger.warning("%s Redis appears wiped, re-warming...", self.member_prefix)
            self._populated = False
            self.ensure()
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
        self._populated = False  # reset so ensure() re-checks after flush
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


class MetadataCache:
    """Single-key Redis cache for the combined metadata response."""

    KEY = "metadata:all"
    LAST_SYNC_KEY = "metadata:last_sync_at"

    def __init__(self, ttl=60 * 60 * 24):
        self.ttl = ttl

    def _redis(self):
        return get_redis_connection("default")

    def get(self):
        raw = self._redis().get(self.KEY)
        if raw is None:
            logger.info("Metadata cache MISS (%s)", self.KEY)
            return None
        logger.info("Metadata cache HIT (%s)", self.KEY)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def set(self, data):
        r = self._redis()
        pipe = r.pipeline()
        pipe.set(self.KEY, json.dumps(data), ex=self.ttl)
        pipe.set(self.LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
        pipe.execute()
        logger.info(
            "Metadata cache SET (%s) ttl=%ss categories=%d topics=%d divisions=%d publishers=%d source_aliases=%d",
            self.KEY,
            self.ttl,
            len(data.get("categories", [])),
            len(data.get("topics", [])),
            len(data.get("divisions", [])),
            len(data.get("publishers", [])),
            len(data.get("source_aliases", [])),
        )

    def flush(self):
        self._redis().delete(self.KEY)
        logger.info("Metadata cache FLUSH (%s)", self.KEY)

    def stats(self):
        r = self._redis()
        key_exists = bool(r.exists(self.KEY))
        ttl_seconds = r.ttl(self.KEY)
        last_sync_raw = r.get(self.LAST_SYNC_KEY)
        if isinstance(last_sync_raw, bytes):
            last_sync_raw = last_sync_raw.decode("utf-8")
        return {
            "cached": key_exists,
            "ttl_seconds": ttl_seconds if ttl_seconds is not None else -2,
            "last_sync_at": last_sync_raw or "",
        }


class WorkerTokenHandler:
    """
    Central token handler for Cloudflare Worker JWT tokens.
    """

    CACHE_KEY = "worker:token"
    EXPIRY_KEY = "worker:token:expires_at"
    # Refresh token 60 seconds before actual expiry to avoid race conditions
    SAFETY_MARGIN_SECONDS = 60
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self):
        pass

    def _redis(self):
        return get_redis_connection("default")

    def _get_config(self):
        from django.conf import settings
        worker_base = (getattr(settings, 'WORKER_BASE_URL', '') or '').rstrip('/')
        app_secret = (getattr(settings, 'APP_SECRET', '') or '').strip()
        if not worker_base or not app_secret:
            return None, None, 'WORKER_BASE_URL and APP_SECRET must be configured'
        return worker_base, app_secret, None

    def _get_cached(self):
        """
        Get cached token if valid and not expired.
        Returns (token, expires_in_seconds) or (None, 0) if no valid cache.
        """
        r = self._redis()
        pipe = r.pipeline()
        pipe.get(self.CACHE_KEY)
        pipe.get(self.EXPIRY_KEY)
        results = pipe.execute()

        token_raw, expiry_raw = results

        if not token_raw:
            return None, 0

        if isinstance(token_raw, bytes):
            token_raw = token_raw.decode("utf-8")
        if isinstance(expiry_raw, bytes):
            expiry_raw = expiry_raw.decode("utf-8")

        try:
            expires_at = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.warning("Worker token cache invalid expiry format")
            return None, 0

        now = datetime.now(timezone.utc)
        remaining = (expires_at - now).total_seconds() - self.SAFETY_MARGIN_SECONDS

        if remaining <= 0:
            return None, 0

        return token_raw, int(remaining)

    def _cache_token(self, token, expires_in_seconds):
        """Cache the token with its expiry time."""
        if not token or expires_in_seconds <= 0:
            return

        r = self._redis()
        expires_at = datetime.now(timezone.utc).timestamp() + expires_in_seconds
        expires_at_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        expires_at_iso = expires_at_dt.isoformat()

        # Cache with Redis TTL slightly longer than actual expiry
        ttl = expires_in_seconds + 10

        pipe = r.pipeline()
        pipe.set(self.CACHE_KEY, token, ex=ttl)
        pipe.set(self.EXPIRY_KEY, expires_at_iso, ex=ttl)
        pipe.execute()

        logger.info("Worker token cached (expires_in=%ds)", expires_in_seconds)

    def _fetch_token(self, worker_base, app_secret):
        """Fetch fresh token from Worker."""
        import urllib.request
        import urllib.error

        url = f'{worker_base}/api/v1/get-token'
        data = json.dumps({}).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-App-Secret': app_secret,
            'User-Agent': self.DEFAULT_USER_AGENT,
        }
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode('utf-8')
                result = json.loads(body) if body else {}
                token = str(result.get('token') or '').strip()
                if not token:
                    return None, 0, 'Worker token response missing token'
                expires_in = int(result.get('expires_in', 900))
                return token, expires_in, None
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = exc.read().decode('utf-8')[:200]
            except Exception:
                pass
            return None, 0, f'Worker token request failed ({exc.code}): {detail or exc.reason}'
        except Exception as exc:
            return None, 0, f'Worker token request error: {exc}'

    def get_token(self, user_agent=None):
        """
        Get a valid Worker JWT token.
        
        This is THE method to call throughout the project. It handles:
        - Checking Redis cache first
        - Fetching from Worker if needed
        - Caching new tokens automatically
        
        Args:
            user_agent: Optional user agent string (for logging on Worker side)
        
        Returns:
            tuple: (token, expires_in_seconds, error)
            - On success: (token_string, expires_in, None)
            - On error: (None, 0, error_message)
        """
        # Get config
        worker_base, app_secret, config_error = self._get_config()
        if config_error:
            return None, 0, config_error

        # Check cache first
        cached_token, remaining = self._get_cached()
        if cached_token:
            logger.debug("Worker token from cache (remaining: %ds)", remaining)
            return cached_token, remaining, None

        # Fetch fresh token
        logger.debug("Worker token cache miss, fetching from Worker...")
        token, expires_in, fetch_error = self._fetch_token(worker_base, app_secret)
        if fetch_error:
            return None, 0, fetch_error

        # Cache and return
        self._cache_token(token, expires_in)
        return token, expires_in, None


worker_token_handler = WorkerTokenHandler()
