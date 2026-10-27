import { createTalliApiClient, TalliApiError, type LaunchSignoffCommandWire } from "@talli/talli-api-client";
import { backendClientOptions } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({ ...backendClientOptions(), headers: { Authorization: `Bearer ${accessToken}` } });
}
function request() { return { signal: AbortSignal.timeout(15_000) }; }

export async function loadLaunchSignoffs(accessToken: string) {
  return (await client(accessToken).operatorControlsListLaunchSignoffs(request())).signoffs;
}

export async function recordLaunchSignoffThroughApi(accessToken: string, body: LaunchSignoffCommandWire) {
  const result = await client(accessToken).operatorControlsRecordLaunchSignoff(body, request());
  if (result.key !== body.key || result.status !== body.status) throw new TalliApiError(502, undefined);
  return result;
}
