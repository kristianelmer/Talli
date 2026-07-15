export type SensitiveAction =
  | "production_filing"
  | "approve_corporate_facts"
  | "attest_signed_corporate_document"
  | "finalize_corporate_decision"
  | "record_owner_dividend_payment"
  | "confirm_authority"
  | "invite_reviewer"
  | "change_role"
  | "document_download"
  | "archive_export"
  | "billing_admin"
  | "company_cancel"
  | "company_delete";

export type StepUpContext = {
  actorId: string;
  mfaVerifiedAt: string | null;
};

export type StepUpRequirement = {
  action: SensitiveAction;
  requiresMfa: boolean;
  maxMfaAgeMinutes: number;
  label: string;
};

type SupabaseStepUpClient = {
  auth: {
    getClaims: () => Promise<{
      data: { claims: unknown } | null;
      error: unknown;
    }>;
  };
  from: (table: string) => any;
};

type SignedClaimRecord = {
  sub?: unknown;
  aal?: unknown;
  amr?: unknown;
};

const timestampedMfaMethods = new Set(["totp", "mfa/totp", "mfa/phone", "mfa/webauthn"]);

export class SensitiveActionStepUpError extends Error {
  readonly code: string;
  readonly userMessage: string;

  constructor(message: string, code: string, userMessage = message) {
    super(message);
    this.name = "SensitiveActionStepUpError";
    this.code = code;
    this.userMessage = userMessage;
  }
}

export const sensitiveActionRequirements: StepUpRequirement[] = [
  {
    action: "production_filing",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Produksjonsinnsending",
  },
  {
    action: "approve_corporate_facts",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Godkjenn selskapsrettslige fakta",
  },
  {
    action: "attest_signed_corporate_document",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Bekreft signert selskapsdokument",
  },
  {
    action: "finalize_corporate_decision",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Fullfør selskapsbeslutning",
  },
  {
    action: "record_owner_dividend_payment",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Avstem utbyttebetaling",
  },
  {
    action: "confirm_authority",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Bekreft innsendingsrett",
  },
  {
    action: "invite_reviewer",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Inviter reviewer",
  },
  {
    action: "change_role",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Endre rolle",
  },
  {
    action: "document_download",
    requiresMfa: false,
    maxMfaAgeMinutes: 15,
    label: "Dokumentnedlasting",
  },
  {
    action: "archive_export",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Arkiveksport",
  },
  {
    action: "billing_admin",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Billing-admin",
  },
  {
    action: "company_cancel",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Kanseller selskap",
  },
  {
    action: "company_delete",
    requiresMfa: true,
    maxMfaAgeMinutes: 15,
    label: "Slett selskap",
  },
];

export function requirementForSensitiveAction(action: SensitiveAction) {
  const requirement = sensitiveActionRequirements.find((item) => item.action === action);
  if (!requirement) {
    throw new SensitiveActionStepUpError("Ukjent sensitiv handling.", "unknown_sensitive_action");
  }
  return requirement;
}

export function assertStepUpAllowed(action: SensitiveAction, context: StepUpContext, now = new Date()) {
  const requirement = requirementForSensitiveAction(action);
  if (!context.actorId) {
    throw new SensitiveActionStepUpError(
      `${requirement.label} mangler innlogget aktør.`,
      "missing_actor",
      `${requirement.label} stoppet: innlogging kreves.`,
    );
  }
  if (requirement.requiresMfa) {
    if (!context.mfaVerifiedAt) {
      throw new SensitiveActionStepUpError(
        `${requirement.label} krever fersk MFA/step-up.`,
        "missing_mfa_step_up",
        `${requirement.label} stoppet: fersk MFA/step-up kreves.`,
      );
    }
    const verifiedAt = new Date(context.mfaVerifiedAt);
    if (Number.isNaN(verifiedAt.getTime())) {
      throw new SensitiveActionStepUpError(
        `${requirement.label} har ugyldig MFA-tidspunkt.`,
        "invalid_mfa_step_up",
        `${requirement.label} stoppet: MFA/step-up må gjennomføres på nytt.`,
      );
    }
    const ageMs = now.getTime() - verifiedAt.getTime();
    if (ageMs < 0 || ageMs > requirement.maxMfaAgeMinutes * 60_000) {
      throw new SensitiveActionStepUpError(
        `${requirement.label} krever MFA/step-up nyere enn ${requirement.maxMfaAgeMinutes} minutter.`,
        "expired_mfa_step_up",
        `${requirement.label} stoppet: MFA/step-up er utløpt. Bekreft på nytt.`,
      );
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function stepUpContextFromClaims(actorId: string, value: unknown): StepUpContext {
  if (!isRecord(value)) {
    return { actorId, mfaVerifiedAt: null };
  }

  const claims = value as SignedClaimRecord;
  if (claims.sub !== actorId || claims.aal !== "aal2" || !Array.isArray(claims.amr)) {
    return { actorId, mfaVerifiedAt: null };
  }

  let newestMfaTimestampSeconds: number | null = null;
  for (const entry of claims.amr) {
    if (!isRecord(entry) || typeof entry.method !== "string" || !timestampedMfaMethods.has(entry.method)) {
      continue;
    }
    if (typeof entry.timestamp !== "number" || !Number.isFinite(entry.timestamp)) {
      continue;
    }
    if (newestMfaTimestampSeconds === null || entry.timestamp > newestMfaTimestampSeconds) {
      newestMfaTimestampSeconds = entry.timestamp;
    }
  }

  if (newestMfaTimestampSeconds === null) {
    return { actorId, mfaVerifiedAt: null };
  }

  const verifiedAt = new Date(newestMfaTimestampSeconds * 1000);
  if (Number.isNaN(verifiedAt.getTime())) {
    return { actorId, mfaVerifiedAt: null };
  }

  return {
    actorId,
    mfaVerifiedAt: verifiedAt.toISOString(),
  };
}

export async function loadTrustedStepUpContext(
  supabase: SupabaseStepUpClient,
  actorId: string,
): Promise<StepUpContext> {
  const { data, error } = await supabase.auth.getClaims();
  if (error) {
    throw new SensitiveActionStepUpError(
      "Verifiserte innloggingskrav kunne ikke kontrolleres.",
      "trusted_claims_lookup_failed",
      "Sensitiv handling stoppet: innloggingen kunne ikke verifiseres. Prøv å logge inn på nytt.",
    );
  }
  if (!data?.claims) {
    throw new SensitiveActionStepUpError(
      "Verifiserte innloggingskrav mangler.",
      "trusted_claims_missing",
      "Sensitiv handling stoppet: innloggingen kunne ikke verifiseres. Prøv å logge inn på nytt.",
    );
  }
  return stepUpContextFromClaims(actorId, data.claims);
}

export async function requireStepUpForAction(input: {
  supabase: SupabaseStepUpClient;
  userId: string;
  companyId: string;
  action: SensitiveAction;
  now?: Date;
}) {
  const requirement = requirementForSensitiveAction(input.action);
  try {
    const context = await loadTrustedStepUpContext(input.supabase, input.userId);
    assertStepUpAllowed(input.action, context, input.now);
    await input.supabase.from("audit_events").insert({
      company_id: input.companyId,
      actor_id: input.userId,
      category: "security",
      action: "sensitive_action_allowed",
      message: `${requirement.label} tillatt etter MFA/step-up-kontroll.`,
    });
  } catch (error) {
    const stepUpError =
      error instanceof SensitiveActionStepUpError
        ? error
        : new SensitiveActionStepUpError("Sensitiv handling stoppet.", "step_up_failed");
    await input.supabase.from("audit_events").insert({
      company_id: input.companyId,
      actor_id: input.userId,
      category: "security",
      action: "sensitive_action_blocked",
      message: `${requirement.label} blokkert: ${stepUpError.code}.`,
    });
    throw stepUpError;
  }
}
