import { createTalliApiClient } from "@talli/talli-api-client";
import { backendBaseUrl, backendClientOptions } from "#backend-configuration";

export {
  BackendConfigurationError,
  backendBaseUrl,
  type BackendConfigurationErrorCode,
} from "#backend-configuration";

export async function loadSystemBoundary(requestId: string) {
  const abort = AbortSignal.timeout(10_000);
  const client = createTalliApiClient({
    ...backendClientOptions(),
  });

  return client.systemBoundaryGetTracerStatus({ signal: abort, requestId });
}
