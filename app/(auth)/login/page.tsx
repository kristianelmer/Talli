import Link from "next/link";

import { Banner, FormField, SubmitButton } from "../../components/ui";
import { signIn } from "../../actions";
import { hasSupabaseEnv } from "../../lib/supabase/server";
import { ownerCopy } from "../../lib/copy";
import { GoogleSignInButton } from "../GoogleSignInButton";

type LoginProps = {
  searchParams?: Promise<{ error?: string }>;
};

export default async function LoginPage({ searchParams }: LoginProps) {
  const params = await searchParams;
  return (
    <div className="authCard">
      <div className="appBrand">
        <span className="appBrandMark" aria-hidden="true" />
        <span>{ownerCopy.brand}</span>
      </div>
      <h1 className="authTitle">{ownerCopy.auth.signInTitle}</h1>
      <p className="authIntro">{ownerCopy.auth.signInIntro}</p>
      {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}
      {!hasSupabaseEnv() ? (
        <Banner variant="danger" title={ownerCopy.auth.unavailableTitle}>
          {ownerCopy.auth.unavailable}
        </Banner>
      ) : null}
      <form className="authForm" action={signIn}>
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
          autoComplete="current-password"
          minLength={6}
          required
        />
        <SubmitButton block pendingLabel={ownerCopy.auth.signInPending}>
          {ownerCopy.auth.signInCta}
        </SubmitButton>
      </form>
      <p className="authDivider">{ownerCopy.auth.orDivider}</p>
      <GoogleSignInButton />
      <p className="authAlt">
        {ownerCopy.auth.noAccount}{" "}
        <Link href="/signup">{ownerCopy.auth.toSignUp}</Link>
      </p>
      <p className="authLegal">
        <Link href="/vilkar">{ownerCopy.auth.termsLink}</Link>
        {" · "}
        <Link href="/personvern">{ownerCopy.auth.privacyLink}</Link>
      </p>
    </div>
  );
}
