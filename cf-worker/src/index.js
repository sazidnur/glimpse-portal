// ─── Timing constants ────────────────────────────────────────────────────────
// Layer 1: Worker named microcache per PoP (absorbs burst traffic)
const WORKER_CACHE_TTL = 120;    // seconds — microcache TTL
const WORKER_SWR       = 15;     // seconds — stale-while-revalidate for microcache
// Layer 2: Cloudflare CDN / Tiered cache (upper tier + edge)
const CDN_CACHE_TTL    = 1800;   // seconds — CDN TTL (override via cf.cacheTtl)
const CDN_SWR          = 120;    // seconds — stale-while-revalidate for CDN layer
const METADATA_CDN_TTL = 86400;  // 1 day — metadata changes infrequently
const METADATA_SWR     = 21600;  // 6 hours — stale-while-revalidate for metadata
const NEWS_ALL_CDN_TTL = 86400;  // 1 day — news?all changes infrequently
const NEWS_ALL_SWR     = 21600;  // 6 hours — stale-while-revalidate for news?all
// Worker microcache name — MUST be different from caches.default to avoid
// overwriting the CDN-cached entry at the same URL key.
const MICROCACHE_NAME  = "worker-microcache";
const TOKEN_EXPIRY     = 7200;   // seconds — JWT lifetime

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
  // Only methods the Worker actually handles. PUT/DELETE are not used and
  // listing them widens the CORS preflight surface unnecessarily.
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

// --- Origin ---

async function fetchOriginGET(url, env) {
  // Plain fetch — no cf.cacheEverything. Same-zone subrequests (Worker calling
  // its own zone) are never cached by cf.cacheEverything; CF treats them as
  // internal loopback and returns DYNAMIC. We manage both cache layers manually.
  return fetch(`${env.ORIGIN_BASE}${url.pathname}${url.search}`, {
    method: "GET",
    headers: {
      Authorization: `Token ${env.DRF_TOKEN}`,
      "X-Origin-Secret": env.ORIGIN_PATH_SECRET,
      Accept: "application/json",
    },
  });
}

async function proxyToOrigin(request, env) {
  const url = new URL(request.url);
  // Build a clean header set — only forward safe, known headers to origin.
  // Never blindly forward all client headers; that leaks any injected header
  // (e.g. X-Forwarded-For spoofing, internal secrets) straight through.
  const headers = new Headers({
    "X-Origin-Secret": env.ORIGIN_PATH_SECRET,
    "Content-Type": request.headers.get("Content-Type") || "application/json",
    Accept: request.headers.get("Accept") || "application/json",
  });
  // Forward the client's DRF token if present (needed for write operations).
  const clientAuth = request.headers.get("Authorization");
  if (clientAuth) headers.set("Authorization", clientAuth);

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
  const microcache = await caches.open(MICROCACHE_NAME);
  const workerDomain = env.WORKER_DOMAIN || "glimpseapp.net";
  const results = [];

  await Promise.allSettled(
    WARM_ENDPOINTS.map(async (endpoint) => {
      try {
        const publicUrl = `https://${workerDomain}${endpoint}`;

        const originResp = await fetch(`${env.ORIGIN_BASE}${endpoint}`, {
          headers: {
            Authorization: `Token ${env.DRF_TOKEN}`,
            "X-Origin-Secret": env.ORIGIN_PATH_SECRET,
            Accept: "application/json",
          },
        });

        if (originResp.ok) {
          // Build CDN and microcache entries from separate clones — a Response body
          // can only be consumed once, so we clone before reading either.
          const cdnEntry = new Response(originResp.clone().body, originResp);
          cdnEntry.headers.set("Cache-Control", `s-maxage=${CDN_CACHE_TTL}, stale-while-revalidate=${CDN_SWR}`);
          cdnEntry.headers.delete("Set-Cookie");
          cdnEntry.headers.delete("Vary");

          const microEntry = new Response(originResp.body, originResp);
          microEntry.headers.set("Cache-Control", `s-maxage=${WORKER_CACHE_TTL}, stale-while-revalidate=${WORKER_SWR}`);
          microEntry.headers.set("X-Cache", "HIT");

          // Write both layers in parallel — neither depends on the other.
          await Promise.all([
            caches.default.put(new Request(publicUrl), cdnEntry),
            microcache.put(new Request(publicUrl), microEntry),
          ]);

          results.push({ endpoint, status: "ok" });
        } else {
          results.push({ endpoint, status: "error", code: originResp.status });
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

    // ── L1: Worker named microcache (WORKER_CACHE_TTL) ──────────────────────────
    // caches.open(MICROCACHE_NAME) is isolated from caches.default so writing here
    // never evicts the L2 entry stored at the same URL key in caches.default.
    const microcache = await caches.open(MICROCACHE_NAME);
    const cacheKey = new Request(url.toString(), { method: "GET" });
    let response = await microcache.match(cacheKey);

    if (response) {
      _counts.WORKER++;
      maybeFlushAnalytics(env);
      const r = new Response(response.body, response);
      // X-Cache: HIT = served from cache (L1 Worker or L2 CDN), MISS = origin fetched.
      // Standard values — do not expose internal layer names (WORKER/CDN/ORIGIN)
      // as that leaks caching architecture details to clients.
      r.headers.set("X-Cache", "HIT");
      for (const [k, v] of Object.entries(getCORSHeaders(env))) r.headers.set(k, v);
      return r;
    }

    // ── L2: CDN layer via caches.default (CDN_CACHE_TTL) ────────────────────────
    // cf.cacheEverything does NOT work for same-zone subrequests — CF returns DYNAMIC
    // and never stores the entry. We manage caches.default explicitly instead.
    const workerDomain = env.WORKER_DOMAIN || "glimpseapp.net"; // fallback guards against misconfiguration
    const publicUrl = `https://${workerDomain}${url.pathname}${url.search}`;
    const cdnKey = new Request(publicUrl, { method: "GET" });
    response = await caches.default.match(cdnKey);
    let layer;

    if (response) {
      layer = "HIT";   // L2 CDN
      _counts.CDN++;
    } else {
      // ── L3: Origin ────────────────────────────────────────────────────────────
      const originResp = await fetchOriginGET(url, env);
      if (!originResp.ok) return addCORS(originResp, env);
      layer = "MISS";   // L3 Origin
      _counts.ORIGIN++;

      // Persist to CDN layer: store a clean copy in caches.default with CDN_CACHE_TTL.
      // Strip Set-Cookie and Vary so the entry is stored and reused for all callers.
      const cdnClone = originResp.clone();
      const cdnEntry = new Response(cdnClone.body, cdnClone);
      const pathNormalized = url.pathname.replace(/\/+$/, "");
      const isMetadata = pathNormalized === "/api/v1/metadata";
      const isNewsAll = pathNormalized === "/api/v1/news" && url.searchParams.get("all") === "true";
      let cdnTtl, cdnSwr;
      if (isMetadata) {
        cdnTtl = METADATA_CDN_TTL;
        cdnSwr = METADATA_SWR;
      } else if (isNewsAll) {
        cdnTtl = NEWS_ALL_CDN_TTL;
        cdnSwr = NEWS_ALL_SWR;
      } else {
        cdnTtl = CDN_CACHE_TTL;
        cdnSwr = CDN_SWR;
      }
      cdnEntry.headers.set("Cache-Control", `s-maxage=${cdnTtl}, stale-while-revalidate=${cdnSwr}`);
      cdnEntry.headers.delete("Set-Cookie");
      cdnEntry.headers.delete("Vary");
      ctx.waitUntil(caches.default.put(cdnKey, cdnEntry));

      response = originResp;
    }

    // ── Build microcache entry + client response ─────────────────────────────────
    const toClient = new Response(response.body, response);
    toClient.headers.set("Cache-Control", `s-maxage=${WORKER_CACHE_TTL}, stale-while-revalidate=${WORKER_SWR}`);
    toClient.headers.set("X-Cache", layer); // HIT (CDN) or MISS (origin)
    for (const [k, v] of Object.entries(getCORSHeaders(env))) toClient.headers.set(k, v);
    ctx.waitUntil(
      microcache.put(cacheKey, toClient.clone()).then(() => maybeFlushAnalytics(env))
    );
    return toClient;
  },
  // No cron: freshness is controlled by Cloudflare purge API after each hourly DB update.
  // Call the /api/v1/warm endpoint manually after purging if you need to pre-seed caches.
};
