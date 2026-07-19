import type { EmailOtpType } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";

import { createSupabaseServerClient, hasSupabaseEnv } from "../../lib/supabase/server";

/** Only allow internal redirect targets to avoid an open-redirect. */
function sanitizeNext(value: string | null): string {
  if (value && value.startsWith("/") && !value.startsWith("//")) {
    return value;
  }
  return "/email-confirmed";
}

/**
 * Email-confirmation callback. Supabase redirects here from the confirmation
 * link with either a `token_hash` (verifyOtp flow) or a PKCE `code`
 * (exchangeCodeForSession flow). Either path establishes the session cookie,
 * so the owner is logged in without re-entering credentials, then lands on the
 * "email confirmed" page.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const next = sanitizeNext(searchParams.get("next"));
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const code = searchParams.get("code");

  const failure = new URL("/verify-email", origin);
  failure.searchParams.set(
    "error",
    "Bekreftelseslenken er ugyldig eller utløpt. Be om en ny nedenfor.",
  );

  if (!hasSupabaseEnv()) {
    return NextResponse.redirect(failure);
  }

  const supabase = await createSupabaseServerClient();

  if (tokenHash && type) {
    const { error } = await supabase.auth.verifyOtp({ type, token_hash: tokenHash });
    if (!error) {
      return NextResponse.redirect(new URL(next, origin));
    }
  } else if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(new URL(next, origin));
    }
  }

  return NextResponse.redirect(failure);
}
