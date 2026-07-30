import { createTalliApiClient } from "@talli/talli-api-client";

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
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    (url.pathname !== "/" && url.pathname !== "") ||
    url.search ||
    url.hash
  ) {
    throw new BackendConfigurationError("BACKEND_URL_INVALID");
  }
  const isLoopback = ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
  if (process.env.NODE_ENV === "production" && url.protocol !== "https:" && !isLoopback) {
    throw new BackendConfigurationError("BACKEND_URL_INSECURE");
  }
  return url.origin;
}

export async function loadSystemBoundary(requestId: string) {
  const abort = AbortSignal.timeout(10_000);
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
  });

  return client.systemBoundaryGetTracerStatus({ signal: abort, requestId });
}
