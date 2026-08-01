import { createTalliApiClient } from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

export {
  BackendConfigurationError,
  backendBaseUrl,
  type BackendConfigurationErrorCode,
} from "#backend-configuration";

export async function loadSystemBoundary(requestId: string) {
  const abort = AbortSignal.timeout(10_000);
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
  });

  return client.systemBoundaryGetTracerStatus({ signal: abort, requestId });
}
