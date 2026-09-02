export const acquisitionStopRuleKeys = [
  "eligibility",
  "capability",
  "production",
  "billing",
  "banking",
  "filing",
  "security",
  "ux",
  "deadlines",
  "dataIntegrity",
  "charges",
  "supportCapacity",
] as const;

export type AcquisitionStopRuleKey = (typeof acquisitionStopRuleKeys)[number];

export type PublicAcquisitionRuntimeInput = {
  requestedMode?: string;
  requestedCheckout?: string;
  stableRelease: { gitRevision: string } | null;
  capabilityManifestVersion: string;
  expectedCapabilityManifestVersion: string;
  definitiveEligibilityContinuation: boolean;
  gates: Readonly<Record<AcquisitionStopRuleKey, boolean>>;
};

export type PublicAcquisitionRuntime = {
  mode: "recruitment" | "launch";
  liveClaimsEnabled: boolean;
  checkoutEnabled: boolean;
  blockingReasons: readonly string[];
};

export const deniedAcquisitionGates = Object.fromEntries(
  acquisitionStopRuleKeys.map((key) => [key, false]),
) as Record<AcquisitionStopRuleKey, boolean>;

export function derivePublicAcquisitionRuntime(
  input: PublicAcquisitionRuntimeInput,
): PublicAcquisitionRuntime {
  const blockingReasons = acquisitionStopRuleKeys
    .filter((key) => !input.gates[key])
    .map((key) => `gate:${key}`);
  if (!input.stableRelease) blockingReasons.push("release:missing");
  if (input.capabilityManifestVersion !== input.expectedCapabilityManifestVersion) {
    blockingReasons.push("capability:version-mismatch");
  }
  if (input.requestedMode !== "launch") blockingReasons.push("mode:not-requested");

  const liveClaimsEnabled = blockingReasons.length === 0;
  const checkoutEnabled = liveClaimsEnabled
    && input.requestedCheckout === "true"
    && input.definitiveEligibilityContinuation;

  return {
    mode: liveClaimsEnabled ? "launch" : "recruitment",
    liveClaimsEnabled,
    checkoutEnabled,
    blockingReasons: checkoutEnabled || input.requestedCheckout !== "true"
      ? blockingReasons
      : [...blockingReasons, "eligibility:definitive-required"],
  };
}
