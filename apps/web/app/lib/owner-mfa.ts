import type { SupabaseClient } from "@supabase/supabase-js";

type OwnerMfaApi = SupabaseClient["auth"]["mfa"];

/** A browser download leaves the verified MFA page open instead of navigating. */
export function ownerMfaHistoryDownloadReturn(returnTo: string): string | null {
  const match = /^\/companies\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/rf1086-test-history\/download$/u.exec(returnTo);
  if (!match || match[1] === "00000000-0000-0000-0000-000000000000") return null;
  return `/companies/${match[1]}/rf1086-test-history`;
}

export const ownerMfaCopy = {
  heading: "Beskytt kontoen før du fortsetter",
  intro:
    "Bekreft innloggingen med en autentiseringsapp før du fortsetter.",
  statusError:
    "MFA-kontrollen kunne ikke fullføres. Arbeidsflaten er fortsatt stengt. Prøv kontrollen igjen.",
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
  | { kind: "challenge"; factorId: string; factors?: { id: string; label: string }[] }
  | { kind: "verified" }
  | { kind: "error"; message: string };

export async function inspectOwnerMfa(
  mfa: OwnerMfaApi,
  { requireFreshChallenge = false, accessToken }: { requireFreshChallenge?: boolean; accessToken?: string } = {},
): Promise<OwnerMfaInspection> {
  if (!accessToken) return { kind: "error", message: ownerMfaCopy.statusError };
  try {
    const assurance = await mfa.getAuthenticatorAssuranceLevel(accessToken);
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
      ? { kind: "challenge", factorId: factor.id,
        ...(factors.data.totp.length > 1 ? { factors: factors.data.totp.map((item, index) => ({
          id: item.id, label: `${item.friendly_name || "Autentiseringsapp"} (${index + 1})`,
        })) } : {}) }
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
    if (typeof verification.data.access_token !== "string") return { ok: false, message: ownerMfaCopy.verificationError };
    const assurance = await mfa.getAuthenticatorAssuranceLevel(verification.data.access_token);
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
