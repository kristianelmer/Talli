import { createTalliApiClient } from "@talli/talli-api-client";

export function companyAccessBackendBaseUrl(): string {
  const raw = process.env.TALLI_BACKEND_URL;
  if (!raw) throw new Error("BACKEND_URL_MISSING");
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("BACKEND_URL_INVALID");
  }
  if (
    !["http:", "https:"].includes(url.protocol)
    || url.username
    || url.password
    || (url.pathname !== "/" && url.pathname !== "")
    || url.search
    || url.hash
  ) {
    throw new Error("BACKEND_URL_INVALID");
  }
  const isLoopback = ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
  if (process.env.NODE_ENV === "production" && url.protocol !== "https:" && !isLoopback) {
    throw new Error("BACKEND_URL_INSECURE");
  }
  return url.origin;
}

export async function loadCompanyAccessContext(
  accessToken: string,
  requestId?: string,
  options: { companyId?: string } = {},
) {
  const client = createTalliApiClient({
    baseUrl: companyAccessBackendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  return client.companyAccessGetSelectedContext({
    ...options,
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}
