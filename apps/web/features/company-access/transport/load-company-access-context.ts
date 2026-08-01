import { createTalliApiClient } from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

export {
  BackendConfigurationError,
  backendBaseUrl as companyAccessBackendBaseUrl,
  type BackendConfigurationErrorCode,
} from "#backend-configuration";

export async function loadCompanyAccessContext(
  accessToken: string,
  requestId?: string,
  options: { companyId?: string } = {},
) {
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  return client.companyAccessGetSelectedContext({
    ...options,
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}
