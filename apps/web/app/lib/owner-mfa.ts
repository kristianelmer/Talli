import type { SupabaseClient } from "@supabase/supabase-js";

type OwnerMfaApi = SupabaseClient["auth"]["mfa"];

export const ownerMfaCopy = {
  heading: "Beskytt kontoen før du fortsetter",
  intro:
    "Selskapet er opprettet. Før du går videre må du bekrefte innloggingen med en autentiseringsapp.",
  statusError:
    "MFA-kontrollen kunne ikke fullføres. Arbeidsflaten er fortsatt stengt. Last siden på nytt og prøv igjen.",
  enrollmentError:
    "Oppsettet kunne ikke startes. Arbeidsflaten er fortsatt stengt. Prøv igjen.",
  verificationError:
    "Koden kunne ikke bekreftes. Arbeidsflaten er fortsatt stengt. Vent på en ny kode og prøv igjen.",
  codeError: "Skriv den sekssifrede koden fra autentiseringsappen.",
} as const;

export type OwnerMfaErrorKind = "status" | "enrollment" | "verification" | null;

export function ownerMfaEnrollmentControl({
  busy,
  errorKind,
}: {
  busy: boolean;
  errorKind: OwnerMfaErrorKind;
}) {
  return {
    disabled: busy || errorKind === "status",
    label: busy
      ? "Starter …"
      : errorKind === "enrollment"
        ? "Prøv igjen"
        : "Sett opp autentiseringsapp",
  } as const;
}

export type OwnerMfaInspection =
  | { kind: "enrollment" }
  | { kind: "challenge"; factorId: string }
  | { kind: "verified" }
  | { kind: "error"; message: string };

export async function inspectOwnerMfa(
  mfa: OwnerMfaApi,
  { requireFreshChallenge = false }: { requireFreshChallenge?: boolean } = {},
): Promise<OwnerMfaInspection> {
  try {
    const assurance = await mfa.getAuthenticatorAssuranceLevel();
    if (assurance.error || !assurance.data) {
      return { kind: "error", message: ownerMfaCopy.statusError };
    }
    // AAL2 does not prove that a backend-required challenge is still fresh.
    // This intent asks for more verification; the backend retains its age rule.
    if (assurance.data.currentLevel === "aal2" && !requireFreshChallenge) {
      return { kind: "verified" };
    }

    const factors = await mfa.listFactors();
    if (factors.error || !factors.data) {
      return { kind: "error", message: ownerMfaCopy.statusError };
    }
    const factor = factors.data.totp[0];
    return factor
      ? { kind: "challenge", factorId: factor.id }
      : { kind: "enrollment" };
  } catch {
    return { kind: "error", message: ownerMfaCopy.statusError };
  }
}

export type OwnerMfaEnrollment =
  | {
      ok: true;
      factorId: string;
      qrCode: string;
      secret: string;
    }
  | { ok: false; message: string };

export async function startOwnerMfaEnrollment(
  mfa: OwnerMfaApi,
): Promise<OwnerMfaEnrollment> {
  try {
    const enrollment = await mfa.enroll({
      factorType: "totp",
      friendlyName: "Talli selskapseier",
    });
    if (
      enrollment.error
      || !enrollment.data
      || enrollment.data.type !== "totp"
      || !enrollment.data.totp.qr_code
      || !enrollment.data.totp.secret
    ) {
      return { ok: false, message: ownerMfaCopy.enrollmentError };
    }
    return {
      ok: true,
      factorId: enrollment.data.id,
      qrCode: enrollment.data.totp.qr_code,
      secret: enrollment.data.totp.secret,
    };
  } catch {
    return { ok: false, message: ownerMfaCopy.enrollmentError };
  }
}

export type OwnerMfaVerification =
  | { ok: true }
  | { ok: false; message: string };

export async function verifyOwnerMfa(
  mfa: OwnerMfaApi,
  factorId: string,
  code: string,
): Promise<OwnerMfaVerification> {
  if (!factorId || !/^\d{6}$/u.test(code)) {
    return { ok: false, message: ownerMfaCopy.codeError };
  }
  try {
    const verification = await mfa.challengeAndVerify({ factorId, code });
    if (verification.error || !verification.data) {
      return { ok: false, message: ownerMfaCopy.verificationError };
    }
    const assurance = await mfa.getAuthenticatorAssuranceLevel();
    if (
      assurance.error
      || !assurance.data
      || assurance.data.currentLevel !== "aal2"
    ) {
      return { ok: false, message: ownerMfaCopy.verificationError };
    }
    return { ok: true };
  } catch {
    return { ok: false, message: ownerMfaCopy.verificationError };
  }
}
