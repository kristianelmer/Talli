import Link from "next/link";
import { redirect } from "next/navigation";

import { Banner, FormField, SubmitButton } from "../../components/ui";
import { signIn } from "../../actions";
import { getCurrentUser, hasSupabaseEnv, needsEmailVerification } from "../../lib/supabase/server";
import { ownerCopy } from "../../lib/copy";
import { sanitizeInternalRedirect } from "../../lib/internal-redirect";
import { GoogleSignInButton } from "../GoogleSignInButton";

type LoginProps = {
  searchParams?: Promise<{ error?: string; next?: string; reauth?: string }>;
};

export default async function LoginPage({ searchParams }: LoginProps) {
  const params = await searchParams;
  const next = sanitizeInternalRedirect(params?.next);
  const reauthenticate = params?.reauth === "1";
  if (hasSupabaseEnv()) {
    const user = await getCurrentUser();
    if (user) {
      if (needsEmailVerification(user)) redirect("/verify-email");
      // The backend can reject a session Supabase still recognizes. An
      // explicit recovery visit must allow the owner to replace that session.
      if (!reauthenticate) redirect("/dashboard");
    }
  }
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
        <input name="next" type="hidden" value={next} />
        {reauthenticate ? <input name="reauth" type="hidden" value="1" /> : null}
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
      <GoogleSignInButton next={next} reauthenticate={reauthenticate} />
      <p className="authAlt">
        {ownerCopy.auth.noAccount}{" "}
        <Link href={`/signup?next=${encodeURIComponent(next)}`}>{ownerCopy.auth.toSignUp}</Link>
      </p>
      <p className="authLegal">
        <Link href="/vilkar">{ownerCopy.auth.termsLink}</Link>
        {" · "}
        <Link href="/personvern">{ownerCopy.auth.privacyLink}</Link>
      </p>
    </div>
  );
}
