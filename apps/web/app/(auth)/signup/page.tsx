import Link from "next/link";
import { redirect } from "next/navigation";

import { Banner, FormField, SubmitButton } from "../../components/ui";
import { signUp } from "../../actions";
import { hasSupabaseEnv } from "../../lib/supabase/server";
import { ownerCopy } from "../../lib/copy";
import { readEligibilityContinuation } from "../../lib/eligibility-continuation";
import { sanitizeInternalRedirect } from "../../lib/internal-redirect";
import { GoogleSignInButton } from "../GoogleSignInButton";

type SignupProps = {
  searchParams?: Promise<{ error?: string; next?: string }>;
};

export default async function SignupPage({ searchParams }: SignupProps) {
  const params = await searchParams;
  const next = sanitizeInternalRedirect(params?.next);
  const continuation = await readEligibilityContinuation();
  if (!continuation && !next.startsWith("/invite/accept")) {
    redirect("/sjekk-selskapet");
  }
  return (
    <div className="authCard">
      <div className="appBrand">
        <span className="appBrandMark" aria-hidden="true" />
        <span>{ownerCopy.brand}</span>
      </div>
      <h1 className="authTitle">{ownerCopy.auth.signUpTitle}</h1>
      <p className="authIntro">{ownerCopy.auth.signUpIntro}</p>
      {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}
      {!hasSupabaseEnv() ? (
        <Banner variant="danger" title={ownerCopy.auth.unavailableTitle}>
          {ownerCopy.auth.unavailable}
        </Banner>
      ) : null}
      <form className="authForm" action={signUp}>
        <input name="next" type="hidden" value={next} />
        <FormField
          label={ownerCopy.auth.emailLabel}
          name="email"
          type="email"
          autoComplete="email"
          required
        />
        <FormField
          label={ownerCopy.auth.passwordLabel}
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          required
          helper={ownerCopy.auth.passwordHelp}
        />
        <SubmitButton block pendingLabel={ownerCopy.auth.signUpPending}>
          {ownerCopy.auth.signUpCta}
        </SubmitButton>
      </form>
      <p className="authDivider">{ownerCopy.auth.orDivider}</p>
      <GoogleSignInButton next={next} />
      <p className="authAlt">
        {ownerCopy.auth.haveAccount}{" "}
        <Link href={`/login?next=${encodeURIComponent(next)}`}>{ownerCopy.auth.toSignIn}</Link>
      </p>
      <p className="authLegal">
        <Link href="/vilkar">{ownerCopy.auth.termsLink}</Link>
        {" · "}
        <Link href="/personvern">{ownerCopy.auth.privacyLink}</Link>
      </p>
    </div>
  );
}
