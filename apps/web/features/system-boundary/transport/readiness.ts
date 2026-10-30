import { backendBaseUrl, backendClientOptions } from "#backend-configuration";

const MAX_RESPONSE_BYTES = 16_384;
const DEADLINE_MS = 3_000;
const CACHE_MS = 2_000;

type Configuration = { backend: string; auth: string; key: string };
type Options = {
  configuration?: () => Configuration;
  fetch?: typeof fetch;
  deadlineMs?: number;
  cacheMs?: number;
};

function configuredDependencies(): Configuration {
  const raw = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_ANON_KEY;
  if (!raw || raw !== raw.trim() || /\s/u.test(raw) || !key || key !== key.trim()
      || key.length > 8192 || /[\x00-\x20\x7f]/u.test(key)) throw new Error("Invalid readiness configuration");
  const auth = new URL(raw);
  if (!["https:", "http:"].includes(auth.protocol) || auth.username || auth.password
      || auth.pathname !== "/" || auth.search || auth.hash
      || (auth.protocol === "http:" && !["localhost", "127.0.0.1", "[::1]"].includes(auth.hostname))) {
    throw new Error("Invalid readiness configuration");
  }
  return { backend: backendBaseUrl(), auth: auth.origin, key };
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

async function boundedJson(fetcher: typeof fetch, url: string, signal: AbortSignal,
                           headers?: HeadersInit): Promise<unknown> {
  const response = await fetcher(url, { headers, signal, redirect: "error", cache: "no-store" });
  const reader = response.body?.getReader();
  try {
    if (response.status !== 200 || response.redirected
        || response.headers.get("content-type")?.split(";")[0].trim() !== "application/json" || !reader) {
      throw new Error("Unavailable dependency");
    }
    let length = 0;
    const chunks: Uint8Array[] = [];
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > MAX_RESPONSE_BYTES) throw new Error("Invalid dependency response");
      chunks.push(value);
    }
    const body = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
  } finally {
    // Also cancel unread error/redirect/oversized bodies; never expose contents.
    await reader?.cancel();
    reader?.releaseLock();
  }
}

export function createReadinessProbe(options: Options = {}): () => Promise<boolean> {
  let inFlight: Promise<boolean> | undefined;
  let expiresAt = 0;
  let result = false;
  const configuration = options.configuration ?? configuredDependencies;
  const fetcher = options.fetch ?? globalThis.fetch;
  return async () => {
    if (performance.now() < expiresAt) return result;
    if (inFlight) return inFlight;
    inFlight = (async () => {
      const controller = new AbortController();
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const config = configuration();
        const backendFetch = backendClientOptions({ baseUrl: config.backend, fetch: fetcher }).fetch ?? fetcher;
        const checks = Promise.all([
          boundedJson(backendFetch, config.backend + "/health/ready", controller.signal).then(
            (data) => record(data) && Object.keys(data).length === 1 && data.status === "ready",
          ),
          boundedJson(fetcher, config.auth + "/auth/v1/settings", controller.signal, { apikey: config.key }).then(
            (data) => record(data) && record(data.external) && typeof data.external.email === "boolean"
              && typeof data.disable_signup === "boolean",
          ),
        ]).then((values) => values.every(Boolean));
        const deadline = new Promise<boolean>((resolve) => {
          timer = setTimeout(() => { controller.abort(); resolve(false); }, options.deadlineMs ?? DEADLINE_MS);
        });
        result = await Promise.race([checks, deadline]);
      } catch {
        result = false;
      } finally {
        controller.abort();
        clearTimeout(timer);
        expiresAt = performance.now() + (options.cacheMs ?? CACHE_MS);
      }
      return result;
    })();
    try { return await inFlight; } finally { inFlight = undefined; }
  };
}

// Per process only. No request, cookie, user data, or upstream diagnostic is cached.
export const dependenciesReady = createReadinessProbe();
