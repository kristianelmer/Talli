export const launchSignoffKeys = [
  "launch_legal_name_public_copy",
  "legal_policy_pack",
  "security_restore",
  "billing_refund",
  "rf1086_authority",
  "annual_accounts_authority",
  "tax_return_authority",
  "support_rollback",
  "founder_production_go_live",
] as const;

export type LaunchSignoffKey = (typeof launchSignoffKeys)[number];
export type LaunchSignoffStatus = "approved" | "rejected" | "pending";
export type LaunchSignoffGateStatus = "launch_signoff_ready" | "launch_signoff_blocked";
export type LaunchSignoffReviewStatus = "approved" | "missing" | "rejected" | "stale";

export type LaunchSignoff = {
  key: LaunchSignoffKey;
  status: LaunchSignoffStatus;
  reviewer: string;
  reviewedAt: string;
  evidenceLink: string;
  decision: string;
};

export type LaunchSignoffGate = {
  status: LaunchSignoffGateStatus;
  ready: boolean;
  missing: LaunchSignoffKey[];
  rejected: LaunchSignoffKey[];
  stale: LaunchSignoffKey[];
  messages: string[];
};

export type LaunchSignoffInput = {
  key: string;
  status: string;
  reviewer: string;
  reviewedAt: string;
  evidenceLink: string;
  decision: string;
  recordedBy: string;
};

export type LaunchSignoffRecord = {
  key: LaunchSignoffKey;
  status: LaunchSignoffStatus;
  reviewer: string;
  reviewed_at: string;
  evidence_link: string;
  decision: string;
  recorded_by: string;
  updated_at: string;
};

const signoffLabels: Record<LaunchSignoffKey, string> = {
  launch_legal_name_public_copy: "Launch/legal/name/public copy",
  legal_policy_pack: "Legal/privacy/DPA/retention/incident",
  security_restore: "Security/restore",
  billing_refund: "Billing/refund",
  rf1086_authority: "RF-1086 authority filing",
  annual_accounts_authority: "Årsregnskap authority filing",
  tax_return_authority: "Skattemelding authority filing",
  support_rollback: "Support/rollback",
  founder_production_go_live: "Final founder production go-live",
};

function nonEmpty(value: string) {
  return value.trim().length > 0;
}

function validDate(value: string) {
  return Number.isFinite(Date.parse(value));
}

function daysBetween(later: Date, earlier: Date) {
  return Math.floor((later.getTime() - earlier.getTime()) / 86_400_000);
}

export function launchSignoffLabel(key: LaunchSignoffKey) {
  return signoffLabels[key];
}

export function validateLaunchSignoffKey(value: string): LaunchSignoffKey {
  if (!launchSignoffKeys.includes(value as LaunchSignoffKey)) {
    throw new Error("Ugyldig launch signoff.");
  }
  return value as LaunchSignoffKey;
}

export function validateLaunchSignoffStatus(value: string): LaunchSignoffStatus {
  if (!["approved", "rejected", "pending"].includes(value)) {
    throw new Error("Ugyldig launch signoff status.");
  }
  return value as LaunchSignoffStatus;
}

export function buildLaunchSignoffRecord(input: LaunchSignoffInput, now = new Date()): LaunchSignoffRecord {
  const key = validateLaunchSignoffKey(input.key);
  const status = validateLaunchSignoffStatus(input.status);
  if (!nonEmpty(input.recordedBy)) {
    throw new Error("Recorded by mangler.");
  }
  if (!validDate(input.reviewedAt)) {
    throw new Error("Review date er ugyldig.");
  }
  if (status === "approved" && (!nonEmpty(input.reviewer) || !nonEmpty(input.evidenceLink) || !nonEmpty(input.decision))) {
    throw new Error("Approved signoff krever reviewer, evidenslenke og beslutning.");
  }
  return {
    key,
    status,
    reviewer: input.reviewer.trim(),
    reviewed_at: input.reviewedAt,
    evidence_link: input.evidenceLink.trim(),
    decision: input.decision.trim(),
    recorded_by: input.recordedBy.trim(),
    updated_at: now.toISOString(),
  };
}

export function evaluateLaunchSignoff(input: {
  signoffs: LaunchSignoff[];
  key: LaunchSignoffKey;
  now?: Date;
  restoreMaxAgeDays?: number;
}): LaunchSignoffReviewStatus {
  const now = input.now ?? new Date();
  const restoreMaxAgeDays = input.restoreMaxAgeDays ?? 30;
  const signoff = input.signoffs.find((item) => item.key === input.key);

  if (
    !signoff ||
    signoff.status === "pending" ||
    !nonEmpty(signoff.reviewer) ||
    !nonEmpty(signoff.evidenceLink) ||
    !nonEmpty(signoff.decision) ||
    !validDate(signoff.reviewedAt)
  ) {
    return "missing";
  }
  if (signoff.status === "rejected") {
    return "rejected";
  }
  if (
    input.key === "security_restore" &&
    daysBetween(now, new Date(signoff.reviewedAt)) > restoreMaxAgeDays
  ) {
    return "stale";
  }
  return "approved";
}

export function buildLaunchSignoffGate(input: {
  signoffs: LaunchSignoff[];
  now?: Date;
  restoreMaxAgeDays?: number;
}): LaunchSignoffGate {
  const now = input.now ?? new Date();
  const restoreMaxAgeDays = input.restoreMaxAgeDays ?? 30;
  const missing: LaunchSignoffKey[] = [];
  const rejected: LaunchSignoffKey[] = [];
  const stale: LaunchSignoffKey[] = [];
  const messages: string[] = [];

  for (const key of launchSignoffKeys) {
    const status = evaluateLaunchSignoff({
      signoffs: input.signoffs,
      key,
      now,
      restoreMaxAgeDays,
    });
    if (status === "missing") {
      missing.push(key);
      messages.push(`${launchSignoffLabel(key)} mangler godkjent reviewer, dato, evidenslenke eller beslutning.`);
      continue;
    }
    if (status === "rejected") {
      rejected.push(key);
      messages.push(`${launchSignoffLabel(key)} er avvist av reviewer.`);
      continue;
    }
    if (status === "stale") {
      const signoff = input.signoffs.find((item) => item.key === key)!;
      const ageDays = daysBetween(now, new Date(signoff.reviewedAt));
      stale.push(key);
      messages.push(`Security/restore signoff er ${ageDays} dager gammel og maa fornyes.`);
    }
  }

  const ready = missing.length === 0 && rejected.length === 0 && stale.length === 0;
  return {
    status: ready ? "launch_signoff_ready" : "launch_signoff_blocked",
    ready,
    missing,
    rejected,
    stale,
    messages,
  };
}
