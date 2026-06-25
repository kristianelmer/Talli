import Link from "next/link";

import { Banner, FormField, SubmitButton } from "../components/ui";
import { resendConfirmation } from "../actions";
import { hasSupabaseEnv } from "../lib/supabase/server";
import { ownerCopy } from "../lib/copy";

type VerifyEmailProps = {
  searchParams?: Promise<{ email?: string; error?: string; resent?: string }>;
};

export default async function VerifyEmailPage({ searchParams }: VerifyEmailProps) {
  const params = await searchParams;
  const c = ownerCopy.verifyEmail;
  const email = params?.email ?? "";
  return (
    <div className="authShell">
      <div className="authCard">
        <div className="appBrand">
          <span className="appBrandMark" aria-hidden="true" />
          <span>{ownerCopy.brand}</span>
        </div>
        <h1 className="authTitle">{c.title}</h1>
        <p className="authIntro">{c.intro}</p>
        {email ? (
          <p className="authEmail">
            <span className="cardLabel">{c.sentTo}</span> <strong>{email}</strong>
          </p>
        ) : null}

        {params?.resent ? <Banner variant="success">{c.resent}</Banner> : null}
        {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}

        <Banner variant="info" title={c.hintTitle}>
          {c.hint}
        </Banner>

        <form className="authForm" action={resendConfirmation}>
          {email ? <input type="hidden" name="email" value={email} /> : null}
          {!email ? (
            <FormField
              label={ownerCopy.auth.emailLabel}
              name="email"
              type="email"
              autoComplete="email"
              required
            />
          ) : null}
          <SubmitButton
            block
            variant="secondary"
            pendingLabel={c.resendPending}
            disabled={!hasSupabaseEnv()}
          >
            {c.resendCta}
          </SubmitButton>
        </form>

        <p className="authAlt">
          <Link href="/login">{c.backToLogin}</Link>
        </p>
      </div>
    </div>
  );
}
