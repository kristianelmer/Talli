import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { isAuthSessionMissingError } from "@supabase/supabase-js";
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { hasAuthRecoveryEnv } from "../../lib/auth-recovery-context";
import {
  mintRecoveryIntent, readRecoveryIntent, RECOVERY_GRANT_COOKIE, RECOVERY_REQUEST_COOKIE,
  recoveryCookieOptions, recoverySigningSecret, verifierDigest,
} from "../../lib/auth-recovery-intent";
import { recoveryReturn, type AuthRecoveryError } from "../../lib/auth-recovery-presentation";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const next = recoveryReturn(params.get("next"));
  const origin = request.nextUrl.origin;
  const cookieStore = await cookies();
  const failure = (reason: AuthRecoveryError) => {
    const target = new URL("/forgot-password", origin);
    target.searchParams.set("next", next);
    target.searchParams.set("error", reason);
    const response = NextResponse.redirect(target);
    response.headers.set("Cache-Control", "private, no-store");
    response.headers.set("Referrer-Policy", "no-referrer");
    response.cookies.delete(RECOVERY_GRANT_COOKIE);
    return response;
  };
  if (!hasAuthRecoveryEnv()) return failure("unavailable");
  const code = params.get("code");
  const tokenHash = params.get("token_hash");
  if (params.has("error") || Boolean(code) === Boolean(tokenHash)
    || ["code", "token_hash", "type", "next"].some((name) => params.getAll(name).length > 1)
    || (tokenHash && params.get("type") !== "recovery")) return failure("invalid-link");

  const secret = recoverySigningSecret()!;
  const requestIntent = readRecoveryIntent(cookieStore.get(RECOVERY_REQUEST_COOKIE)?.value, secret);
  const existing = new Map(cookieStore.getAll().map(({ name, value }) => [name, value]));
  const verifier = [...existing].find(([name]) => name.endsWith("-code-verifier"))?.[1];
  if (code && (!requestIntent || requestIntent.kind !== "request" || !verifier
    || verifierDigest(verifier) !== requestIntent.verifierHash)) return failure("invalid-link");

  // Keep replacement cookies staged until the old and recovered identities agree.
  const pending = new Map<string, { name: string; value: string; options: CookieOptions }>();
  const supabase = createServerClient(process.env.SUPABASE_URL!, process.env.SUPABASE_ANON_KEY!, {
    cookies: {
      getAll: () => [...existing].map(([name, value]) => ({ name, value })),
      setAll(values) {
        for (const cookie of values) {
          existing.set(cookie.name, cookie.value);
          pending.set(cookie.name, cookie);
        }
      },
    },
  });
  try {
    const prior = await supabase.auth.getUser();
    // An outage or throttle does not establish that the browser is signed out.
    if (prior.error && !isAuthSessionMissingError(prior.error)) return failure("unavailable");
    const priorUser = prior.error ? null : prior.data.user;
    const result = code
      ? await supabase.auth.exchangeCodeForSession(code)
      : await supabase.auth.verifyOtp({ token_hash: tokenHash!, type: "recovery" });
    if (result.error || !result.data.session || !result.data.user
      || (code && (!("redirectType" in result.data) || result.data.redirectType !== "recovery"))) {
      return failure("invalid-link");
    }
    const userResult = await supabase.auth.getUser(result.data.session.access_token);
    const user = userResult.data.user;
    if (userResult.error || !user || user.id !== result.data.user.id) return failure("unavailable");
    if (priorUser && priorUser.id !== user.id) {
      await supabase.auth.signOut({ scope: "local" });
      return failure("wrong-account");
    }
    if (requestIntent?.kind === "request" && requestIntent.email !== user.email?.toLowerCase()) {
      await supabase.auth.signOut({ scope: "local" });
      return failure("wrong-recipient");
    }
    const claims = await supabase.auth.getClaims(result.data.session.access_token);
    const sessionId = claims.data?.claims.session_id;
    if (claims.error || claims.data?.claims.sub !== user.id || typeof sessionId !== "string") {
      return failure("unavailable");
    }
    const destination = code && requestIntent?.kind === "request" ? requestIntent.next : next;
    const target = new URL("/reset-password", origin);
    target.searchParams.set("next", destination);
    const response = NextResponse.redirect(target);
    response.headers.set("Cache-Control", "private, no-store");
    response.headers.set("Referrer-Policy", "no-referrer");
    for (const { name, value, options } of pending.values()) response.cookies.set(name, value, options);
    response.cookies.set(RECOVERY_GRANT_COOKIE, mintRecoveryIntent({
      kind: "grant", userId: user.id, sessionId, next: destination,
    }, secret), recoveryCookieOptions);
    response.cookies.delete(RECOVERY_REQUEST_COOKIE);
    return response;
  } catch {
    return failure("unavailable");
  }
}
