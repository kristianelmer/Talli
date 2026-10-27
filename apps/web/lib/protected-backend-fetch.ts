export type BackendTransportErrorCode =
  | "BACKEND_ORIGIN_INVALID"
  | "BACKEND_SERVER_CONTEXT_REQUIRED"
  | "BACKEND_REQUEST_INVALID"
  | "BACKEND_REQUEST_OUTSIDE_ORIGIN"
  | "BACKEND_CALLER_PROTECTION_HEADER_DENIED"
  | "BACKEND_REQUEST_ABORTED"
  | "BACKEND_OIDC_TOKEN_UNAVAILABLE"
  | "BACKEND_FETCH_UNAVAILABLE";

export class BackendTransportError extends Error {
  readonly code: BackendTransportErrorCode;

  constructor(code: BackendTransportErrorCode) {
    super(code);
    this.name = "BackendTransportError";
    this.code = code;
  }
}

/** Keep attempted-request uncertainty recognizable to existing owner policies. */
export class BackendFetchError extends TypeError {
  readonly code = "BACKEND_FETCH_UNAVAILABLE";

  constructor() {
    super("BACKEND_FETCH_UNAVAILABLE");
  }
}

type PreviewFetchOptions = {
  backendOrigin: string;
  tokenProvider: () => Promise<string>;
  fetchImplementation: typeof globalThis.fetch;
};

const deniedHeaders = [
  "x-vercel-trusted-oidc-idp-token",
  "x-vercel-oidc-token",
  "x-vercel-protection-bypass",
];

function refuse(code: BackendTransportErrorCode): never {
  throw new BackendTransportError(code);
}

async function resolveToken(
  provider: PreviewFetchOptions["tokenProvider"], signal?: AbortSignal | null,
): Promise<string> {
  if (signal?.aborted) refuse("BACKEND_REQUEST_ABORTED");
  if (!signal) return provider();
  let onAbort: () => void = () => {};
  const cancelled = new Promise<never>((_resolve, reject) => {
    onAbort = () => reject(new BackendTransportError("BACKEND_REQUEST_ABORTED"));
    signal.addEventListener("abort", onAbort, { once: true });
  });
  try {
    return await Promise.race([Promise.resolve().then(() => {
      if (signal.aborted) refuse("BACKEND_REQUEST_ABORTED");
      return provider();
    }), cancelled]);
  } finally {
    signal.removeEventListener("abort", onAbort);
  }
}

/** Bind the platform token to one backend origin and resolve it per request. */
export function createPreviewBackendFetch(options: PreviewFetchOptions): typeof globalThis.fetch {
  let origin: URL;
  try {
    origin = new URL(options.backendOrigin);
  } catch {
    return refuse("BACKEND_ORIGIN_INVALID");
  }
  if (origin.origin !== options.backendOrigin || origin.protocol !== "https:") {
    refuse("BACKEND_ORIGIN_INVALID");
  }
  return async (input, init = {}) => {
    if (typeof window !== "undefined") refuse("BACKEND_SERVER_CONTEXT_REQUIRED");
    let target: URL;
    let headers: Headers;
    try {
      target = new URL(input instanceof Request ? input.url : String(input));
      headers = new Headers(input instanceof Request ? input.headers : undefined);
      for (const [key, value] of new Headers(init.headers)) headers.set(key, value);
    } catch {
      return refuse("BACKEND_REQUEST_INVALID");
    }
    if (target.origin !== origin.origin || target.username || target.password || target.hash) {
      refuse("BACKEND_REQUEST_OUTSIDE_ORIGIN");
    }
    if (deniedHeaders.some(header => headers.has(header))) {
      refuse("BACKEND_CALLER_PROTECTION_HEADER_DENIED");
    }
    const signal = init.signal === undefined && input instanceof Request ? input.signal : init.signal;
    let token: string;
    try {
      token = await resolveToken(options.tokenProvider, signal);
    } catch {
      if (signal?.aborted) refuse("BACKEND_REQUEST_ABORTED");
      return refuse("BACKEND_OIDC_TOKEN_UNAVAILABLE");
    }
    if (signal?.aborted) refuse("BACKEND_REQUEST_ABORTED");
    if (typeof token !== "string" || token.length > 32_768
      || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/u.test(token)) {
      refuse("BACKEND_OIDC_TOKEN_UNAVAILABLE");
    }
    headers.set("x-vercel-trusted-oidc-idp-token", token);
    try {
      // A platform header must never follow a redirect. Retry/reconciliation
      // remains with the owning command; one invocation makes one request.
      return await options.fetchImplementation(input, {
        ...init, headers, redirect: "error", cache: "no-store",
      });
    } catch {
      throw new BackendFetchError();
    }
  };
}
