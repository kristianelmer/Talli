const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

type SupabaseError = { code?: unknown };
type SupabaseResult = PromiseLike<{ data: unknown; error: SupabaseError | null }>;

export type Rf1086ProductionLeaseClient = {
  rpc(name: string, parameters: Record<string, unknown>): SupabaseResult;
};

export class Rf1086ProductionLeaseError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "Rf1086ProductionLeaseError";
    this.code = code;
  }
}

function leaseError(code: string, message: string) {
  return new Rf1086ProductionLeaseError(code, message);
}

async function callLeaseRpc(
  client: Rf1086ProductionLeaseClient,
  name: string,
  parameters: Record<string, unknown>,
) {
  try {
    return await client.rpc(name, parameters);
  } catch {
    throw leaseError(
      name.startsWith("acquire_")
        ? "rf1086_production_lease_acquire_failed"
        : "rf1086_production_lease_release_failed",
      "RF-1086 production lease operation failed.",
    );
  }
}

export async function withRf1086ProductionLease<T>(input: {
  client: Rf1086ProductionLeaseClient;
  previewId: string;
  actorId: string;
  operation: () => Promise<T>;
}): Promise<T> {
  if (
    !input.client ||
    typeof input.client.rpc !== "function" ||
    !UUID_PATTERN.test(input.previewId) ||
    !UUID_PATTERN.test(input.actorId) ||
    typeof input.operation !== "function"
  ) {
    throw leaseError(
      "rf1086_production_lease_input_invalid",
      "RF-1086 production lease input is invalid.",
    );
  }

  const acquired = await callLeaseRpc(input.client, "acquire_rf1086_production_lease", {
    p_preview_id: input.previewId,
    p_actor_id: input.actorId,
  });
  if (acquired.error) {
    if (acquired.error.code === "PT409") {
      throw leaseError(
        "rf1086_production_lease_conflict",
        "Another RF-1086 production operation is already in progress.",
      );
    }
    throw leaseError(
      "rf1086_production_lease_acquire_failed",
      "RF-1086 production lease could not be acquired.",
    );
  }
  if (typeof acquired.data !== "string" || !UUID_PATTERN.test(acquired.data)) {
    throw leaseError(
      "rf1086_production_lease_response_invalid",
      "RF-1086 production lease returned an invalid response.",
    );
  }

  let result: T | undefined;
  let operationError: unknown;
  let operationFailed = false;
  try {
    result = await input.operation();
  } catch (error) {
    operationFailed = true;
    operationError = error;
  }

  const released = await callLeaseRpc(input.client, "release_rf1086_production_lease", {
    p_preview_id: input.previewId,
    p_lease_id: acquired.data,
  }).catch((error) => {
    if (operationFailed) return null;
    throw error;
  });

  if (operationFailed) throw operationError;
  if (!released || released.error || released.data !== true) {
    throw leaseError(
      "rf1086_production_lease_release_failed",
      "RF-1086 production lease could not be released.",
    );
  }
  return result as T;
}
