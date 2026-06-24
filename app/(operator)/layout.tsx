import Link from "next/link";
import { redirect } from "next/navigation";

import { signOut } from "../actions";
import { getOperatorContext } from "../lib/supabase/server";

export default async function OperatorLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { user, isOperator } = await getOperatorContext();
  if (!user) {
    redirect("/login");
  }
  if (!isOperator) {
    redirect("/dashboard");
  }
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
        </nav>
        <div className="appNavRight">
          <span className="cardLabel">{user.email}</span>
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
