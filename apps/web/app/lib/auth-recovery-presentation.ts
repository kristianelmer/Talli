import { sanitizeInternalRedirect } from "./internal-redirect";

export type AuthRecoveryError =
  | "unavailable" | "rate-limit" | "email" | "invalid-link" | "wrong-account" | "wrong-recipient"
  | "expired-session" | "mfa" | "password-short" | "password-mismatch"
  | "password-rejected" | "password-unknown";

export type AuthRecoveryFormState =
  | { status: "idle" }
  | { status: "sent" }
  | { status: "error"; reason: AuthRecoveryError };

export const authRecoveryMessage: Record<AuthRecoveryError, string> = {
  unavailable: "Tilbakestilling er midlertidig utilgjengelig. Prøv igjen senere.",
  "rate-limit": "Vent litt før du ber om en ny lenke.",
  email: "Skriv inn en gyldig e-postadresse.",
  "invalid-link": "Lenken er ugyldig, utløpt eller allerede brukt. Be om en ny.",
  "wrong-account": "Lenken gjelder en annen konto. Logg ut før du ber om en ny lenke.",
  "wrong-recipient": "Lenken gjelder ikke adressen du ba om. Be om en ny lenke.",
  "expired-session": "Innloggingen for tilbakestillingen er utløpt eller endret. Be om en ny lenke.",
  mfa: "Bekreft med autentiseringsappen før du endrer passordet.",
  "password-short": "Bruk minst 12 tegn.",
  "password-mismatch": "Passordene er ikke like.",
  "password-rejected": "Passordet kunne ikke godtas. Velg et annet passord.",
  "password-unknown": "Endringen kunne ikke bekreftes. Prøv å logge inn med det nye passordet, eller be om en ny lenke.",
};

export function recoveryReturn(value: string | null | undefined) {
  const next = sanitizeInternalRedirect(value);
  const path = new URL(next, "https://talli.internal").pathname;
  return next.length > 2_048 || path.startsWith("/auth/")
    || ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email", "/email-confirmed"].includes(path)
    ? "/dashboard" : next;
}

export function recoveryError(value: string | null | undefined): AuthRecoveryError | null {
  return value && Object.hasOwn(authRecoveryMessage, value) ? value as AuthRecoveryError : null;
}

export function recoveryPasswordError(password: string, confirmation: string) {
  if (password.length < 12) return "password-short" as const;
  if (password !== confirmation) return "password-mismatch" as const;
  return null;
}
