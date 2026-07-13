"use server";

import { revalidatePath } from "next/cache";
import {
  type MfaActionState,
  MfaInputError,
  normalizeMfaFactorId,
  normalizeTotpCode,
  totpQrCodeDataUrl,
} from "../../lib/mfa";
import { createSupabaseServerClient, hasSupabaseEnv } from "../../lib/supabase/server";

async function authenticatedClient() {
  if (!hasSupabaseEnv()) return { ok: false, error: "Supabase-miljøvariabler mangler." } as const;
  const supabase = await createSupabaseServerClient();
  const { data: { user }, error } = await supabase.auth.getUser();
  if (error || !user) return { ok: false, error: "Logg inn før du administrerer MFA." } as const;
  return { ok: true, supabase, user } as const;
}

export async function beginTotpEnrollment(
  _previousState: MfaActionState,
  _formData: FormData,
): Promise<MfaActionState> {
  const auth = await authenticatedClient();
  if (!auth.ok) return { status: "error", message: auth.error };

  const { data: factors, error: factorError } = await auth.supabase.auth.mfa.listFactors();
  if (factorError) return { status: "error", message: "Kunne ikke kontrollere eksisterende MFA-faktorer." };
  if (factors.totp.length > 0) {
    return { status: "error", message: "En verifisert TOTP-faktor finnes allerede. Bruk step-up-skjemaet." };
  }

  const { data, error } = await auth.supabase.auth.mfa.enroll({
    factorType: "totp",
    friendlyName: "Talli Authenticator",
    issuer: "Talli",
  });
  if (error) return { status: "error", message: "Kunne ikke starte TOTP-registrering." };

  return {
    status: "enrollment_started",
    message: "Skann QR-koden og bekreft med en sekssifret kode.",
    enrollment: {
      factorId: data.id,
      qrCodeDataUrl: totpQrCodeDataUrl(data.totp.qr_code),
      secret: data.totp.secret,
    },
  };
}

export async function verifyTotpStepUp(
  _previousState: MfaActionState,
  formData: FormData,
): Promise<MfaActionState> {
  const auth = await authenticatedClient();
  if (!auth.ok) return { status: "error", message: auth.error };

  let factorId: string;
  let code: string;
  try {
    factorId = normalizeMfaFactorId(formData.get("factorId"));
    code = normalizeTotpCode(formData.get("code"));
  } catch (error) {
    return {
      status: "error",
      message: error instanceof MfaInputError ? error.message : "Ugyldig MFA-forespørsel.",
    };
  }

  const { error: verifyError } = await auth.supabase.auth.mfa.challengeAndVerify({ factorId, code });
  if (verifyError) return { status: "error", message: "Koden ble ikke godkjent. Prøv en ny kode." };

  const { error: recordError } = await auth.supabase.rpc("record_mfa_step_up");
  if (recordError) {
    return {
      status: "error",
      message: "MFA ble bekreftet, men step-up kunne ikke registreres. Sensitive handlinger forblir blokkert.",
    };
  }

  revalidatePath("/");
  revalidatePath("/security/mfa");
  return {
    status: "verified",
    message: "MFA/step-up er registrert og gjelder for sensitive handlinger i 15 minutter.",
  };
}
