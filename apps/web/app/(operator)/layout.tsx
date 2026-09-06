import Link from "next/link";

import { signOut } from "../actions";
import { getCurrentUser } from "../lib/supabase/server";

export default async function OperatorLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Each operator page guards its protected reads and retains its recovery URL.
  const user = await getCurrentUser();
  return (
    <div className="appShell">
      <header className="appTopbar">
        <div className="appBrand">
          <span className="appBrandMark" aria-hidden="true" />
          <span>Talli · Operatør</span>
        </div>
        <nav className="appNav" aria-label="Operatørmeny">
          <Link className="appNavLink" href="/dashboard">
            Til arbeidsflate
          </Link>
          <Link className="appNavLink" data-variant="operator" href="/operator">
            Operatør
          </Link>
          <Link className="appNavLink" data-variant="operator" href="/operator/marketing">
            Traktmåling
          </Link>
        </nav>
        <div className="appNavRight">
          <span className="cardLabel">{user?.email}</span>
          <form action={signOut}>
            <button className="btn btn--ghost" type="submit">
              Logg ut
            </button>
          </form>
        </div>
      </header>
      <main className="appMain">{children}</main>
    </div>
  );
}
