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

If Redis throws an error, list requests fall back to querying the DB directly. Not ideal for latency, but the API stays up.

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
  "pages": 8
}
```

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
<summary><h2>Cloudflare Edge Worker (API Gateway)</h2></summary>

### What Is This?

There's a Cloudflare Worker sitting between the internet and our Django server. It acts as a gatekeeper for all `GET /api/v1/*` requests. Think of it as a bouncer + speed layer — it checks who you are before letting you read data, and it serves cached responses from Cloudflare's edge so the origin server doesn't get hammered.

It only touches `/api/v1/` paths. The admin panel, website, static files — none of that goes through the Worker.

In production, Django does **not** register the `/api/v1/` URL pattern at all — it only registers `/origin/api/v1/`. The middleware also blocks `/api/v1/` when `DEBUG=False` as defense-in-depth. This means the only way to reach the API in production is through the Worker. In local development (`DEBUG=True`), `/api/v1/` is available directly for convenience.

### How the Request Flow Works

```
Your App
   │
   ▼
Cloudflare Worker  (glimpseapp.net/api/v1/*)
   │
   ├── GET request?  → Check JWT → Serve from edge cache (or fetch origin)
   ├── POST/DELETE?   → Pass straight through to Django (you handle DRF auth)
   └── Not /api/v1/?  → Pass straight through to origin
   │
   ▼
Django + DRF  (glimpseapp.net/origin/api/v1/*)  ← Worker fetches from here
```

The Worker is deployed on `glimpseapp.net/api/v1/*`. When it needs fresh data from Django, it can't fetch from the same path (that would loop back into itself). So Django also mounts the same views at `/origin/api/v1/*`. This path is protected by a shared secret header (`X-Origin-Secret`) — only the Worker knows it. No extra subdomain needed, no server IP exposed.

### Two Types of Tokens

This system uses two separate tokens for different purposes:

**Worker JWT** — A short-lived token (2 hours) that the Worker creates and validates. This is what your app uses for reading data via GET requests. The app never talks to Django to get this token — it comes from the Worker itself.

**DRF Token** — The existing Django REST Framework token. Used for write operations (POST, DELETE) and also used internally by the Worker to fetch data from the origin. Your app still uses this for creating/deleting content, same as before.

The Worker JWT is a lightweight layer that protects the previously-public GET endpoints. Users of your app never see the DRF token for read operations — only the Worker uses it behind the scenes when it needs to fetch fresh data.

### What Each Request Type Does

**Getting a token (for your app to read data):**

```
POST https://glimpseapp.net/api/v1/get-token
X-App-Secret: your-shared-secret
```

Response:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 900
}
```

Your app should call this once, cache the token, and refresh it before it expires (every 15 min).

**Reading data (GET endpoints — news, videos, etc.):**

```
GET https://glimpseapp.net/api/v1/news/?page=1&limit=10
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

The Worker validates the JWT, then either:
- Returns the cached response instantly (`X-Cache: HIT`)
- Fetches from origin using the DRF token, caches it, returns it (`X-Cache: MISS`)

**Writing data (POST, DELETE — same as before):**

```
POST https://glimpseapp.net/api/v1/news/create/
Authorization: Token your-drf-token
Content-Type: application/json

{ "title": "...", "summary": "...", "source": "..." }
```

The Worker doesn't interfere here. It forwards the request to Django as-is. Your app sends the DRF token directly.

### Setting Up Auth in Your App

Here's the flow your app should follow:

1. **On app startup (or when the current token is expired):**
   - Call `POST /api/v1/get-token` with your `app_secret`
   - Store the returned JWT and its expiry time

2. **For every GET request:**
   - Attach the JWT: `Authorization: Bearer <jwt>`
   - If you get a 401 back, fetch a new token and retry

3. **For POST/DELETE requests:**
   - Use the DRF token directly: `Authorization: Token <drf-token>`
   - The Worker doesn't check these — they go straight to Django

Simple example:

```
// Pseudocode for any client

token = null
tokenExpiry = 0

function getToken():
    response = POST("https://glimpseapp.net/api/v1/get-token", {
        headers: { "X-App-Secret": APP_SECRET }
    })
    token = response.token
    tokenExpiry = now() + response.expires_in

function fetchAPI(endpoint):
    if token is null or now() > tokenExpiry:
        getToken()

    return GET(endpoint, {
        headers: { Authorization: "Bearer " + token }
    })

// Usage
news = fetchAPI("https://glimpseapp.net/api/v1/news/?page=1&limit=10")
```

### Edge Caching

Every successful GET response is cached at Cloudflare's edge for 30 minutes. The cache key is the full URL including query parameters, so `/api/v1/news/?page=1` and `/api/v1/news/?page=2` are cached separately.

Responses include an `X-Cache` header so you can see what happened:
- `HIT` — Served from edge cache, didn't touch origin
- `MISS` — Fetched from origin, now cached for next time
- `PREWARMED` — Cron job pre-filled this cache entry

Error responses (4xx, 5xx) are never cached.

When content is created or deleted through POST/DELETE, the cached GET responses will go stale. They automatically expire after 30 minutes. For a news/video feed, this is fine — users seeing slightly old data for a few minutes isn't a problem.

### Cron Pre-Warming

A scheduled job runs every 30 minutes and pre-fetches the most common endpoints so they're always warm in the edge cache:

- `/api/v1/news/`
- `/api/v1/news/?page=1&limit=10`
- `/api/v1/videos/`
- `/api/v1/videos/?page=1&limit=10`

This means the first real user request after a cache expiry still gets a fast response.

### Env Variables

Set secrets via Wrangler CLI (never commit these):

```bash
npx wrangler secret put TOKEN_SECRET        # Random 64-char string for JWT signing
npx wrangler secret put APP_SECRET          # The secret your app sends to get tokens
npx wrangler secret put DRF_TOKEN           # Django REST Framework auth token
npx wrangler secret put ORIGIN_BASE         # https://glimpseapp.net/origin
npx wrangler secret put ORIGIN_PATH_SECRET  # Same value as ORIGIN_PATH_SECRET in Django .env
```

Django side (`.env`):

```
ORIGIN_PATH_SECRET=your-random-secret-here
```

This secret must match between the Worker and Django. Generate it the same way as the others (`-join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Max 256) })`).

Plain variables in `wrangler.toml`:

| Variable | Value | What it does |
|----------|-------|-------------|
| `CACHE_TTL` | `1800` | Edge cache duration in seconds (30 min) |
| `WORKER_DOMAIN` | `glimpseapp.net` | Used for cron pre-warm cache key URLs |

### Files

| File | Purpose |
|------|---------|
| `cf-worker/src/index.js` | The Worker script |
| `cf-worker/wrangler.toml` | Wrangler config (routes, vars, cron) |
| `cf-worker/package.json` | Dependencies (wrangler) |
| `cf-worker/Dockerfile` | Container for wrangler — no local Node needed |
| `cf-worker/.dockerignore` | Keeps node_modules out of the image |

### Deploy (Docker — recommended)

No need to install Node or Wrangler locally. Everything runs in a container.

**First time setup:**

```bash
cd cf-worker

# Build the container
docker build -t glimpse-worker .

# Get an API token from: Cloudflare Dashboard → My Profile → API Tokens
# Use the "Edit Cloudflare Workers" template
# Set it as an env variable:
set CLOUDFLARE_API_TOKEN=your-token-here

# Set secrets (interactive, one at a time)
docker run --rm -it -e CLOUDFLARE_API_TOKEN=%CLOUDFLARE_API_TOKEN% glimpse-worker secret put TOKEN_SECRET
docker run --rm -it -e CLOUDFLARE_API_TOKEN=%CLOUDFLARE_API_TOKEN% glimpse-worker secret put APP_SECRET
docker run --rm -it -e CLOUDFLARE_API_TOKEN=%CLOUDFLARE_API_TOKEN% glimpse-worker secret put DRF_TOKEN
docker run --rm -it -e CLOUDFLARE_API_TOKEN=%CLOUDFLARE_API_TOKEN% glimpse-worker secret put ORIGIN_BASE
docker run --rm -it -e CLOUDFLARE_API_TOKEN=%CLOUDFLARE_API_TOKEN% glimpse-worker secret put ORIGIN_PATH_SECRET
```

**Deploy (every time you update the worker):**

```bash
docker run --rm -e CLOUDFLARE_API_TOKEN=%CLOUDFLARE_API_TOKEN% glimpse-worker deploy
```

**Live logs:**

```bash
docker run --rm -e CLOUDFLARE_API_TOKEN=%CLOUDFLARE_API_TOKEN% glimpse-worker tail
```

### Deploy (without Docker)

If you prefer installing locally:

```bash
cd cf-worker
npm install
npx wrangler login
npx wrangler secret put TOKEN_SECRET
npx wrangler secret put APP_SECRET
npx wrangler secret put DRF_TOKEN
npx wrangler secret put ORIGIN_BASE
npx wrangler secret put ORIGIN_PATH_SECRET
npx wrangler deploy
```

For local dev: `npx wrangler dev` starts a server at `http://localhost:8787`.
