import { createHash, createHmac, randomUUID, timingSafeEqual } from "node:crypto";

import { recoveryReturn } from "./auth-recovery-presentation";

export const RECOVERY_REQUEST_COOKIE = "talli_password_recovery_request";
export const RECOVERY_GRANT_COOKIE = "talli_password_recovery_grant";
export const RECOVERY_INTENT_SECONDS = 10 * 60;

type IntentBase = { version: 1; nonce: string; expiresAt: number; next: string };
export type RecoveryRequestIntent = IntentBase & {
  kind: "request"; email: string; verifierHash: string;
};
export type RecoveryGrantIntent = IntentBase & {
  kind: "grant"; userId: string; sessionId: string;
};
export type RecoveryIntent = RecoveryRequestIntent | RecoveryGrantIntent;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

/** Existing server-only key; never an admin Auth call or client-side secret. */
export function recoverySigningSecret() {
  const value = process.env.SUPABASE_SERVICE_ROLE_KEY;
  return value && value.length >= 32 ? value : null;
}

function signature(payload: string, secret: string) {
  const key = createHmac("sha256", secret).update("talli/auth/password-recovery/v1").digest();
  return createHmac("sha256", key).update(payload).digest();
}

export function verifierDigest(value: string) {
  return createHash("sha256").update(value).digest("hex");
}

export function mintRecoveryIntent(
  payload: { kind: "request"; email: string; verifierHash: string; next: string }
    | { kind: "grant"; userId: string; sessionId: string; next: string },
  secret: string,
  now = Date.now(),
) {
  const intent = {
    ...payload, next: recoveryReturn(payload.next), version: 1,
    nonce: randomUUID(), expiresAt: now + RECOVERY_INTENT_SECONDS * 1_000,
  };
  const encoded = Buffer.from(JSON.stringify(intent)).toString("base64url");
  return `${encoded}.${signature(encoded, secret).toString("hex")}`;
}

export function readRecoveryIntent(value: string | undefined, secret: string, now = Date.now()): RecoveryIntent | null {
  if (!value || value.length > 8_192) return null;
  const [payload, signed, extra] = value.split(".");
  if (extra !== undefined || !/^[A-Za-z0-9_-]+$/u.test(payload) || !/^[a-f0-9]{64}$/u.test(signed ?? "")) return null;
  if (!timingSafeEqual(signature(payload, secret), Buffer.from(signed, "hex"))) return null;
  try {
    const parsed = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)
      || parsed.version !== 1 || !uuid.test(parsed.nonce)
      || !Number.isSafeInteger(parsed.expiresAt) || parsed.expiresAt <= now
      || parsed.expiresAt > now + RECOVERY_INTENT_SECONDS * 1_000
      || typeof parsed.next !== "string" || recoveryReturn(parsed.next) !== parsed.next) return null;
    const keys = Object.keys(parsed).sort().join(",");
    if (parsed.kind === "request" && keys === "email,expiresAt,kind,next,nonce,verifierHash,version"
      && typeof parsed.email === "string" && parsed.email.length <= 320
      && /^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(parsed.email)
      && /^[a-f0-9]{64}$/u.test(parsed.verifierHash)) return parsed;
    if (parsed.kind === "grant" && keys === "expiresAt,kind,next,nonce,sessionId,userId,version"
      && uuid.test(parsed.userId) && uuid.test(parsed.sessionId)) return parsed;
  } catch {
    // Malformed cookies are unusable; they never establish Auth authority.
  }
  return null;
}

export const recoveryCookieOptions = {
  httpOnly: true, sameSite: "lax" as const, path: "/",
  secure: process.env.NODE_ENV === "production", maxAge: RECOVERY_INTENT_SECONDS,
};
