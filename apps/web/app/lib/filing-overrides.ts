export type FilingOverrideRiskLevel = "advisory" | "warning" | "block";

export type FilingOverrideInput = {
  fieldTarget: string;
  oldValue: string;
  newValue: string;
  reason: string;
  riskLevel: FilingOverrideRiskLevel;
};

export type FilingOverrideGateInput = {
  risk_level: FilingOverrideRiskLevel;
  field_target?: string;
};

export function validateFilingOverride(input: FilingOverrideInput) {
  const fieldTarget = input.fieldTarget.trim();
  const oldValue = input.oldValue.trim();
  const newValue = input.newValue.trim();
  const reason = input.reason.trim();
  if (!fieldTarget) {
    throw new Error("Feltmål mangler for filing-overstyring.");
  }
  if (!oldValue && !newValue) {
    throw new Error("Gammel eller ny verdi må fylles ut for filing-overstyring.");
  }
  if (!reason) {
    throw new Error("Begrunnelse mangler for filing-overstyring.");
  }
  if (!["advisory", "warning", "block"].includes(input.riskLevel)) {
    throw new Error("Ugyldig risikonivå for filing-overstyring.");
  }
  return {
    fieldTarget,
    oldValue,
    newValue,
    reason,
    riskLevel: input.riskLevel,
  };
}

export function assertNoBlockingFilingOverrides(overrides: FilingOverrideGateInput[]) {
  const blockingOverride = overrides.find((override) => override.risk_level === "block");
  if (blockingOverride) {
    throw new Error(
      `Blokkerende filing-overstyring må avklares før simulert innsending: ${blockingOverride.field_target ?? "ukjent felt"}.`,
    );
  }
}
