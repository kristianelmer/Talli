import Link from "next/link";

import { Banner, FormField, SubmitButton } from "../../components/ui";
import { signUp } from "../../actions";
import { hasSupabaseEnv } from "../../lib/supabase/server";

type SignupProps = {
  searchParams?: Promise<{ error?: string }>;
};

export default async function SignupPage({ searchParams }: SignupProps) {
  const params = await searchParams;
  return (
    <div className="authCard">
      <div className="appBrand">
        <span className="appBrandMark" aria-hidden="true" />
        <span>Talli</span>
      </div>
      <h1 className="authTitle">Opprett bruker</h1>
      <p className="authIntro">Kom i gang med holdingselskapets årsoppgjør.</p>
      {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}
      {!hasSupabaseEnv() ? (
        <Banner variant="danger" title="Konfigurasjon mangler">
          Supabase-miljøvariabler mangler.
        </Banner>
      ) : null}
      <form className="authForm" action={signUp}>
        <FormField
          label="E-post"
          name="email"
          type="email"
          autoComplete="email"
          required
        />
        <FormField
          label="Passord"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={6}
          required
          helper="Minst 6 tegn."
        />
        <SubmitButton block pendingLabel="Oppretter …">
          Opprett bruker
        </SubmitButton>
      </form>
      <p className="authAlt">
        Har du allerede konto? <Link href="/login">Logg inn</Link>
      </p>
    </div>
  );
}
