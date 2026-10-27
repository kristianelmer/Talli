export class BackendTransportError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = "BackendTransportError";
    this.code = code;
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

function refuse(code: string): never {
  throw new BackendTransportError(code);
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
    let token: string;
    try {
      token = await options.tokenProvider();
    } catch {
      return refuse("BACKEND_OIDC_TOKEN_UNAVAILABLE");
    }
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
      return refuse("BACKEND_FETCH_UNAVAILABLE");
    }
  };
}
