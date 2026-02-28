# Glimpse Portal -- System Documentation

This is a living document. It covers how things are built, why certain decisions were made, and what you need to know to work with the system. We'll keep adding to it as new features land.

---

## Table of Contents

- [Redis Caching Layer](#redis-caching-layer)
- [REST API (v1)](#rest-api-v1)
- [Admin Cache Dashboard](#admin-cache-dashboard)
- [Architecture & Files](#architecture--files)
- [Known Considerations](#known-considerations)
- [Future Topics](#future-topics)

---

<details open>
<summary><h2>Redis Caching Layer</h2></summary>

### Why Redis?

The business data lives in an external Supabase PostgreSQL database. Every API call was hitting that remote DB directly, which adds latency and isn't great if the DB goes down. Redis sits in front of it as a fast local cache.

### How It Works (Sorted Set + Hash)

We use a generic `SortedSetCache` class that can cache any model. Each model gets:

- A **Redis Sorted Set** (`{prefix}:all`) holding all item IDs, scored by timestamp. This gives free pagination via `ZREVRANGE` -- "give me items 10 through 19" and Redis handles it.
- Each item's full data in a separate **Redis key** (`{prefix}:obj:{id}`) as JSON.

Currently configured for two models:

| Model   | Prefix  | Sorted Set Key | Object Key Pattern |
|---------|---------|----------------|--------------------|
| News    | `news`  | `news:all`     | `news:obj:{id}`    |
| Videos  | `video` | `video:all`    | `video:obj:{id}`   |

A paginated read does two things:
1. `ZREVRANGE {prefix}:all {start} {end}` -- grab the member keys for this page
2. `MGET {prefix}:obj:42 {prefix}:obj:41 ...` -- grab the actual data

Sub-millisecond for typical page sizes.

### Adding a New Model to the Cache

The cache is fully generic. To add a new model:

1. Write a serializer function in `api/v1/resources.py`
2. Create a `SortedSetCache` instance with the model and serializer
3. Create concrete view subclasses (one-liners extending the base classes)
4. Add URL routes in `api/v1/urls.py`
5. Add an entry to `CACHE_REGISTRY` in `supabase/admin.py` for the admin dashboard

That's it. No new cache logic, no new view logic.

### Why Not Per-Query Caching?

We considered caching each unique API query as its own key (e.g., `news:page=1&limit=10`). The problem is invalidation. When new items are added, every cached page shifts. You'd have to flush all keys on every write. The sorted set approach avoids this: adding an item is just `ZADD` + `SET`, and pagination recalculates on the fly.

### Cold Start

When Redis is empty (fresh deploy, restart, or flush), the first API request triggers a "warm" that loads all items from DB into Redis. This happens once. After that, everything serves from cache.

You can also warm manually via API or the admin dashboard.

### DB Fallback

If Redis throws an error, list requests fall back to querying the DB directly. The response includes `"cache": "DB_FALLBACK"` so you know it's not from cache. Not ideal for latency, but the API stays up.

### Memory

Each item takes roughly 1-3 KB. TTL is 7 days. At 100K items that's ~100-300 MB. Redis handles this without issue.

</details>

---

<details open>
<summary><h2>REST API (v1)</h2></summary>

Base path: `/api/v1/`

Both News and Videos follow the exact same URL pattern and behavior. Replace `news` with `videos` for the Videos API.

### Authentication

List endpoints are **public** (no token). All write and cache management endpoints require:
```
Authorization: Token <your-token>
```

### List

```
GET /api/v1/news/
GET /api/v1/videos/
```

Query parameters:
- `page` (int, default: 1) -- 1-based page number
- `limit` (int, default: 10, max: 100) -- items per page
- `all` (bool, default: false) -- returns all items (capped at 10,000)

Response:
```json
{
  "items": [ { "id": 1922, "title": "...", ... } ],
  "total": 73,
  "page": 1,
  "limit": 10,
  "pages": 8,
  "cache": "REDIS"
}
```

The `cache` field is `"REDIS"` or `"DB_FALLBACK"`.

### Create (single)

```
POST /api/v1/news/create/
```
```json
{
  "title": "Headline",
  "summary": "Details.",
  "source": "https://example.com/article"
}
```

Returns the created item with `201`.

### Create (batch)

Same endpoint. Send an array and it auto-detects:

```
POST /api/v1/news/create/
```
```json
[
  { "title": "First", "summary": "...", "source": "..." },
  { "title": "Second", "summary": "...", "source": "..." }
]
```

Returns `{ "created": 2, "items": [...] }` with `201`.

### Delete (single)

```
DELETE /api/v1/news/{id}/delete/
```

### Delete (batch)

```
DELETE /api/v1/news/delete/
```
```json
{ "ids": [42, 43, 44] }
```

Returns `{ "deleted": [42, 43], "count": 2, "not_found": [44] }`.

### Cache Stats

```
GET /api/v1/news/cache/
```

Returns items in Redis + memory usage.

### Warm Cache

```
POST /api/v1/news/cache/warm/
```

Full reload from DB into Redis.

### Flush Cache

```
POST /api/v1/news/cache/flush/
```

Wipes all cached data. Next read triggers automatic re-warm.

### News Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | string | yes | |
| `summary` | string | yes | |
| `source` | string | yes | URL |
| `imageurl` | string | no | |
| `timestamp` | datetime | no | Defaults to now |
| `score` | float | no | |
| `topic` | int | no | FK |
| `categoryid` | int | no | FK |

### Video Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | string | yes | |
| `videourl` | string | no | |
| `source` | string | no | |
| `publisher` | int | no | FK to Videopublishers |
| `timestamp` | datetime | no | Defaults to now |
| `score` | float | no | |
| `thumbnailurl` | string | no | |

</details>

---

<details open>
<summary><h2>Admin Cache Dashboard</h2></summary>

A unified page at `/portal/cache-dashboard/` to manage all Redis caches from one place.

### What It Does

- Shows a card per cached model (News, Videos) with live stats: cached count, DB total, sync status, memory usage
- **Per-resource actions**: Warm or Flush individual caches
- **Global actions**: Refresh All, Warm All, Flush All
- Sync indicator: `✓ Synced` (counts match), `Cold` (cache empty), or `X behind` (partial)
- Auto-loads stats on page open

### Access

- Link on the admin index page (top button)
- Direct URL: `/portal/cache-dashboard/`
- Requires admin login

### How It Works

The dashboard is a single HTML template (`templates/admin/cache_dashboard.html`) that makes AJAX calls to four endpoints registered on the admin site:

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `cache-dashboard/stats/{key}/` | GET | Returns cached count, DB total, memory |
| `cache-dashboard/warm/{key}/` | POST | Warms that cache from DB |
| `cache-dashboard/flush/{key}/` | POST | Flushes that cache |

These are registered via `AdminSite.get_urls` monkey-patch in `supabase/admin.py`.

### Adding a New Model

Add one entry to `CACHE_REGISTRY` in `supabase/admin.py`:

```python
CACHE_REGISTRY = [
    {"key": "news", "label": "News", "cache": news_cache, "model": "News"},
    {"key": "video", "label": "Videos", "cache": video_cache, "model": "Videos"},
    # Add here:
    {"key": "events", "label": "Events", "cache": event_cache, "model": "Events"},
]
```

The dashboard auto-renders the new card. No template changes needed.

</details>

---

<details open>
<summary><h2>Architecture & Files</h2></summary>

### Design Principles

- **Generic base classes** -- one `SortedSetCache`, six base `APIView` classes. Zero duplication.
- **Concrete subclasses are one-liners** -- just set `cache`, `model`, `serializer_class`.
- **Single file knows about specific models** -- `api/v1/resources.py` is the only place that imports `News` or `Videos`.

### File Map

| File | What it does |
|------|-------------|
| `api/v1/cache.py` | `SortedSetCache` class -- generic sorted-set + hash cache for any model |
| `api/v1/views.py` | 6 base `APIView` classes: `CachedListView`, `CachedCreateView`, `CachedDeleteView`, `CacheStatsView`, `CacheWarmView`, `CacheFlushView` |
| `api/v1/resources.py` | Cache instances (`news_cache`, `video_cache`), serializer functions, concrete view subclasses |
| `api/v1/serializers.py` | `NewsDetailSerializer`, `VideoDetailSerializer` (DRF ModelSerializers) |
| `api/v1/urls.py` | URL routes for all `/api/v1/` endpoints |
| `supabase/admin.py` | `CACHE_REGISTRY`, unified dashboard views, model admin classes, `AdminSite.get_urls` patch |
| `config/urls.py` | Root URL config, admin site setup |
| `config/settings.py` | Redis cache backend config (django-redis) |
| `config/middleware.py` | `APIIPWhitelistMiddleware` for `/api/` paths |
| `templates/admin/cache_dashboard.html` | Unified cache dashboard (JS + AJAX) |
| `templates/admin/custom_index.html` | Admin index override with dashboard link |

### SortedSetCache API

| Method | What it does |
|--------|-------------|
| `warm()` | Load all items from DB into Redis |
| `ensure()` | Warm only if cache is empty |
| `get_paginated(page, limit)` | Paginated read from sorted set |
| `get_all(max_items)` | All items (capped) |
| `add(obj)` | Add single item to cache + sorted set |
| `add_many(objects)` | Batch add via pipeline |
| `delete(obj_id)` | Remove single item |
| `delete_many(obj_ids)` | Batch remove via pipeline |
| `update(obj)` | Re-serialize and overwrite |
| `flush()` | Remove all items and the sorted set |
| `stats()` | Item count + Redis memory info |

### Base View Classes

| Class | HTTP | Auth | Behavior |
|-------|------|------|----------|
| `CachedListView` | GET | Public | Pagination, `?all=true`, DB fallback |
| `CachedCreateView` | POST | Token | Auto-detects single vs array (batch) |
| `CachedDeleteView` | DELETE | Token | Single by `pk` or batch by `{"ids":[...]}` |
| `CacheStatsView` | GET | Token | Returns `cache.stats()` |
| `CacheWarmView` | POST | Token | Returns `cache.warm()` |
| `CacheFlushView` | POST | Token | Calls `cache.flush()` |

</details>

---

<details open>
<summary><h2>Known Considerations</h2></summary>

### Admin Edits and Cache Sync

The Django admin can edit data directly in the database. Those changes won't reflect in Redis until the cache is warmed or flushed. Use the admin cache dashboard or the API warm endpoint to resync.

### IP Whitelist

The API middleware checks `ALLOWED_API_IPS` for all `/api/` paths. In production, set this to your server IPs. For development, set `ALLOWED_API_IPS=*`.

### Docker Setup

Redis runs as a container alongside Django and PostgreSQL. Only accessible within the Docker network (`redis://redis:6379/0`).

The `docker-compose.yml` Redis service:
- `redis:7-alpine` image
- 512 MB memory cap with LRU eviction
- Persistent volume (`redis_data`) so cache survives restarts
- Health check so Django waits for Redis

### Database Routing

Two databases: local PostgreSQL for Django internals (auth, sessions), Supabase PostgreSQL for business data (News, Videos, etc.). `config/routers.py` handles the routing -- `supabase` app models go to the `supabase` database.

### Traefik

Traefik reverse proxy routes `/portal` and `/api` to Django with priority 100. Config in `docker-compose.yml` labels.

</details>

---

<details open>
<summary><h2>Future Topics</h2></summary>

- News categories and topic filtering
- Admin panel cache sync hooks (auto warm on save/delete)
- Rate limiting and API key management
- Deployment and CI/CD pipeline
- WebSocket push for real-time cache updates

</details>
