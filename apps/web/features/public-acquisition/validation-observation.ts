export const validationObservationModes = ["off", "invited-pilot"] as const;

// This runtime controls only a passive evidence writer. Product behavior must
// never branch on this value; full launch turns off the writer, not a feature.

export type ValidationObservationMode = (typeof validationObservationModes)[number];

export type ValidationObservationRuntimeInput = {
  requestedMode?: string;
  publicAcquisitionMode?: string;
  pilotEntitlementId?: string;
  approvedRunId?: string;
  expiresAt?: string;
  now?: number;
};

export type ValidationObservationRuntime = {
  mode: ValidationObservationMode;
  pilotEntitlementId: string | null;
  approvedRunId: string | null;
  expiresAt: string | null;
  blockingReasons: readonly string[];
};

const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const runId = /^V2P8-[0-9]{8}-[A-Z0-9]{4,16}$/u;
const maximumPilotLifetimeMilliseconds = 90 * 24 * 60 * 60 * 1_000;

export function deriveValidationObservationRuntime(
  input: ValidationObservationRuntimeInput,
): ValidationObservationRuntime {
  const blockingReasons: string[] = [];
  const now = input.now ?? Date.now();
  const expiry = input.expiresAt ? Date.parse(input.expiresAt) : Number.NaN;

  if (input.requestedMode !== "invited-pilot") {
    blockingReasons.push("mode:not-requested");
  }
  if (input.publicAcquisitionMode === "launch") {
    blockingReasons.push("full-launch:forbidden");
  }
  if (!input.pilotEntitlementId || !uuidV4.test(input.pilotEntitlementId)) {
    blockingReasons.push("pilot-entitlement:invalid");
  }
  if (!input.approvedRunId || !runId.test(input.approvedRunId)) {
    blockingReasons.push("validation-run:invalid");
  }
  if (!Number.isFinite(expiry) || expiry <= now) {
    blockingReasons.push("expiry:missing-or-expired");
  } else if (expiry > now + maximumPilotLifetimeMilliseconds) {
    blockingReasons.push("expiry:too-distant");
  }

  if (blockingReasons.length > 0) {
    return {
      mode: "off",
      pilotEntitlementId: null,
      approvedRunId: null,
      expiresAt: null,
      blockingReasons,
    };
  }

  return {
    mode: "invited-pilot",
    pilotEntitlementId: input.pilotEntitlementId ?? null,
    approvedRunId: input.approvedRunId ?? null,
    expiresAt: input.expiresAt ?? null,
    blockingReasons: [],
  };
}

export function validationObservationRuntimeFromEnvironment(
  environment: Record<string, string | undefined> = process.env,
  now = Date.now(),
): ValidationObservationRuntime {
  return deriveValidationObservationRuntime({
    requestedMode: environment.TALLI_VALIDATION_OBSERVATION_MODE,
    publicAcquisitionMode: environment.TALLI_PUBLIC_ACQUISITION_MODE,
    pilotEntitlementId: environment.TALLI_VALIDATION_PILOT_ENTITLEMENT_ID,
    approvedRunId: environment.TALLI_VALIDATION_APPROVED_RUN_ID,
    expiresAt: environment.TALLI_VALIDATION_OBSERVATION_EXPIRES_AT,
    now,
  });
}
