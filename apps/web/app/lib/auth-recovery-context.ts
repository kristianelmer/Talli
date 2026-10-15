import { cookies } from "next/headers";

import { createSupabaseServerClient, hasSupabaseEnv } from "./supabase/server";
import { readRecoveryIntent, RECOVERY_GRANT_COOKIE, recoverySigningSecret } from "./auth-recovery-intent";

export function hasAuthRecoveryEnv() {
  // Recovery email credentials must never follow an untrusted Host header.
  const site = process.env.SITE_URL ?? process.env.NEXT_PUBLIC_SITE_URL
    ?? (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : null);
  if (!site) return false;
  try {
    const url = new URL(site);
    if (url.username || url.password || (url.protocol !== "https:"
      && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)))) return false;
  } catch { return false; }
  return hasSupabaseEnv() && recoverySigningSecret() !== null;
}

/** Auth owns identity/AAL. The signed cookie scopes a verified recovery visit. */
export async function passwordRecoveryContext() {
  const secret = recoverySigningSecret();
  if (!hasSupabaseEnv() || !secret) return { kind: "unavailable" } as const;
  const cookieStore = await cookies();
  const grant = readRecoveryIntent(cookieStore.get(RECOVERY_GRANT_COOKIE)?.value, secret);
  if (!grant || grant.kind !== "grant") return { kind: "invalid-link" } as const;
  try {
    const supabase = await createSupabaseServerClient();
    const userResult = await supabase.auth.getUser();
    if (userResult.error && (userResult.error.status ?? 0) >= 500) return { kind: "unavailable", next: grant.next } as const;
    if (userResult.error || !userResult.data.user) return { kind: "expired-session", next: grant.next } as const;
    const user = userResult.data.user;
    if (user.id !== grant.userId) return { kind: "wrong-account", next: grant.next } as const;
    const claimsResult = await supabase.auth.getClaims();
    const claims = claimsResult.data?.claims;
    if (claimsResult.error && (claimsResult.error.status ?? 0) >= 500) return { kind: "unavailable", next: grant.next } as const;
    if (claimsResult.error || claims?.sub !== user.id || claims.session_id !== grant.sessionId) {
      return { kind: "expired-session", next: grant.next } as const;
    }
    // The SDK's no-token assurance overload reads session.user from a cookie.
    // Use verified JWT assurance and the fresh Auth response's factors instead.
    if (claims.aal !== "aal1" && claims.aal !== "aal2") return { kind: "unavailable", next: grant.next } as const;
    if (user.factors?.some((factor) => factor.status === "verified") && claims.aal !== "aal2") {
      return { kind: "mfa", next: grant.next } as const;
    }
    return { kind: "ready", next: grant.next, user, supabase } as const;
  } catch {
    return { kind: "unavailable", next: grant.next } as const;
  }
}
