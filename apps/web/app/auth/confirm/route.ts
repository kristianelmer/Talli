import type { EmailOtpType } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";

import { createSupabaseServerClient, hasSupabaseEnv } from "../../lib/supabase/server";
import { sanitizeInternalRedirect } from "../../lib/internal-redirect";

/**
 * Email-confirmation callback. Supabase redirects here from the confirmation
 * link with either a `token_hash` (verifyOtp flow) or a PKCE `code`
 * (exchangeCodeForSession flow). Either path establishes the session cookie,
 * so the owner is logged in without re-entering credentials, then lands on the
 * "email confirmed" page.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const next = sanitizeInternalRedirect(searchParams.get("next"), "/email-confirmed");
  const reauthenticate = searchParams.get("reauth") === "1";
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const code = searchParams.get("code");

  const failure = new URL(reauthenticate ? "/login" : "/verify-email", origin);
  if (reauthenticate) failure.searchParams.set("reauth", "1");
  failure.searchParams.set("next", next);
  failure.searchParams.set(
    "error",
    reauthenticate
      ? "Innloggingen kunne ikke fullføres. Prøv igjen."
      : "Bekreftelseslenken er ugyldig eller utløpt. Be om en ny nedenfor.",
  );

  if (!hasSupabaseEnv() || searchParams.has("error")) {
    return NextResponse.redirect(failure);
  }

  try {
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
  } catch {
    // An interrupted exchange must leave a usable recovery entry point.
  }

  return NextResponse.redirect(failure);
}
