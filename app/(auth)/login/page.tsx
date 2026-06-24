import Link from "next/link";

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
      {params?.error ? <p className="bannerError">{params.error}</p> : null}
      {!hasSupabaseEnv() ? (
        <p className="bannerError">Supabase-miljøvariabler mangler.</p>
      ) : null}
      <form className="authForm" action={signIn}>
        <label className="field">
          E-post
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <label className="field">
          Passord
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            minLength={6}
            required
          />
        </label>
        <button className="btn btn--primary" type="submit">
          Logg inn
        </button>
      </form>
      <p className="authAlt">
        Ny her? <Link href="/signup">Opprett bruker</Link>
      </p>
    </div>
  );
}
