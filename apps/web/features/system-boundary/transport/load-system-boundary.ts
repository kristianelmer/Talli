import { createTalliApiClient } from "@talli/talli-api-client";

function backendBaseUrl(): string {
  const raw = process.env.TALLI_BACKEND_URL ?? "http://127.0.0.1:8000";
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error("Invalid TALLI_BACKEND_URL");
  }
  const isLoopback = ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
  if (process.env.NODE_ENV === "production" && url.protocol !== "https:" && !isLoopback) {
    throw new Error("TALLI_BACKEND_URL must use HTTPS in production");
  }
  return url.origin;
}

export async function loadSystemBoundary(requestId: string) {
  const abort = AbortSignal.timeout(10_000);
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: {
      "X-Request-ID": requestId,
    },
  });

  return client.systemBoundaryGetTracerStatus({ signal: abort });
}
