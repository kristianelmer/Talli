export type AuthorityObligation = "aksjonaerregisteroppgaven" | "skattemelding" | "aarsregnskap";
export type AuthorityPermissionGateStatus =
  | "missing_authority_confirmation"
  | "production_disabled"
  | "ready_for_production_submission";

export type AuthorityPermission = {
  company_id: string;
  obligation: AuthorityObligation;
  submitter_user_id: string;
  confirmed_by: string;
  confirmed_at: string;
  production_enabled: boolean;
};

export type AuthorityPermissionGate = {
  status: AuthorityPermissionGateStatus;
  allowed: boolean;
  message: string;
};

export const authorityObligations: AuthorityObligation[] = [
  "aksjonaerregisteroppgaven",
  "skattemelding",
  "aarsregnskap",
];

export function authorityObligationLabel(obligation: AuthorityObligation) {
  if (obligation === "aksjonaerregisteroppgaven") {
    return "Aksjonærregisteroppgaven";
  }
  if (obligation === "skattemelding") {
    return "Skattemelding for AS";
  }
  return "Årsregnskap";
}

export function validateAuthorityObligation(value: string): AuthorityObligation {
  if (!authorityObligations.includes(value as AuthorityObligation)) {
    throw new Error("Ugyldig myndighetsplikt.");
  }
  return value as AuthorityObligation;
}

export function authorityPermissionGateStatusLabel(status: AuthorityPermissionGateStatus): string {
  if (status === "ready_for_production_submission") return "Klar for produksjonsinnsending";
  if (status === "production_disabled") return "Produksjonsinnsending deaktivert";
  return "Innsendingsrett ikke bekreftet";
}

export function productionAuthorityGate(
  permissions: Pick<AuthorityPermission, "obligation" | "confirmed_at" | "production_enabled">[],
  obligation: AuthorityObligation,
): AuthorityPermissionGate {
  const permission = permissions.find((item) => item.obligation === obligation);
  if (!permission?.confirmed_at) {
    return {
      status: "missing_authority_confirmation",
      allowed: false,
      message: "Innsendingsrett må bekreftes av eier før produksjonsinnsending.",
    };
  }
  if (!permission.production_enabled) {
    return {
      status: "production_disabled",
      allowed: false,
      message: "Produksjonsinnsending er fortsatt deaktivert for denne plikten.",
    };
  }
  return {
    status: "ready_for_production_submission",
    allowed: true,
    message: "Innsendingsrett er bekreftet og produksjonsgate er aktivert.",
  };
}
