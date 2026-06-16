export type SensitiveAction =
  | "production_filing"
  | "confirm_authority"
  | "invite_reviewer"
  | "change_role"
  | "document_download"
  | "archive_export"
  | "billing_admin"
  | "company_delete";

export type StepUpContext = {
  actorId: string;
  mfaVerifiedAt: string | null;
  securityReviewApproved?: boolean;
  productionCredentialsEnabled?: boolean;
};

export type StepUpRequirement = {
  action: SensitiveAction;
  requiresMfa: boolean;
  requiresSecurityReview: boolean;
  requiresProductionCredentialsGate: boolean;
  maxMfaAgeMinutes: number;
  label: string;
};

type SupabaseStepUpClient = {
  from: (table: string) => any;
};

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
    requiresSecurityReview: true,
    requiresProductionCredentialsGate: true,
    maxMfaAgeMinutes: 15,
    label: "Produksjonsinnsending",
  },
  {
    action: "confirm_authority",
    requiresMfa: true,
    requiresSecurityReview: false,
    requiresProductionCredentialsGate: false,
    maxMfaAgeMinutes: 15,
    label: "Bekreft innsendingsrett",
  },
  {
    action: "invite_reviewer",
    requiresMfa: true,
    requiresSecurityReview: false,
    requiresProductionCredentialsGate: false,
    maxMfaAgeMinutes: 15,
    label: "Inviter reviewer",
  },
  {
    action: "change_role",
    requiresMfa: true,
    requiresSecurityReview: false,
    requiresProductionCredentialsGate: false,
    maxMfaAgeMinutes: 15,
    label: "Endre rolle",
  },
  {
    action: "document_download",
    requiresMfa: false,
    requiresSecurityReview: false,
    requiresProductionCredentialsGate: false,
    maxMfaAgeMinutes: 15,
    label: "Dokumentnedlasting",
  },
  {
    action: "archive_export",
    requiresMfa: true,
    requiresSecurityReview: false,
    requiresProductionCredentialsGate: false,
    maxMfaAgeMinutes: 15,
    label: "Arkiveksport",
  },
  {
    action: "billing_admin",
    requiresMfa: true,
    requiresSecurityReview: false,
    requiresProductionCredentialsGate: false,
    maxMfaAgeMinutes: 15,
    label: "Billing-admin",
  },
  {
    action: "company_delete",
    requiresMfa: true,
    requiresSecurityReview: true,
    requiresProductionCredentialsGate: false,
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
  if (requirement.requiresSecurityReview && !context.securityReviewApproved) {
    throw new SensitiveActionStepUpError(
      `${requirement.label} krever human security review.`,
      "missing_security_review",
      `${requirement.label} stoppet: security review må være godkjent.`,
    );
  }
  if (requirement.requiresProductionCredentialsGate && !context.productionCredentialsEnabled) {
    throw new SensitiveActionStepUpError(
      `${requirement.label} krever eksplisitt produksjonscredential-gate.`,
      "missing_production_credentials_gate",
      `${requirement.label} stoppet: produksjonscredentials er ikke aktivert.`,
    );
  }
}

export function stepUpContextFromEvent(
  actorId: string,
  event:
    | {
        actor_id: string;
        mfa_verified_at: string | null;
        security_review_approved: boolean | null;
        production_credentials_enabled: boolean | null;
      }
    | null
    | undefined,
): StepUpContext {
  if (!event) {
    return { actorId, mfaVerifiedAt: null };
  }
  if (event.actor_id !== actorId) {
    return { actorId, mfaVerifiedAt: null };
  }
  return {
    actorId,
    mfaVerifiedAt: event.mfa_verified_at,
    securityReviewApproved: Boolean(event.security_review_approved),
    productionCredentialsEnabled: Boolean(event.production_credentials_enabled),
  };
}

export async function loadLatestStepUpContext(supabase: SupabaseStepUpClient, actorId: string): Promise<StepUpContext> {
  const { data, error } = await supabase
    .from("step_up_events")
    .select("actor_id, mfa_verified_at, security_review_approved, production_credentials_enabled")
    .eq("actor_id", actorId)
    .order("mfa_verified_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) {
    throw new SensitiveActionStepUpError(
      `Kunne ikke lese MFA/step-up-status: ${error.message}`,
      "step_up_lookup_failed",
      "Sensitiv handling stoppet: MFA/step-up-status kunne ikke kontrolleres.",
    );
  }
  return stepUpContextFromEvent(actorId, data);
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
    const context = await loadLatestStepUpContext(input.supabase, input.userId);
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
