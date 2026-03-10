const WORKER_CACHE_TTL = 120;
const WORKER_SWR = 15;
const CDN_CACHE_TTL = 1800;
const METADATA_CDN_TTL = 86400;
const NEWS_ALL_CDN_TTL = 86400;
// Dedicated Worker microcache name.
const MICROCACHE_NAME = "worker-microcache";
const TOKEN_EXPIRY = 7200;

const _counts = { WORKER: 0, CDN: 0, ORIGIN: 0 };
let _lastFlush = Date.now();
const ANALYTICS_FLUSH_INTERVAL = 60_000;

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

const WARM_ENDPOINTS = [
  "/api/v1/news/?page=1&limit=50",
  "/api/v1/news/?page=2&limit=50",
  "/api/v1/videos/?page=1&limit=50",
  "/api/v1/videos/?page=2&limit=50",
];

async function warmCache(env) {
  const microcache = await caches.open(MICROCACHE_NAME);
  const workerDomain = env.WORKER_DOMAIN || "glimpseapp.net";
  const results = [];

  await Promise.allSettled(
    WARM_ENDPOINTS.map(async (endpoint) => {
      try {
        const publicUrl = `https://${workerDomain}${endpoint}`;
        const endpointUrl = new URL(publicUrl);
        const cdnTtl = getCDNTTL(endpointUrl);
        const originResp = await fetchOriginGET(endpointUrl, env, cdnTtl);

        if (originResp.ok) {
          const microEntry = new Response(originResp.body, originResp);
          microEntry.headers.set("Cache-Control", `s-maxage=${WORKER_CACHE_TTL}, stale-while-revalidate=${WORKER_SWR}`);
          microEntry.headers.set("X-Cache", "HIT");

          await microcache.put(new Request(publicUrl), microEntry);

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

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (!url.pathname.startsWith("/api/v1/")) {
      return fetch(request);
    }

    if (request.method === "OPTIONS") {
      return handlePreflight(env);
    }

    const tokenPath = url.pathname.replace(/\/+$/, "");
    if (tokenPath === "/api/v1/get-token") {
      return handleGetToken(request, env);
    }

    if (tokenPath === "/api/v1/warm") {
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
      r.headers.set("X-Cache", "HIT");
      for (const [k, v] of Object.entries(getCORSHeaders(env))) r.headers.set(k, v);
      return r;
    }

    const cdnTtl = getCDNTTL(url);
    response = await fetchOriginGET(url, env, cdnTtl);
    if (!response.ok) return addCORS(response, env);

    const cfCacheStatus = response.headers.get("CF-Cache-Status");
    const layer = isCDNHitStatus(cfCacheStatus) ? "HIT" : "MISS";
    if (layer === "HIT") {
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
};
