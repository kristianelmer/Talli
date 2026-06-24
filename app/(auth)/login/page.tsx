import Link from "next/link";

import { Banner, FormField, SubmitButton } from "../../components/ui";
import { signIn } from "../../actions";
import { hasSupabaseEnv } from "../../lib/supabase/server";

type LoginProps = {
  searchParams?: Promise<{ error?: string }>;
};

export default async function LoginPage({ searchParams }: LoginProps) {
  const params = await searchParams;
  return (
    <div className="authCard">
      <div className="appBrand">
        <span className="appBrandMark" aria-hidden="true" />
        <span>Talli</span>
      </div>
      <h1 className="authTitle">Logg inn</h1>
      <p className="authIntro">Holding-først årsrapportering for enkle AS.</p>
      {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}
      {!hasSupabaseEnv() ? (
        <Banner variant="danger" title="Konfigurasjon mangler">
          Supabase-miljøvariabler mangler.
        </Banner>
      ) : null}
      <form className="authForm" action={signIn}>
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
          autoComplete="current-password"
          minLength={6}
          required
        />
        <SubmitButton block pendingLabel="Logger inn …">
          Logg inn
        </SubmitButton>
      </form>
      <p className="authAlt">
        Ny her? <Link href="/signup">Opprett bruker</Link>
      </p>
    </div>
  );
}
