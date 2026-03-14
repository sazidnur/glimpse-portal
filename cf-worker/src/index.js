const WORKER_CACHE_TTL = 120;
const WORKER_SWR = 15;
const CDN_CACHE_TTL = 1800-60;
const METADATA_CDN_TTL = 1800-60;
const NEWS_ALL_CDN_TTL = 86400-60;
// Dedicated Worker microcache name.
const MICROCACHE_NAME = "worker-microcache";
const TOKEN_EXPIRY = 7200;
const X_CACHE_WORKER = "0";
const X_CACHE_CDN = "1";
const X_CACHE_ORIGIN = "2";
const LIVE_FEED_HUB_NAME = "hub-apac";
const LIVE_FEED_LOCATION_HINT = "apac";

const _counts = { WORKER: 0, CDN: 0, ORIGIN: 0 };
let _lastFlush = Date.now();
const ANALYTICS_FLUSH_INTERVAL = 60_000;

function parseIntSafe(value, fallback, min = 1, max = Number.MAX_SAFE_INTEGER) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

function parseRequiredEnvInt(name, envValue, min = 1) {
  const parsed = Number.parseInt(envValue ?? "", 10);
  if (!Number.isInteger(parsed) || parsed < min) {
    throw new Error(`${name} must be configured as an integer >= ${min}`);
  }
  return parsed;
}

function normalizePath(pathname) {
  const normalized = pathname.replace(/\/+$/, "");
  return normalized || "/";
}

function maybeFlushAnalytics(env) {
  const now = Date.now();
  if (now - _lastFlush < ANALYTICS_FLUSH_INTERVAL) return;
  const total = _counts.WORKER + _counts.CDN + _counts.ORIGIN;
  if (total === 0) return;
  env.ANALYTICS?.writeDataPoint({
    doubles: [_counts.WORKER, _counts.CDN, _counts.ORIGIN],
    indexes: ["cache"],
  });
  _counts.WORKER = 0;
  _counts.CDN = 0;
  _counts.ORIGIN = 0;
  _lastFlush = now;
}

let _cachedSignKey = null;
let _cachedVerifyKey = null;

function base64UrlEncode(data) {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlDecode(str) {
  str = str.replace(/-/g, "+").replace(/_/g, "/");
  str += "=".repeat((4 - (str.length % 4)) % 4);
  return Uint8Array.from(atob(str), (c) => c.charCodeAt(0));
}

async function getHMACKey(secret, usage) {
  const isSign = usage.includes("sign");
  if (isSign && _cachedSignKey) return _cachedSignKey;
  if (!isSign && _cachedVerifyKey) return _cachedVerifyKey;

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    usage
  );

  if (isSign) _cachedSignKey = key;
  else _cachedVerifyKey = key;
  return key;
}

async function generateToken(env) {
  const now = Math.floor(Date.now() / 1000);

  const header = base64UrlEncode(
    new TextEncoder().encode(JSON.stringify({ alg: "HS256", typ: "JWT" }))
  );
  const payload = base64UrlEncode(
    new TextEncoder().encode(JSON.stringify({ iat: now, exp: now + TOKEN_EXPIRY }))
  );

  const key = await getHMACKey(env.TOKEN_SECRET, ["sign"]);
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`${header}.${payload}`)
  );

  return `${header}.${payload}.${base64UrlEncode(signature)}`;
}

async function verifyToken(token, env) {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return { valid: false, error: "Malformed token" };

    const [header, payload, signature] = parts;

    const key = await getHMACKey(env.TOKEN_SECRET, ["verify"]);
    const valid = await crypto.subtle.verify(
      "HMAC",
      key,
      base64UrlDecode(signature),
      new TextEncoder().encode(`${header}.${payload}`)
    );
    if (!valid) return { valid: false, error: "Invalid signature" };

    const claims = JSON.parse(new TextDecoder().decode(base64UrlDecode(payload)));
    if (!claims.exp || claims.exp < Date.now() / 1000) {
      return { valid: false, error: "Token expired" };
    }

    return { valid: true };
  } catch {
    return { valid: false, error: "Token verification failed" };
  }
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
};

function getCORSHeaders(env) {
  if (env?.ALLOWED_ORIGIN && env.ALLOWED_ORIGIN !== "*") {
    return { ...CORS_HEADERS, "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN };
  }
  return CORS_HEADERS;
}

function corsJSON(data, status = 200, env) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...getCORSHeaders(env) },
  });
}

function addCORS(response, env) {
  const resp = new Response(response.body, response);
  for (const [k, v] of Object.entries(getCORSHeaders(env))) resp.headers.set(k, v);
  return resp;
}

function handlePreflight(env) {
  return new Response(null, { status: 204, headers: getCORSHeaders(env) });
}

function getCDNTTL(url) {
  const pathNormalized = url.pathname.replace(/\/+$/, "");
  const isMetadata = pathNormalized === "/api/v1/metadata";
  const isNewsAll = pathNormalized === "/api/v1/news" && url.searchParams.get("all")?.toLowerCase() === "true";
  if (isMetadata) return METADATA_CDN_TTL;
  if (isNewsAll) return NEWS_ALL_CDN_TTL;
  return CDN_CACHE_TTL;
}

function isCDNHitStatus(status) {
  return ["HIT", "REVALIDATED", "UPDATING", "STALE"].includes((status || "").toUpperCase());
}

async function fetchOriginGET(url, env, cdnTtl) {
  return fetch(`${env.ORIGIN_BASE}${url.pathname}${url.search}`, {
    method: "GET",
    headers: {
      Authorization: `Token ${env.DRF_TOKEN}`,
      "X-Origin-Secret": env.ORIGIN_PATH_SECRET,
      Accept: "application/json",
    },
    cf: {
      cacheEverything: true,
      cacheTtl: cdnTtl,
    },
  });
}

async function proxyToOrigin(request, env) {
  const url = new URL(request.url);
  const headers = new Headers({
    "X-Origin-Secret": env.ORIGIN_PATH_SECRET,
    "Content-Type": request.headers.get("Content-Type") || "application/json",
    Accept: request.headers.get("Accept") || "application/json",
  });
  const clientAuth = request.headers.get("Authorization");
  if (clientAuth) headers.set("Authorization", clientAuth);

  const init = { method: request.method, headers };
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
  }

  const response = await fetch(`${env.ORIGIN_BASE}${url.pathname}${url.search}`, init);
  return addCORS(response, env);
}

async function handleGetToken(request, env) {
  if (request.method !== "POST") {
    return corsJSON({ error: "POST required" }, 405, env);
  }

  const appSecret = request.headers.get("X-App-Secret") || "";
  if (!appSecret || appSecret !== env.APP_SECRET) {
    return corsJSON({ error: "Forbidden" }, 403, env);
  }

  const token = await generateToken(env);
  return corsJSON({ token, token_type: "Bearer", expires_in: TOKEN_EXPIRY }, 200, env);
}

function nowIso() {
  return new Date().toISOString();
}

const WARM_ENDPOINTS = [
  "/api/v1/news/?page=1&limit=50",
  "/api/v1/news/?page=2&limit=50",
  "/api/v1/news/?page=1&limit=20",
  "/api/v1/videos/?page=1&limit=50",
  "/api/v1/videos/?page=2&limit=50",
  "/api/v1/metadata",
  "/api/v1/news/?all=true",
];

async function warmCache(env, source = "unknown") {
  const microcache = await caches.open(MICROCACHE_NAME);
  const workerDomain = env.WORKER_DOMAIN || "glimpseapp.net";
  const results = [];
  console.log(
    `[warm:start] ts=${nowIso()} source=${source} endpoints=${WARM_ENDPOINTS.length} worker_domain=${workerDomain}`
  );

  await Promise.allSettled(
    WARM_ENDPOINTS.map(async (endpoint) => {
      try {
        const publicUrl = `https://${workerDomain}${endpoint}`;
        const endpointUrl = new URL(publicUrl);
        const cdnTtl = getCDNTTL(endpointUrl);
        const originResp = await fetchOriginGET(endpointUrl, env, cdnTtl);

        if (originResp.ok) {
          const cfStatus = originResp.headers.get("CF-Cache-Status") || "NONE";
          const microEntry = new Response(originResp.body, originResp);
          microEntry.headers.set("Cache-Control", `s-maxage=${WORKER_CACHE_TTL}, stale-while-revalidate=${WORKER_SWR}`);
          microEntry.headers.set("X-Cache", X_CACHE_WORKER);

          await microcache.put(new Request(publicUrl), microEntry);

          console.log(
            `[warm:item] ts=${nowIso()} source=${source} endpoint="${endpoint}" status=ok code=${originResp.status} cf_cache_status=${cfStatus}`
          );
          results.push({ endpoint, status: "ok" });
        } else {
          const cfStatus = originResp.headers.get("CF-Cache-Status") || "NONE";
          console.warn(
            `[warm:item] ts=${nowIso()} source=${source} endpoint="${endpoint}" status=error code=${originResp.status} cf_cache_status=${cfStatus}`
          );
          results.push({ endpoint, status: "error", code: originResp.status });
        }
      } catch (e) {
        console.error(`[warm:item] ts=${nowIso()} source=${source} endpoint="${endpoint}" status=error error="${e.message}"`);
        results.push({ endpoint, status: "error", error: e.message });
      }
    })
  );

  const warmed = results.filter((r) => r.status === "ok").length;
  console.log(
    `[warm:end] ts=${nowIso()} source=${source} warmed=${warmed}/${WARM_ENDPOINTS.length}`
  );

  return results;
}

async function handleWarm(request, env) {
  if (request.method !== "POST") {
    return corsJSON({ error: "POST required" }, 405, env);
  }

  const appSecret = request.headers.get("X-App-Secret") || "";
  if (!appSecret || appSecret !== env.APP_SECRET) {
    return corsJSON({ error: "Forbidden" }, 403, env);
  }

  const results = await warmCache(env, "manual");
  const ok = results.filter((r) => r.status === "ok").length;
  return corsJSON({ warmed: ok, total: WARM_ENDPOINTS.length, results }, 200, env);
}

function getLiveFeedStub(env) {
  const namespace = env.GLIMPSE_LIVE_FEED;
  if (!namespace) {
    throw new Error("GLIMPSE_LIVE_FEED binding is missing");
  }
  const id = namespace.idFromName(LIVE_FEED_HUB_NAME);
  return namespace.get(id, { locationHint: LIVE_FEED_LOCATION_HINT });
}

async function requireBearerJWT(request, env) {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return corsJSON({ error: "Authorization: Bearer <token> required" }, 401, env);
  }

  const authResult = await verifyToken(authHeader.slice(7), env);
  if (!authResult.valid) {
    return corsJSON({ error: authResult.error }, 401, env);
  }

  return null;
}

async function handleLiveFeedSocket(request, env) {
  if (request.method !== "GET") {
    return corsJSON({ error: "GET required" }, 405, env);
  }

  const upgrade = request.headers.get("Upgrade") || "";
  if (upgrade.toLowerCase() !== "websocket") {
    return corsJSON({ error: "WebSocket upgrade required" }, 426, env);
  }

  const authHeader = request.headers.get("Authorization") || "";
  let token = "";
  if (authHeader.startsWith("Bearer ")) {
    token = authHeader.slice(7);
  } else {
    const url = new URL(request.url);
    token = (url.searchParams.get("token") || "").trim();
  }
  if (!token) {
    return corsJSON({ error: "Authorization token is required" }, 401, env);
  }
  const authResult = await verifyToken(token, env);
  if (!authResult.valid) {
    return corsJSON({ error: authResult.error }, 401, env);
  }

  try {
    const stub = getLiveFeedStub(env);
    const doRequest = new Request("https://live-feed/connect", {
      method: "GET",
      headers: request.headers,
    });
    return stub.fetch(doRequest);
  } catch (error) {
    return corsJSON({ error: `Live feed unavailable: ${error.message}` }, 503, env);
  }
}

async function handleLiveFeedPublish(request, env) {
  if (request.method !== "POST") {
    return corsJSON({ error: "POST required" }, 405, env);
  }
  const jwtError = await requireBearerJWT(request, env);
  if (jwtError) return jwtError;

  const rawBody = await request.text();
  try {
    const stub = getLiveFeedStub(env);
    const response = await stub.fetch("https://live-feed/admin/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: rawBody,
    });
    return addCORS(response, env);
  } catch (error) {
    return corsJSON({ error: `Live feed unavailable: ${error.message}` }, 503, env);
  }
}

async function handleLiveFeedPurgeCategory(request, env) {
  if (request.method !== "POST") {
    return corsJSON({ error: "POST required" }, 405, env);
  }
  const jwtError = await requireBearerJWT(request, env);
  if (jwtError) return jwtError;

  const rawBody = await request.text();
  try {
    const stub = getLiveFeedStub(env);
    const response = await stub.fetch("https://live-feed/admin/purge-category", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: rawBody,
    });
    return addCORS(response, env);
  } catch (error) {
    return corsJSON({ error: `Live feed unavailable: ${error.message}` }, 503, env);
  }
}

async function handleLiveFeedCategoryList(request, env) {
  if (request.method !== "GET") {
    return corsJSON({ error: "GET required" }, 405, env);
  }
  const jwtError = await requireBearerJWT(request, env);
  if (jwtError) return jwtError;

  try {
    const stub = getLiveFeedStub(env);
    const response = await stub.fetch("https://live-feed/admin/categories/list", {
      method: "GET",
    });
    return addCORS(response, env);
  } catch (error) {
    return corsJSON({ error: `Live feed unavailable: ${error.message}` }, 503, env);
  }
}

async function handleLiveFeedCategoryUpsert(request, env) {
  if (request.method !== "POST") {
    return corsJSON({ error: "POST required" }, 405, env);
  }
  const jwtError = await requireBearerJWT(request, env);
  if (jwtError) return jwtError;

  const rawBody = await request.text();
  try {
    const stub = getLiveFeedStub(env);
    const response = await stub.fetch("https://live-feed/admin/categories/upsert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: rawBody,
    });
    return addCORS(response, env);
  } catch (error) {
    return corsJSON({ error: `Live feed unavailable: ${error.message}` }, 503, env);
  }
}

async function handleLiveFeedCategoryDelete(request, env) {
  if (request.method !== "POST") {
    return corsJSON({ error: "POST required" }, 405, env);
  }
  const jwtError = await requireBearerJWT(request, env);
  if (jwtError) return jwtError;

  const rawBody = await request.text();
  try {
    const stub = getLiveFeedStub(env);
    const response = await stub.fetch("https://live-feed/admin/categories/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: rawBody,
    });
    return addCORS(response, env);
  } catch (error) {
    return corsJSON({ error: `Live feed unavailable: ${error.message}` }, 503, env);
  }
}

async function handleLiveFeedItemsList(request, env) {
  if (request.method !== "GET") {
    return corsJSON({ error: "GET required" }, 405, env);
  }
  const jwtError = await requireBearerJWT(request, env);
  if (jwtError) return jwtError;

  const url = new URL(request.url);
  try {
    const stub = getLiveFeedStub(env);
    const response = await stub.fetch(`https://live-feed/admin/items/list${url.search}`, {
      method: "GET",
    });
    return addCORS(response, env);
  } catch (error) {
    return corsJSON({ error: `Live feed unavailable: ${error.message}` }, 503, env);
  }
}

function doJSON(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export class LiveFeedHubv2 {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.sql = state.storage.sql;
    this._initialized = false;
  }

  async ensureInitialized() {
    if (this._initialized) return;

    await this.state.blockConcurrencyWhile(async () => {
      if (this._initialized) return;

      this.sql.exec(`
        CREATE TABLE IF NOT EXISTS items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          seq INTEGER NOT NULL,
          category_id INTEGER NOT NULL,
          title TEXT NOT NULL,
          ts TEXT NOT NULL,
          impact INTEGER NOT NULL DEFAULT 0,
          payload_json TEXT
        )
      `);
      this.sql.exec(`
        CREATE UNIQUE INDEX IF NOT EXISTS idx_items_category_seq_unique
        ON items(category_id, seq)
      `);
      this.sql.exec(`
        CREATE INDEX IF NOT EXISTS idx_items_category_seq_desc
        ON items(category_id, seq DESC)
      `);
      this.sql.exec(`
        CREATE INDEX IF NOT EXISTS idx_items_category_ts_desc
        ON items(category_id, ts DESC)
      `);
      this.sql.exec(`
        CREATE TABLE IF NOT EXISTS categories (
          category_id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          live_feed_type INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        )
      `);
      this.sql.exec(`
        CREATE INDEX IF NOT EXISTS idx_categories_live_enabled
        ON categories(live_feed_type, enabled)
      `);

      this._initialized = true;
    });
  }

  getInitItems() {
    return parseRequiredEnvInt("LIVE_FEED_INIT_ITEMS", this.env.LIVE_FEED_INIT_ITEMS, 1);
  }

  getMaxItemsPerCategory() {
    return parseRequiredEnvInt(
      "LIVE_FEED_MAX_ITEMS_PER_CATEGORY",
      this.env.LIVE_FEED_MAX_ITEMS_PER_CATEGORY,
      1
    );
  }

  getMaxLoadOlder() {
    return parseRequiredEnvInt("LIVE_FEED_MAX_LOAD_OLDER", this.env.LIVE_FEED_MAX_LOAD_OLDER, 1);
  }

  serializeItemRow(row) {
    let payload = null;
    if (row.payload_json) {
      try {
        payload = JSON.parse(row.payload_json);
      } catch {
        payload = null;
      }
    }
    return {
      seq: Number(row.seq),
      category_id: Number(row.category_id),
      title: row.title,
      timestamp: row.ts,
      impact: Number(row.impact || 0),
      payload,
    };
  }

  normalizeImpact(value) {
    const impact = Number.parseInt(value, 10);
    if (impact === 1 || impact === 2) return impact;
    return 0;
  }

  normalizeTimestamp(value) {
    if (!value) return new Date().toISOString();
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return new Date().toISOString();
    return parsed.toISOString();
  }

  parseCategoryId(value) {
    const categoryId = Number.parseInt(value, 10);
    if (!Number.isInteger(categoryId) || categoryId <= 0) return null;
    return categoryId;
  }

  parseBeforeSeq(value) {
    const beforeSeq = Number.parseInt(value, 10);
    if (!Number.isInteger(beforeSeq) || beforeSeq <= 0) return null;
    return beforeSeq;
  }

  normalizeEnabled(value) {
    if (typeof value === "boolean") return value ? 1 : 0;
    const parsed = Number.parseInt(value, 10);
    if (Number.isInteger(parsed)) return parsed === 0 ? 0 : 1;
    return 1;
  }

  normalizeLiveFeedType(value) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isInteger(parsed) || parsed < 0) return 0;
    return parsed;
  }

  getCategoryState(categoryId) {
    const row = this.sql
      .exec(
        "SELECT category_id, name, enabled, live_feed_type FROM categories WHERE category_id = ?",
        categoryId
      )
      .one();
    if (!row) return null;
    return {
      category_id: Number(row.category_id),
      name: row.name || "",
      enabled: Number(row.enabled || 0) === 1,
      live_feed_type: Number(row.live_feed_type || 0),
    };
  }

  upsertCategory(data) {
    const categoryId = this.parseCategoryId(data?.category_id);
    if (!categoryId) {
      return { ok: false, error: "category_id must be a positive integer", status: 400 };
    }

    const name = typeof data?.name === "string" ? data.name.trim() : "";
    const enabled = this.normalizeEnabled(data?.enabled);
    const liveFeedType = this.normalizeLiveFeedType(data?.live_feed_type);
    const updatedAt = new Date().toISOString();

    this.sql.exec(
      `INSERT INTO categories (category_id, name, enabled, live_feed_type, updated_at)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(category_id) DO UPDATE SET
         name = excluded.name,
         enabled = excluded.enabled,
         live_feed_type = excluded.live_feed_type,
         updated_at = excluded.updated_at`,
      categoryId,
      name,
      enabled,
      liveFeedType,
      updatedAt
    );

    return {
      ok: true,
      category: {
        category_id: categoryId,
        name,
        enabled: enabled === 1,
        live_feed_type: liveFeedType,
      },
    };
  }

  deleteCategory(categoryId) {
    this.sql.exec("DELETE FROM categories WHERE category_id = ?", categoryId);
    const catChanges = this.sql.exec("SELECT changes() AS total").one();
    this.sql.exec("DELETE FROM items WHERE category_id = ?", categoryId);
    const itemChanges = this.sql.exec("SELECT changes() AS total").one();
    return {
      category_deleted: Number(catChanges?.total || 0),
      items_deleted: Number(itemChanges?.total || 0),
    };
  }

  listCategories() {
    const rows = this.sql
      .exec(
        "SELECT category_id, name, enabled, live_feed_type, updated_at FROM categories ORDER BY category_id ASC"
      )
      .toArray();
    return rows.map((row) => ({
      category_id: Number(row.category_id),
      name: row.name || "",
      enabled: Number(row.enabled || 0) === 1,
      live_feed_type: Number(row.live_feed_type || 0),
      updated_at: row.updated_at || "",
    }));
  }

  getLatestItemsByCategory(limit) {
    // Get enabled live-feed categories with their full info (for admin)
    const categoryRows = this.sql
      .exec(
        "SELECT category_id, name, enabled, live_feed_type FROM categories WHERE live_feed_type != 0 AND enabled = 1 ORDER BY category_id ASC"
      )
      .toArray();
    const categories = [];

    for (const row of categoryRows) {
      const categoryId = Number(row.category_id);
      const itemRows = this.sql
        .exec(
          "SELECT seq, category_id, title, ts, impact, payload_json FROM items WHERE category_id = ? ORDER BY seq DESC LIMIT ?",
          categoryId,
          limit
        )
        .toArray();
      const items = itemRows
        .map((item) => this.serializeItemRow(item))
        .reverse();
      categories.push({
        category_id: categoryId,
        name: row.name || "",
        enabled: Number(row.enabled || 0) === 1,
        live_feed_type: Number(row.live_feed_type || 0),
        items
      });
    }

    return categories;
  }

  getOlderItems(categoryId, beforeSeq, limit) {
    const rows = this.sql
      .exec(
        "SELECT seq, category_id, title, ts, impact, payload_json FROM items WHERE category_id = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
        categoryId,
        beforeSeq,
        limit
      )
      .toArray();
    return rows
      .map((row) => this.serializeItemRow(row))
      .reverse();
  }

  listItems(categoryId, limit) {
    const rows = this.sql
      .exec(
        "SELECT seq, category_id, title, ts, impact, payload_json FROM items WHERE category_id = ? ORDER BY seq DESC LIMIT ?",
        categoryId,
        limit
      )
      .toArray();
    return rows.map((row) => this.serializeItemRow(row));
  }

  pruneCategory(categoryId) {
    const maxItems = this.getMaxItemsPerCategory();
    const countRow = this.sql
      .exec("SELECT COUNT(*) AS total FROM items WHERE category_id = ?", categoryId)
      .one();
    const total = Number(countRow?.total || 0);
    const excess = total - maxItems;
    if (excess <= 0) return;

    this.sql.exec(
      "DELETE FROM items WHERE id IN (SELECT id FROM items WHERE category_id = ? ORDER BY seq ASC LIMIT ?)",
      categoryId,
      excess
    );
  }

  publishItem(data) {
    const categoryId = this.parseCategoryId(data?.category_id);
    if (!categoryId) {
      return { ok: false, error: "category_id must be a positive integer", status: 400 };
    }
    const category = this.getCategoryState(categoryId);
    if (!category) {
      return { ok: false, error: "Category not found in live-feed DO state", status: 404 };
    }
    if (!category.enabled || category.live_feed_type === 0) {
      return { ok: false, error: "Category is disabled for live feed", status: 400 };
    }

    const title = typeof data?.title === "string" ? data.title.trim() : "";
    if (!title) {
      return { ok: false, error: "title is required", status: 400 };
    }

    const impact = this.normalizeImpact(data?.impact);
    const timestamp = this.normalizeTimestamp(data?.timestamp);
    const payload =
      data?.payload && typeof data.payload === "object" && !Array.isArray(data.payload)
        ? data.payload
        : null;

    const seqRow = this.sql
      .exec(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM items WHERE category_id = ?",
        categoryId
      )
      .one();
    const nextSeq = Number(seqRow?.next_seq || 1);

    this.sql.exec(
      "INSERT INTO items (seq, category_id, title, ts, impact, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
      nextSeq,
      categoryId,
      title,
      timestamp,
      impact,
      payload ? JSON.stringify(payload) : null
    );

    this.pruneCategory(categoryId);

    const item = {
      seq: nextSeq,
      category_id: categoryId,
      title,
      timestamp,
      impact,
      payload,
    };
    this.broadcast({ type: "item", item });
    return { ok: true, item };
  }

  sendJSON(socket, payload) {
    try {
      socket.send(JSON.stringify(payload));
    } catch {
      // socket might already be closed.
    }
  }

  sendBootstrap(socket) {
    const categories = this.getLatestItemsByCategory(this.getInitItems());
    this.sendJSON(socket, {
      type: "bootstrap",
      categories,
      live_users: this.state.getWebSockets().length,
      server_time: new Date().toISOString(),
    });
  }

  broadcast(payload) {
    const sockets = this.state.getWebSockets();
    const message = JSON.stringify({ ...payload, live_users: sockets.length });
    let sent = 0;
    for (const socket of sockets) {
      try {
        socket.send(message);
        sent++;
      } catch {
        try {
          socket.close(1011, "Send failed");
        } catch {
          // best effort close.
        }
      }
    }
  }

  async fetch(request) {
    await this.ensureInitialized();

    const url = new URL(request.url);
    const path = normalizePath(url.pathname);

    // WebSocket connect
    if (path === "/connect") {
      if (request.method !== "GET") {
        return doJSON({ error: "GET required" }, 405);
      }
      const upgrade = request.headers.get("Upgrade") || "";
      if (upgrade.toLowerCase() !== "websocket") {
        return doJSON({ error: "WebSocket upgrade required" }, 426);
      }

      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.state.acceptWebSocket(server);
      this.sendJSON(server, { type: "connected" });
      this.sendBootstrap(server);
      return new Response(null, { status: 101, webSocket: client });
    }

    if (path === "/admin/publish") {
      if (request.method !== "POST") {
        return doJSON({ error: "POST required" }, 405);
      }

      let data = null;
      try {
        data = await request.json();
      } catch {
        return doJSON({ error: "Invalid JSON body" }, 400);
      }

      const result = this.publishItem(data);
      if (!result.ok) {
        return doJSON({ error: result.error }, result.status);
      }
      return doJSON(result.item, 201);
    }

    if (path === "/admin/purge-category") {
      if (request.method !== "POST") {
        return doJSON({ error: "POST required" }, 405);
      }

      let data = null;
      try {
        data = await request.json();
      } catch {
        return doJSON({ error: "Invalid JSON body" }, 400);
      }

      const categoryId = this.parseCategoryId(data?.category_id);
      if (!categoryId) {
        return doJSON({ error: "category_id must be a positive integer" }, 400);
      }

      this.sql.exec("DELETE FROM items WHERE category_id = ?", categoryId);
      const changed = this.sql.exec("SELECT changes() AS total").one();
      return doJSON({ category_id: categoryId, deleted: Number(changed?.total || 0) }, 200);
    }

    if (path === "/admin/categories/list") {
      if (request.method !== "GET") {
        return doJSON({ error: "GET required" }, 405);
      }
      return doJSON({ categories: this.listCategories() }, 200);
    }

    if (path === "/admin/categories/upsert") {
      if (request.method !== "POST") {
        return doJSON({ error: "POST required" }, 405);
      }
      let data = null;
      try {
        data = await request.json();
      } catch {
        return doJSON({ error: "Invalid JSON body" }, 400);
      }
      const result = this.upsertCategory(data);
      if (!result.ok) {
        return doJSON({ error: result.error }, result.status);
      }
      return doJSON(result.category, 200);
    }

    if (path === "/admin/categories/delete") {
      if (request.method !== "POST") {
        return doJSON({ error: "POST required" }, 405);
      }
      let data = null;
      try {
        data = await request.json();
      } catch {
        return doJSON({ error: "Invalid JSON body" }, 400);
      }
      const categoryId = this.parseCategoryId(data?.category_id);
      if (!categoryId) {
        return doJSON({ error: "category_id must be a positive integer" }, 400);
      }
      const deleted = this.deleteCategory(categoryId);
      return doJSON({ category_id: categoryId, ...deleted }, 200);
    }

    if (path === "/admin/items/list") {
      if (request.method !== "GET") {
        return doJSON({ error: "GET required" }, 405);
      }
      const categoryId = this.parseCategoryId(url.searchParams.get("category_id"));
      if (!categoryId) {
        return doJSON({ error: "category_id is required" }, 400);
      }
      const limit = parseIntSafe(url.searchParams.get("limit"), this.getInitItems(), 1, this.getMaxItemsPerCategory());
      return doJSON({ category_id: categoryId, items: this.listItems(categoryId, limit) }, 200);
    }

    return doJSON({ error: "Not found" }, 404);
  }

  async webSocketMessage(socket, message) {
    await this.ensureInitialized();

    let text = "";
    if (typeof message === "string") {
      text = message;
    } else if (message instanceof ArrayBuffer) {
      text = new TextDecoder().decode(message);
    } else {
      text = String(message ?? "");
    }

    let payload = null;
    try {
      payload = JSON.parse(text);
    } catch {
      this.sendJSON(socket, { type: "error", error: "Invalid JSON message" });
      return;
    }

    if (payload?.type === "ping") {
      this.sendJSON(socket, { type: "pong" });
      return;
    }

    if (payload?.type !== "load_older") {
      this.sendJSON(socket, { type: "error", error: "Unsupported message type" });
      return;
    }

    const categoryId = this.parseCategoryId(payload?.category_id);
    const beforeSeq = this.parseBeforeSeq(payload?.before_seq);
    if (!categoryId || !beforeSeq) {
      this.sendJSON(socket, { type: "error", error: "category_id and before_seq are required" });
      return;
    }

    const limit = parseIntSafe(
      payload?.limit,
      this.getMaxLoadOlder(),
      1,
      this.getMaxLoadOlder()
    );
    const items = this.getOlderItems(categoryId, beforeSeq, limit);
    this.sendJSON(socket, { type: "older_items", category_id: categoryId, items });
  }

  webSocketClose() {
    // No cleanup needed for global fanout mode.
  }

  webSocketError(socket) {
    try {
      socket.close(1011, "Socket error");
    } catch {
      // best effort close.
    }
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = normalizePath(url.pathname);

    if (!path.startsWith("/api/v1/")) {
      return fetch(request);
    }

    if (request.method === "OPTIONS") {
      return handlePreflight(env);
    }

    if (path === "/api/v1/live-feed") {
      return handleLiveFeedSocket(request, env);
    }

    if (path === "/api/v1/live-feed/admin/items") {
      return handleLiveFeedPublish(request, env);
    }

    if (path === "/api/v1/live-feed/admin/purge-category") {
      return handleLiveFeedPurgeCategory(request, env);
    }

    if (path === "/api/v1/live-feed/admin/categories/list") {
      return handleLiveFeedCategoryList(request, env);
    }

    if (path === "/api/v1/live-feed/admin/categories/upsert") {
      return handleLiveFeedCategoryUpsert(request, env);
    }

    if (path === "/api/v1/live-feed/admin/categories/delete") {
      return handleLiveFeedCategoryDelete(request, env);
    }

    if (path === "/api/v1/live-feed/admin/items/list") {
      return handleLiveFeedItemsList(request, env);
    }

    if (path === "/api/v1/get-token") {
      return handleGetToken(request, env);
    }

    if (path === "/api/v1/warm") {
      return handleWarm(request, env);
    }

    if (request.method !== "GET") {
      return proxyToOrigin(request, env);
    }

    const authHeader = request.headers.get("Authorization");
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      return corsJSON({ error: "Authorization: Bearer <token> required" }, 401, env);
    }

    const authResult = await verifyToken(authHeader.slice(7), env);
    if (!authResult.valid) {
      return corsJSON({ error: authResult.error }, 401, env);
    }

    const microcache = await caches.open(MICROCACHE_NAME);
    const cacheKey = new Request(url.toString(), { method: "GET" });
    let response = await microcache.match(cacheKey);

    if (response) {
      _counts.WORKER++;
      maybeFlushAnalytics(env);
      const r = new Response(response.body, response);
      r.headers.set("X-Cache", X_CACHE_WORKER);
      for (const [k, v] of Object.entries(getCORSHeaders(env))) r.headers.set(k, v);
      return r;
    }

    const cdnTtl = getCDNTTL(url);
    response = await fetchOriginGET(url, env, cdnTtl);
    if (!response.ok) return addCORS(response, env);

    const cfCacheStatus = response.headers.get("CF-Cache-Status");
    const layer = isCDNHitStatus(cfCacheStatus) ? X_CACHE_CDN : X_CACHE_ORIGIN;
    if (layer === X_CACHE_CDN) {
      _counts.CDN++;
    } else {
      _counts.ORIGIN++;
    }

    const toClient = new Response(response.body, response);
    toClient.headers.set("Cache-Control", `s-maxage=${WORKER_CACHE_TTL}, stale-while-revalidate=${WORKER_SWR}`);
    toClient.headers.set("X-Cache", layer);
    for (const [k, v] of Object.entries(getCORSHeaders(env))) toClient.headers.set(k, v);
    ctx.waitUntil(
      microcache.put(cacheKey, toClient.clone()).then(() => maybeFlushAnalytics(env))
    );
    return toClient;
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(warmCache(env, "cron"));
  },
};
