const DEFAULT_CACHE_TTL = 1800;
const TOKEN_EXPIRY = 900;

// --- JWT (HMAC-SHA256) ---

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
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    usage
  );
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

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
};

function corsJSON(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...CORS_HEADERS },
  });
}

function addCORS(response) {
  const resp = new Response(response.body, response);
  for (const [k, v] of Object.entries(CORS_HEADERS)) resp.headers.set(k, v);
  return resp;
}

function handlePreflight() {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

// --- Origin ---

async function fetchOriginGET(url, env) {
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
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.set("X-Origin-Secret", env.ORIGIN_PATH_SECRET);

  const init = { method: request.method, headers };
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
  }

  const response = await fetch(`${env.ORIGIN_BASE}${url.pathname}${url.search}`, init);
  return addCORS(response);
}

// --- Token endpoint ---

async function handleGetToken(request, env) {
  if (request.method !== "POST") {
    return corsJSON({ error: "POST required" }, 405);
  }

  const appSecret = request.headers.get("X-App-Secret") || "";
  if (!appSecret || appSecret !== env.APP_SECRET) {
    return corsJSON({ error: "Forbidden" }, 403);
  }

  const token = await generateToken(env);
  return corsJSON({ token, token_type: "Bearer", expires_in: TOKEN_EXPIRY });
}

// --- Main Worker ---

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const cacheTTL = parseInt(env.CACHE_TTL) || DEFAULT_CACHE_TTL;

    // Only intercept /api/v1/ — everything else passes through
    if (!url.pathname.startsWith("/api/v1/")) {
      return fetch(request);
    }

    if (request.method === "OPTIONS") {
      return handlePreflight();
    }

    // Token endpoint (no JWT needed)
    const tokenPath = url.pathname.replace(/\/+$/, "");
    if (tokenPath === "/api/v1/get-token") {
      return handleGetToken(request, env);
    }

    // Non-GET → proxy to origin (client handles their own DRF auth)
    if (request.method !== "GET") {
      return proxyToOrigin(request, env);
    }

    // GET → require Worker JWT
    const authHeader = request.headers.get("Authorization");
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      return corsJSON({ error: "Authorization: Bearer <token> required" }, 401);
    }

    const authResult = await verifyToken(authHeader.slice(7), env);
    if (!authResult.valid) {
      return corsJSON({ error: authResult.error }, 401);
    }

    // Edge cache lookup (key includes query params for pagination)
    const cache = caches.default;
    const cacheKey = new Request(url.toString(), { method: "GET" });
    let response = await cache.match(cacheKey);

    if (response) {
      response = new Response(response.body, response);
      response.headers.set("X-Cache", "HIT");
      return addCORS(response);
    }

    // Cache miss → fetch from origin with DRF token
    response = await fetchOriginGET(url, env);
    if (!response.ok) return addCORS(response);

    response = new Response(response.body, response);
    response.headers.set("Cache-Control", `s-maxage=${cacheTTL}, must-revalidate`);
    response.headers.set("X-Cache", "MISS");
    ctx.waitUntil(cache.put(cacheKey, response.clone()));

    return addCORS(response);
  },

  // Cron: pre-warm popular endpoints
  async scheduled(event, env, ctx) {
    const cache = caches.default;
    const cacheTTL = parseInt(env.CACHE_TTL) || DEFAULT_CACHE_TTL;
    const workerDomain = env.WORKER_DOMAIN || "glimpseapp.net";

    const endpoints = [
      "/api/v1/news/",
      "/api/v1/news/?page=1&limit=10",
      "/api/v1/videos/",
      "/api/v1/videos/?page=1&limit=10",
    ];

    await Promise.allSettled(
      endpoints.map(async (endpoint) => {
        try {
          const response = await fetch(`${env.ORIGIN_BASE}${endpoint}`, {
            headers: {
              Authorization: `Token ${env.DRF_TOKEN}`,
              "X-Origin-Secret": env.ORIGIN_PATH_SECRET,
              Accept: "application/json",
            },
          });

          if (response.ok) {
            const cached = new Response(response.body, response);
            cached.headers.set("Cache-Control", `s-maxage=${cacheTTL}, must-revalidate`);
            cached.headers.set("X-Cache", "PREWARMED");
            await cache.put(new Request(`https://${workerDomain}${endpoint}`), cached);
          }
        } catch (e) {
          console.error(`Pre-warm failed for ${endpoint}:`, e.message);
        }
      })
    );
  },
};
