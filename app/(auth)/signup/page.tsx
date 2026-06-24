import Link from "next/link";

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
      {params?.error ? <p className="bannerError">{params.error}</p> : null}
      {!hasSupabaseEnv() ? (
        <p className="bannerError">Supabase-miljøvariabler mangler.</p>
      ) : null}
      <form className="authForm" action={signUp}>
        <label className="field">
          E-post
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <label className="field">
          Passord
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={6}
            required
          />
        </label>
        <button className="btn btn--primary" type="submit">
          Opprett bruker
        </button>
      </form>
      <p className="authAlt">
        Har du allerede konto? <Link href="/login">Logg inn</Link>
      </p>
    </div>
  );
}
