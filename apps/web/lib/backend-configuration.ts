import { getVercelOidcToken } from "@vercel/oidc";
import type { TalliApiClientOptions } from "@talli/talli-api-client";
import { BackendTransportError, createPreviewBackendFetch } from "./protected-backend-fetch.ts";

export type BackendConfigurationErrorCode =
  | "BACKEND_URL_MISSING"
  | "BACKEND_URL_INVALID"
  | "BACKEND_URL_INSECURE";

export class BackendConfigurationError extends Error {
  readonly code: BackendConfigurationErrorCode;

  constructor(code: BackendConfigurationErrorCode) {
    super(code);
    this.name = "BackendConfigurationError";
    this.code = code;
  }
}

export function backendBaseUrl(): string {
  const raw = process.env.TALLI_BACKEND_URL;
  if (!raw) {
    throw new BackendConfigurationError("BACKEND_URL_MISSING");
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new BackendConfigurationError("BACKEND_URL_INVALID");
  }
  if (
    !["http:", "https:"].includes(url.protocol)
    || url.username
    || url.password
    || (url.pathname !== "/" && url.pathname !== "")
    || url.search
    || url.hash
  ) {
    throw new BackendConfigurationError("BACKEND_URL_INVALID");
  }
  const hostname = url.hostname.replace(/^\[|\]$/gu, "");
  const isLoopback = ["127.0.0.1", "localhost", "::1"].includes(hostname);
  if (url.protocol !== "https:" && !isLoopback) {
    throw new BackendConfigurationError("BACKEND_URL_INSECURE");
  }
  return url.origin;
}

/** Platform transport configuration; feature transports retain their own auth. */
export function backendClientOptions(
  supplied?: Pick<TalliApiClientOptions, "baseUrl" | "fetch">,
): Pick<TalliApiClientOptions, "baseUrl" | "fetch"> {
  const options = supplied ?? { baseUrl: backendBaseUrl() };
  if (process.env.VERCEL_ENV !== "preview") return options;
  const configured = backendBaseUrl();
  let target: URL;
  try {
    target = new URL(options.baseUrl);
  } catch {
    throw new BackendTransportError("BACKEND_ORIGIN_INVALID");
  }
  if (target.origin !== configured || target.username || target.password
    || target.pathname !== "/" || target.search || target.hash) {
    throw new BackendTransportError("BACKEND_REQUEST_OUTSIDE_ORIGIN");
  }
  return {
    baseUrl: configured,
    fetch: createPreviewBackendFetch({
      backendOrigin: configured,
      tokenProvider: getVercelOidcToken,
      fetchImplementation: options.fetch ?? globalThis.fetch,
    }),
  };
}
