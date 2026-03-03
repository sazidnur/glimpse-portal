// Layer 1: Worker microcache per PoP (absorbs burst traffic)
const WORKER_CACHE_TTL = 120;    // 2 minutes
// Layer 2: CDN / Tiered cache (upper tier + edge)
const CDN_CACHE_TTL = 1800;      // 30 minutes — purge after hourly DB update
const TOKEN_EXPIRY = 7200;

// --- Analytics (Analytics Engine, free tier) ---
// One datapoint per flush interval instead of per request.
// Max usage: 144 datapoints/isolate/day at 10-min interval — well under 100k free limit.
// After 100k/day limit: writes drop silently, no error, no charge.
const _counts = { WORKER: 0, CDN: 0, ORIGIN: 0 };
let _lastFlush = Date.now();
const ANALYTICS_FLUSH_INTERVAL = 60_000; // 1 minute — 1,440 datapoints/isolate/day (well under 100k free limit)

// Called inside ctx.waitUntil — fully off the response critical path.
function maybeFlushAnalytics(env) {
  const now = Date.now();
  if (now - _lastFlush < ANALYTICS_FLUSH_INTERVAL) return;
  const total = _counts.WORKER + _counts.CDN + _counts.ORIGIN;
  if (total === 0) return;
  // doubles[0]=workerHits, doubles[1]=cdnHits, doubles[2]=originHits
  // Query via GraphQL: sum(double1)/sum(double2)/sum(double3) over any time range.
  env.ANALYTICS?.writeDataPoint({
    doubles: [_counts.WORKER, _counts.CDN, _counts.ORIGIN],
    indexes: ["cache"],
  });
  _counts.WORKER = 0;
  _counts.CDN = 0;
  _counts.ORIGIN = 0;
  _lastFlush = now;
}

// --- JWT (HMAC-SHA256) ---

// Cache imported CryptoKey objects so crypto.subtle.importKey()
// runs only once per isolate lifetime, not on every request.
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

// --- CORS ---
// Access-Control-Allow-Origin is intentionally open (*) because all GET requests
// require a short-lived Worker JWT — the JWT is the auth boundary, not the origin.
// To restrict to your app domain set env.ALLOWED_ORIGIN (e.g. https://glimpseapp.net);
// preflight and non-cached responses pick it up via addCORS / corsJSON.
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
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

// --- Origin ---

async function fetchOriginGET(url, env) {
  // Use cf options so Cloudflare populates the CDN tiered cache (upper tier + edge).
  // cacheKey is the public Worker URL so CDN and Worker microcache share the same key.
  const publicUrl = `https://${env.WORKER_DOMAIN}${url.pathname}${url.search}`;
  return fetch(`${env.ORIGIN_BASE}${url.pathname}${url.search}`, {
    method: "GET",
    headers: {
      Authorization: `Token ${env.DRF_TOKEN}`,
      "X-Origin-Secret": env.ORIGIN_PATH_SECRET,
      Accept: "application/json",
    },
    cf: {
      cacheEverything: true,
      cacheTtl: CDN_CACHE_TTL,
      cacheTtlByStatus: { "200-299": CDN_CACHE_TTL, "404": 60, "500-599": 0 },
      cacheKey: publicUrl,
    },
  });
}

async function proxyToOrigin(request, env) {
  const url = new URL(request.url);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.set("X-Origin-Secret", env.ORIGIN_PATH_SECRET);

  const init = { method: request.method, headers };
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
  }

  const response = await fetch(`${env.ORIGIN_BASE}${url.pathname}${url.search}`, init);
  return addCORS(response, env);
}

// --- Token endpoint ---

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

// --- Cache warming (shared by cron + /warm endpoint) ---

const WARM_ENDPOINTS = [
  "/api/v1/news/?page=1&limit=10",
  "/api/v1/news/?page=2&limit=10",
  "/api/v1/news/?page=3&limit=10",
  "/api/v1/videos/?page=1&limit=10",
  "/api/v1/videos/?page=2&limit=10",
];

async function warmCache(env) {
  const cache = caches.default;
  const workerDomain = env.WORKER_DOMAIN || "glimpseapp.net";
  const results = [];

  await Promise.allSettled(
    WARM_ENDPOINTS.map(async (endpoint) => {
      try {
        const publicUrl = `https://${workerDomain}${endpoint}`;

        // Fetch with cf options: populates CDN tiered cache (upper tier + edge PoPs).
        const response = await fetch(`${env.ORIGIN_BASE}${endpoint}`, {
          headers: {
            Authorization: `Token ${env.DRF_TOKEN}`,
            "X-Origin-Secret": env.ORIGIN_PATH_SECRET,
            Accept: "application/json",
          },
          cf: {
            cacheEverything: true,
            cacheTtl: CDN_CACHE_TTL,
            cacheTtlByStatus: { "200-299": CDN_CACHE_TTL, "404": 60, "500-599": 0 },
            cacheKey: publicUrl,
          },
        });

        if (response.ok) {
          // Also seed the local Worker microcache so the first real request is instant.
          const microcached = new Response(response.body, response);
          microcached.headers.set("Cache-Control", `s-maxage=${WORKER_CACHE_TTL}, stale-while-revalidate=15`);
          microcached.headers.set("X-Cache", "WARM");
          await cache.put(new Request(publicUrl), microcached);
          results.push({ endpoint, status: "ok" });
        } else {
          results.push({ endpoint, status: "error", code: response.status });
        }
      } catch (e) {
        console.error(`Warm failed for ${endpoint}:`, e.message);
        results.push({ endpoint, status: "error", error: e.message });
      }
    })
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

  const results = await warmCache(env);
  const ok = results.filter((r) => r.status === "ok").length;
  return corsJSON({ warmed: ok, total: WARM_ENDPOINTS.length, results }, 200, env);
}

// --- Main Worker ---

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Only intercept /api/v1/ — everything else passes through
    if (!url.pathname.startsWith("/api/v1/")) {
      return fetch(request);
    }

    if (request.method === "OPTIONS") {
      return handlePreflight(env);
    }

    // Token endpoint (no JWT needed)
    const tokenPath = url.pathname.replace(/\/+$/, "");
    if (tokenPath === "/api/v1/get-token") {
      return handleGetToken(request, env);
    }

    // Warm endpoint (no JWT needed, uses APP_SECRET)
    if (tokenPath === "/api/v1/warm") {
      return handleWarm(request, env);
    }

    // Non-GET → proxy to origin (client handles their own DRF auth)
    if (request.method !== "GET") {
      return proxyToOrigin(request, env);
    }

    // GET → require Worker JWT
    const authHeader = request.headers.get("Authorization");
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      return corsJSON({ error: "Authorization: Bearer <token> required" }, 401, env);
    }

    const authResult = await verifyToken(authHeader.slice(7), env);
    if (!authResult.valid) {
      return corsJSON({ error: authResult.error }, 401, env);
    }

    // Edge cache lookup (key includes query params for pagination)
    const cache = caches.default;
    const cacheKey = new Request(url.toString(), { method: "GET" });
    let response = await cache.match(cacheKey);

    if (response) {
      // Single Response copy: set X-Cache + CORS in one pass. maybeFlushAnalytics is
      // synchronous (timestamp check only), no Promise/waitUntil allocation needed.
      const r = new Response(response.body, response);
      r.headers.set("X-Cache", "WORKER");
      for (const [k, v] of Object.entries(getCORSHeaders(env))) r.headers.set(k, v);
      _counts.WORKER++;
      maybeFlushAnalytics(env);
      return r;
    }

    // Worker miss → fetch; cf options let Cloudflare check CDN/upper-tier before origin.
    response = await fetchOriginGET(url, env);
    if (!response.ok) return addCORS(response, env);

    // cf.cacheStatus: HIT/STALE/REVALIDATED/UPDATING all mean CDN served it (no origin hit).
    // MISS/EXPIRED/BYPASS/DYNAMIC mean origin was actually contacted.
    const cdnStatus = response.cf?.cacheStatus ?? "MISS";
    const layer = ["HIT", "STALE", "REVALIDATED", "UPDATING"].includes(cdnStatus) ? "CDN" : "ORIGIN";
    _counts[layer]++;

    // Single Response copy: set Cache-Control, X-Cache, and CORS in one pass.
    // stale-while-revalidate=15: Worker microcache may serve stale for 15s while Cloudflare
    // revalidates in background. Prevents thundering herd when 2-min microcache TTL expires.
    const microcached = new Response(response.body, response);
    microcached.headers.set("Cache-Control", `s-maxage=${WORKER_CACHE_TTL}, stale-while-revalidate=15`);
    microcached.headers.set("X-Cache", layer);
    for (const [k, v] of Object.entries(getCORSHeaders(env))) microcached.headers.set(k, v);
    ctx.waitUntil(
      cache.put(cacheKey, microcached.clone()).then(() => maybeFlushAnalytics(env))
    );
    return microcached;
  },
  // No cron: freshness is controlled by Cloudflare purge API after each hourly DB update.
  // Call the /api/v1/warm endpoint manually after purging if you need to pre-seed caches.
};
