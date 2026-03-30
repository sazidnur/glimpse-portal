const WORKER_CACHE_TTL = 600;
const WORKER_SWR = 600;
const CDN_CACHE_TTL = 1800-60;
const METADATA_CDN_TTL = 1800-60;
const NEWS_ALL_CDN_TTL = 86400-60;
// Dedicated Worker microcache name.
const MICROCACHE_NAME = "worker-microcache";
const TOKEN_EXPIRY = 7200;
const X_CACHE_WORKER = "0";
const X_CACHE_CDN = "1";
const X_CACHE_ORIGIN = "2";
const LIVE_FEED_DEFAULT_ADMIN_HUB = "europe";
const LIVE_FEED_HUBS = {
  apac: { name: "hub-v3-apac", locationHint: "apac" },
  europe: { name: "hub-v4-europe", locationHint: "weur" },
  "middle-east": { name: "hub-v3-middle-east", locationHint: "me" },
  americas: { name: "hub-v3-americas", locationHint: "enam" },
};

const LIVE_FEED_HUB_ALIASES = {
  apac: "apac",
  asia: "apac",
  australia: "apac",
  oceania: "apac",
  eu: "europe",
  europe: "europe",
  weu: "europe",
  "west-europe": "europe",
  "eu-west": "europe",
  "middle-east": "middle-east",
  middleeast: "middle-east",
  me: "middle-east",
  gulf: "middle-east",
  americas: "americas",
  america: "americas",
  "west-america": "americas",
  "usa-canada": "americas",
  us: "americas",
  usa: "americas",
  canada: "americas",
  na: "americas",
  sam: "americas",
};

const LIVE_FEED_APAC_COUNTRIES = new Set([
  "AF",
  "AU",
  "BD",
  "BN",
  "BT",
  "CN",
  "FJ",
  "HK",
  "ID",
  "IN",
  "JP",
  "KH",
  "KP",
  "KR",
  "KZ",
  "LA",
  "LK",
  "MM",
  "MN",
  "MO",
  "MV",
  "MY",
  "NP",
  "NZ",
  "PG",
  "PH",
  "PK",
  "SB",
  "SG",
  "TH",
  "TJ",
  "TL",
  "TM",
  "TW",
  "UZ",
  "VN",
  "VU",
]);

const LIVE_FEED_MIDDLE_EAST_COUNTRIES = new Set([
  "AE",
  "BH",
  "CY",
  "EG",
  "IL",
  "IQ",
  "IR",
  "JO",
  "KW",
  "LB",
  "OM",
  "PS",
  "QA",
  "SA",
  "SY",
  "TR",
  "YE",
]);

const LIVE_FEED_EUROPE_COUNTRIES = new Set([
  "AD",
  "AL",
  "AM",
  "AT",
  "AZ",
  "BA",
  "BE",
  "BG",
  "BY",
  "CH",
  "CZ",
  "DE",
  "DK",
  "EE",
  "ES",
  "FI",
  "FO",
  "FR",
  "GB",
  "GE",
  "GG",
  "GI",
  "GR",
  "HR",
  "HU",
  "IE",
  "IM",
  "IS",
  "IT",
  "JE",
  "LI",
  "LT",
  "LU",
  "LV",
  "MC",
  "MD",
  "ME",
  "MK",
  "MT",
  "NL",
  "NO",
  "PL",
  "PT",
  "RO",
  "RS",
  "RU",
  "SE",
  "SI",
  "SK",
  "SM",
  "UA",
  "VA",
  "XK",
]);

const _counts = { WORKER: 0, CDN: 0, ORIGIN: 0 };
let _lastFlush = Date.now();
const ANALYTICS_FLUSH_INTERVAL = 60_000;


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

function resolveLiveFeedHubKey(value) {
  if (!value) return null;
  const key = String(value).trim().toLowerCase();
  if (!key) return null;
  const mapped = LIVE_FEED_HUB_ALIASES[key] || key;
  return LIVE_FEED_HUBS[mapped] ? mapped : null;
}

function getCountryCode(request) {
  const cfCountry = typeof request?.cf?.country === "string" ? request.cf.country : "";
  const headerCountry = request.headers.get("CF-IPCountry") || "";
  const code = (cfCountry || headerCountry).trim().toUpperCase();
  return code.length === 2 ? code : "";
}

function getAutoUserHubByCountry(countryCode) {
  if (LIVE_FEED_APAC_COUNTRIES.has(countryCode)) return "apac";
  if (LIVE_FEED_MIDDLE_EAST_COUNTRIES.has(countryCode)) return "middle-east";
  if (LIVE_FEED_EUROPE_COUNTRIES.has(countryCode)) return "europe";

  return "americas";
}

function resolveUserHub(request) {
  const url = new URL(request.url);
  const explicitHub =
    resolveLiveFeedHubKey(url.searchParams.get("hub")) ||
    resolveLiveFeedHubKey(request.headers.get("X-Live-Feed-Hub"));
  if (explicitHub) return explicitHub;
  return getAutoUserHubByCountry(getCountryCode(request));
}

function resolveAdminHub(request) {
  return resolveLiveFeedHubKey(request.headers.get("X-Live-Feed-Hub")) || LIVE_FEED_DEFAULT_ADMIN_HUB;
}

function getLiveFeedStub(env, hubKey) {
  const namespace = env.GLIMPSE_LIVE_FEED;
  if (!namespace) {
    throw new Error("GLIMPSE_LIVE_FEED binding is missing");
  }
  const hub = LIVE_FEED_HUBS[hubKey];
  if (!hub) {
    throw new Error(`Unsupported hub: ${hubKey}`);
  }
  const id = namespace.idFromName(hub.name);
  return namespace.get(id, { locationHint: hub.locationHint });
}

function requireWebSocketUpgrade(request, env) {
  if (request.method !== "GET") {
    return corsJSON({ error: "GET required" }, 405, env);
  }
  const upgrade = request.headers.get("Upgrade") || "";
  if (upgrade.toLowerCase() !== "websocket") {
    return corsJSON({ error: "WebSocket upgrade required" }, 426, env);
  }
  return null;
}

function parsePositiveInt(value) {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isInteger(parsed) && parsed > 0) return parsed;
  }
  return null;
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validateSnapshotShape(snapshot) {
  if (!isPlainObject(snapshot)) return "snapshot must be a JSON object";
  if (snapshot.type !== "snapshot") return "snapshot.type must be 'snapshot'";
  if (!isPlainObject(snapshot.category)) return "snapshot.category must be an object";

  const entries = Object.entries(snapshot.category);
  if (entries.length === 0) return "snapshot.category must contain at least one category id";

  for (const [categoryId, rawItems] of entries) {
    if (!parsePositiveInt(categoryId)) return "snapshot.category keys must be positive integer ids";

    const items = Array.isArray(rawItems) ? rawItems : [rawItems];
    if (items.length === 0) return `snapshot.category.${categoryId} must contain at least one item`;

    for (const item of items) {
      if (!isPlainObject(item)) return `snapshot.category.${categoryId} items must be objects`;
      if (!parsePositiveInt(item.seq_id)) return `snapshot.category.${categoryId} item.seq_id must be a positive integer`;
      if (typeof item.title !== "string" || !item.title.trim()) {
        return `snapshot.category.${categoryId} item.title is required`;
      }
    }
  }

  return null;
}

function validatePublishItemShape(item) {
  if (!isPlainObject(item)) return "item must be a JSON object";
  if (item.type !== "message") return "item.type must be 'message'";
  if (!parsePositiveInt(item.category_id)) return "item.category_id must be a positive integer";
  if (!parsePositiveInt(item.sequence_id)) return "item.sequence_id must be a positive integer";
  if (typeof item.title !== "string" || !item.title.trim()) return "item.title is required";
  return null;
}
function getUserJWT(request) {
  const authHeader = request.headers.get("Authorization") || "";
  if (!authHeader.startsWith("Bearer ")) return "";
  return authHeader.slice(7).trim();
}

function secureStringEquals(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const aBytes = new TextEncoder().encode(a);
  const bBytes = new TextEncoder().encode(b);
  if (aBytes.length !== bBytes.length) return false;
  let diff = 0;
  for (let i = 0; i < aBytes.length; i++) {
    diff |= aBytes[i] ^ bBytes[i];
  }
  return diff === 0;
}

function getAdminToken(request) {
  const authHeader = request.headers.get("Authorization") || "";
  if (!authHeader.startsWith("Token ")) return "";
  return authHeader.slice(6).trim();
}

async function requireUserSocketAuth(request, env) {
  const token = getUserJWT(request);
  if (!token) {
    return corsJSON({ error: "Authorization: Bearer <jwt> required" }, 401, env);
  }

  const authResult = await verifyToken(token, env);
  if (!authResult.valid) {
    return corsJSON({ error: authResult.error }, 401, env);
  }

  return null;
}

async function requireAdminSocketAuth(request, env) {
  const required = env.DRF_TOKEN || "";
  if (!required) {
    return corsJSON({ error: "DRF_TOKEN is missing" }, 503, env);
  }

  const incoming = getAdminToken(request);
  if (!incoming) {
    return corsJSON({ error: "Authorization: Token <drf_token> required" }, 401, env);
  }
  if (!secureStringEquals(incoming, required)) {
    return corsJSON({ error: "Forbidden" }, 403, env);
  }

  return null;
}
async function proxySocketToHub(request, env, role, hubKey) {
  const headers = new Headers(request.headers);
  headers.set("X-Live-Feed-Hub", hubKey);
  headers.set("X-Live-Feed-Role", role);

  const url = new URL("https://live-feed/connect");
  url.searchParams.set("hub", hubKey);
  url.searchParams.set("role", role);

  const stub = getLiveFeedStub(env, hubKey);
  return stub.fetch(
    new Request(url.toString(), {
      method: "GET",
      headers,
    })
  );
}

async function handleLiveFeedSocket(request, env) {
  const wsError = requireWebSocketUpgrade(request, env);
  if (wsError) return wsError;

  const authError = await requireUserSocketAuth(request, env);
  if (authError) return authError;

  try {
    return await proxySocketToHub(request, env, "user", resolveUserHub(request));
  } catch (error) {
    return corsJSON({ error: `Live feed unavailable: ${error.message}` }, 503, env);
  }
}

async function handleAdminLiveFeedSocket(request, env) {
  const wsError = requireWebSocketUpgrade(request, env);
  if (wsError) return wsError;

  const authError = await requireAdminSocketAuth(request, env);
  if (authError) return authError;

  try {
    return await proxySocketToHub(request, env, "admin", resolveAdminHub(request));
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

export class LiveFeedRegionalHubV3 {
  constructor(state) {
    this.state = state;
    this.sql = state.storage.sql;
    this._initialized = false;
    this.hub = null;
  }

  async ensureInitialized(hubKey = null) {
    const normalizedHub = resolveLiveFeedHubKey(hubKey) || null;

    if (this._initialized) {
      if (!this.hub && normalizedHub) this.hub = normalizedHub;
      if (!this.hub) this.hub = LIVE_FEED_DEFAULT_ADMIN_HUB;
      if (normalizedHub && this.hub !== normalizedHub) {
        throw new Error("Hub mismatch");
      }
      return;
    }

    await this.state.blockConcurrencyWhile(async () => {
      if (this._initialized) return;

      this.sql.exec(`
        CREATE TABLE IF NOT EXISTS fanout_state (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          payload_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
      `);
      this.sql.exec(
        `INSERT INTO fanout_state (id, payload_json, updated_at)
         VALUES (1, ?, ?)
         ON CONFLICT(id) DO NOTHING`,
        JSON.stringify({ initial_fanout: true }),
        new Date().toISOString()
      );

      const storedHubRaw = await this.state.storage.get("hub_key");
      const storedHub = resolveLiveFeedHubKey(storedHubRaw);
      const finalHub = storedHub || normalizedHub || LIVE_FEED_DEFAULT_ADMIN_HUB;

      this.hub = finalHub;
      if (!storedHub) {
        await this.state.storage.put("hub_key", finalHub);
      }

      this._initialized = true;
    });

    if (!this.hub) {
      this.hub = normalizedHub || LIVE_FEED_DEFAULT_ADMIN_HUB;
    }

    if (normalizedHub && this.hub !== normalizedHub) {
      throw new Error("Hub mismatch");
    }
  }

  getSocketRole(socket) {
    if (this.state.getWebSockets("admin").includes(socket)) return "admin";
    return "user";
  }

  getCounts() {
    const liveUsers = this.state.getWebSockets("user").length;
    const adminUsers = this.state.getWebSockets("admin").length;
    return {
      live_users: liveUsers,
      admin_users: adminUsers,
    };
  }

  sendJSON(socket, payload) {
    try {
      socket.send(JSON.stringify(payload));
    } catch {
      return;
    }
  }

  readFanout() {
    const row = this.sql.exec("SELECT payload_json FROM fanout_state WHERE id = 1").one();
    if (!row || !row.payload_json) return null;

    try {
      return JSON.parse(row.payload_json);
    } catch {
      return null;
    }
  }

  writeFanout(data) {
    const payloadJson = JSON.stringify(data);
    this.sql.exec(
      `INSERT INTO fanout_state (id, payload_json, updated_at)
       VALUES (1, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         payload_json = excluded.payload_json,
         updated_at = excluded.updated_at`,
      payloadJson,
      new Date().toISOString()
    );
  }

  sendConnected(socket) {
    const payload = {
      type: "connected",
      snapshot: this.readFanout(),
    };
    if (this.getSocketRole(socket) === "admin") {
      Object.assign(payload, {
        hub: this.hub,
        ...this.getCounts(),
      });
    }
    this.sendJSON(socket, payload);
  }

  sendHubUsers(socket) {
    this.sendJSON(socket, {
      type: "hub_users",
      hub: this.hub,
      ...this.getCounts(),
    });
  }

  broadcastPayload(payload) {
    const message = JSON.stringify(payload);
    const sockets = this.state.getWebSockets();
    for (const socket of sockets) {
      try {
        socket.send(message);
      } catch {
        try {
          socket.close(1011, "Send failed");
        } catch {
          continue;
        }
      }
    }
  }

  readTextMessage(message) {
    if (typeof message === "string") return message;
    if (message instanceof ArrayBuffer) {
      return new TextDecoder().decode(message);
    }
    if (ArrayBuffer.isView(message)) {
      const view = new Uint8Array(message.buffer, message.byteOffset, message.byteLength);
      return new TextDecoder().decode(view);
    }
    return String(message ?? "");
  }

  async fetch(request) {
    const url = new URL(request.url);
    const path = normalizePath(url.pathname);

    if (path !== "/connect") {
      return doJSON({ error: "Not found" }, 404);
    }

    if (request.method !== "GET") {
      return doJSON({ error: "GET required" }, 405);
    }

    const upgrade = request.headers.get("Upgrade") || "";
    if (upgrade.toLowerCase() !== "websocket") {
      return doJSON({ error: "WebSocket upgrade required" }, 426);
    }

    const role = (url.searchParams.get("role") || "user").toLowerCase() === "admin" ? "admin" : "user";
    const hubKey =
      resolveLiveFeedHubKey(url.searchParams.get("hub")) ||
      resolveLiveFeedHubKey(request.headers.get("X-Live-Feed-Hub")) ||
      LIVE_FEED_DEFAULT_ADMIN_HUB;

    await this.ensureInitialized(hubKey);

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    this.state.acceptWebSocket(server, [role]);
    this.sendConnected(server);

    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(socket, message) {
    await this.ensureInitialized(this.hub || LIVE_FEED_DEFAULT_ADMIN_HUB);

    if (this.getSocketRole(socket) !== "admin") {
      return;
    }

    let payload = null;
    try {
      payload = JSON.parse(this.readTextMessage(message));
    } catch {
      this.sendJSON(socket, { type: "error", error: "Invalid JSON message" });
      return;
    }

    const type = String(payload?.type || "").trim();

    if (type === "get_live_users") {
      this.sendHubUsers(socket);
      return;
    }

    if (type === "set_broadcast") {
      if (!Object.prototype.hasOwnProperty.call(payload, "snapshot")) {
        this.sendJSON(socket, { type: "error", error: "snapshot is required" });
        return;
      }

      const snapshotError = validateSnapshotShape(payload.snapshot);
      if (snapshotError) {
        this.sendJSON(socket, { type: "error", error: snapshotError });
        return;
      }

      try {
        this.writeFanout(payload.snapshot);
      } catch {
        this.sendJSON(socket, { type: "error", error: "Failed to save snapshot" });
        return;
      }

      this.broadcastPayload(payload.snapshot);
      this.sendJSON(socket, { type: "set_broadcast_ack", hub: this.hub, ...this.getCounts() });
      return;
    }

    if (type === "publish_item") {
      if (!Object.prototype.hasOwnProperty.call(payload, "item")) {
        this.sendJSON(socket, { type: "error", error: "item is required" });
        return;
      }

      const itemError = validatePublishItemShape(payload.item);
      if (itemError) {
        this.sendJSON(socket, { type: "error", error: itemError });
        return;
      }

      if (Object.prototype.hasOwnProperty.call(payload, "snapshot")) {
        const snapshotError = validateSnapshotShape(payload.snapshot);
        if (snapshotError) {
          this.sendJSON(socket, { type: "error", error: snapshotError });
          return;
        }

        try {
          this.writeFanout(payload.snapshot);
        } catch {
          this.sendJSON(socket, { type: "error", error: "Failed to save snapshot" });
          return;
        }
      }

      this.broadcastPayload(payload.item);
      this.sendJSON(socket, { type: "publish_item_ack", hub: this.hub, ...this.getCounts() });
      return;
    }

    this.sendJSON(socket, { type: "error", error: "Unsupported message type" });
  }

  webSocketClose() {
    return;
  }

  webSocketError(socket) {
    try {
      socket.close(1011, "Socket error");
    } catch {
      return;
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

    if (path === "/api/v1/admin/live-feed") {
      return handleAdminLiveFeedSocket(request, env);
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
