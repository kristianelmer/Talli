"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { createSupabaseServerClient } from "../lib/supabase/server";
import { getSiteUrl } from "../lib/site-url";
import { hasAuthRecoveryEnv, passwordRecoveryContext } from "../lib/auth-recovery-context";
import {
  mintRecoveryIntent, RECOVERY_GRANT_COOKIE, RECOVERY_REQUEST_COOKIE,
  recoveryCookieOptions, recoverySigningSecret, verifierDigest,
} from "../lib/auth-recovery-intent";
import { recoveryPasswordError, recoveryReturn, type AuthRecoveryFormState } from "../lib/auth-recovery-presentation";

function text(data: FormData, name: string) {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

async function unknownPasswordChange(next: string): Promise<never> {
  const cookieStore = await cookies();
  cookieStore.delete(RECOVERY_GRANT_COOKIE);
  redirect(`/reset-password?${new URLSearchParams({ error: "password-unknown", next })}`);
}

export async function requestPasswordRecovery(
  _previous: AuthRecoveryFormState, data: FormData,
): Promise<AuthRecoveryFormState> {
  if (!hasAuthRecoveryEnv()) return { status: "error", reason: "unavailable" };
  const email = text(data, "email").trim().toLowerCase();
  if (email.length > 320 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(email)) {
    return { status: "error", reason: "email" };
  }
  const next = recoveryReturn(text(data, "next"));
  const cookieStore = await cookies();
  cookieStore.delete(RECOVERY_GRANT_COOKIE);
  cookieStore.delete(RECOVERY_REQUEST_COOKIE);
  try {
    const supabase = await createSupabaseServerClient();
    const site = new URL(await getSiteUrl());
    if (site.username || site.password || (site.protocol !== "https:"
      && !(site.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(site.hostname)))) {
      return { status: "error", reason: "unavailable" };
    }
    const callback = new URL("/auth/recovery", site.origin);
    callback.searchParams.set("next", next);
    const result = await supabase.auth.resetPasswordForEmail(email, { redirectTo: callback.href });
    if (result.error) {
      if (result.error.code === "user_not_found") return { status: "sent" };
      return { status: "error", reason: result.error.status === 429 ? "rate-limit" : "unavailable" };
    }
    const verifier = cookieStore.getAll().find(({ name }) => name.endsWith("-code-verifier"))?.value;
    if (!verifier) return { status: "error", reason: "unavailable" };
    cookieStore.set(RECOVERY_REQUEST_COOKIE, mintRecoveryIntent({
      kind: "request", email, verifierHash: verifierDigest(verifier), next,
    }, recoverySigningSecret()!), recoveryCookieOptions);
    return { status: "sent" };
  } catch {
    return { status: "error", reason: "unavailable" };
  }
}

export async function updateRecoveredPassword(
  _previous: AuthRecoveryFormState, data: FormData,
): Promise<AuthRecoveryFormState> {
  const password = text(data, "password");
  const problem = recoveryPasswordError(password, text(data, "confirmation"));
  if (problem) return { status: "error", reason: problem };
  const context = await passwordRecoveryContext();
  if (context.kind !== "ready") return { status: "error", reason: context.kind };
  if (context.user.id !== text(data, "userId")) return { status: "error", reason: "wrong-account" };
  try {
    const result = await context.supabase.auth.updateUser({ password });
    if (result.error) {
      if (result.error.code === "insufficient_aal") return { status: "error", reason: "mfa" };
      if (!result.error.status || result.error.status >= 500) return unknownPasswordChange(context.next);
      return { status: "error", reason: "password-rejected" };
    }
    if (result.data.user?.id !== context.user.id) return unknownPasswordChange(context.next);
  } catch {
    return unknownPasswordChange(context.next);
  }
  const cookieStore = await cookies();
  cookieStore.delete(RECOVERY_GRANT_COOKIE);
  cookieStore.delete(RECOVERY_REQUEST_COOKIE);
  try {
    await context.supabase.auth.signOut({ scope: "local" });
  } catch {
    // Password is confirmed changed; require a new sign-in even if logout failed.
  }
  redirect(`/login?${new URLSearchParams({ reauth: "1", passwordChanged: "1", next: context.next })}`);
}

export async function leaveAccountForRecovery(data: FormData) {
  const next = recoveryReturn(text(data, "next"));
  const cookieStore = await cookies();
  cookieStore.delete(RECOVERY_GRANT_COOKIE);
  cookieStore.delete(RECOVERY_REQUEST_COOKIE);
  let failed = false;
  try {
    const supabase = await createSupabaseServerClient();
    const { error } = await supabase.auth.signOut({ scope: "local" });
    failed = Boolean(error);
  } catch {
    // An unavailable service must not claim that the old session was replaced.
    failed = true;
  }
  if (failed) redirect(`/forgot-password?${new URLSearchParams({ next, error: "unavailable" })}`);
  redirect(`/forgot-password?${new URLSearchParams({ next })}`);
}
