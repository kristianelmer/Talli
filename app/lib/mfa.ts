export type MfaActionState = {
  status: "idle" | "enrollment_started" | "verified" | "error";
  message: string;
  enrollment?: {
    factorId: string;
    qrCodeDataUrl: string;
    secret: string;
  };
};

export const initialMfaActionState: MfaActionState = {
  status: "idle",
  message: "",
};

export class MfaInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MfaInputError";
  }
}

export function normalizeTotpCode(value: FormDataEntryValue | null) {
  if (typeof value !== "string") throw new MfaInputError("Skriv inn sekssifret kode fra autentiseringsappen.");
  const code = value.replace(/[\s-]/gu, "");
  if (!/^\d{6}$/u.test(code)) throw new MfaInputError("TOTP-koden må ha seks sifre.");
  return code;
}

export function normalizeMfaFactorId(value: FormDataEntryValue | null) {
  if (typeof value !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(value)) {
    throw new MfaInputError("Ugyldig MFA-faktor. Last siden på nytt.");
  }
  return value;
}

export function totpQrCodeDataUrl(qrCode: string) {
  if (qrCode.startsWith("data:image/svg+xml")) return qrCode;
  return `data:image/svg+xml;utf-8,${encodeURIComponent(qrCode)}`;
}
