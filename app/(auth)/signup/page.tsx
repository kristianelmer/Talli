import Link from "next/link";

import { Banner, FormField, SubmitButton } from "../../components/ui";
import { signUp } from "../../actions";
import { hasSupabaseEnv } from "../../lib/supabase/server";
import { ownerCopy } from "../../lib/copy";
import { GoogleSignInButton } from "../GoogleSignInButton";

type SignupProps = {
  searchParams?: Promise<{ error?: string }>;
};

export default async function SignupPage({ searchParams }: SignupProps) {
  const params = await searchParams;
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
          minLength={6}
          required
          helper={ownerCopy.auth.passwordHelp}
        />
        <SubmitButton block pendingLabel={ownerCopy.auth.signUpPending}>
          {ownerCopy.auth.signUpCta}
        </SubmitButton>
      </form>
      <p className="authDivider">{ownerCopy.auth.orDivider}</p>
      <GoogleSignInButton />
      <p className="authAlt">
        {ownerCopy.auth.haveAccount}{" "}
        <Link href="/login">{ownerCopy.auth.toSignIn}</Link>
      </p>
    </div>
  );
}
