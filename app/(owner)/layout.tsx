import Link from "next/link";
import { redirect } from "next/navigation";

import { signOut } from "../actions";
import { getOperatorContext } from "../lib/supabase/server";
import { ownerCopy } from "../lib/copy";

export default async function OwnerLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { user, isOperator } = await getOperatorContext();
  if (!user) {
    redirect("/login");
  }
  return (
    <div className="appShell">
      <header className="appTopbar">
        <div className="appBrand">
          <span className="appBrandMark" aria-hidden="true" />
          <span>{ownerCopy.brand}</span>
        </div>
        <nav className="appNav" aria-label="Hovedmeny">
          <Link className="appNavLink" href="/dashboard">
            {ownerCopy.nav.overview}
          </Link>
          <Link className="appNavLink" href="/actions">
            {ownerCopy.nav.actions}
          </Link>
          <Link className="appNavLink" href="/year-end">
            {ownerCopy.nav.yearEnd}
          </Link>
          <Link className="appNavLink" href="/filing">
            {ownerCopy.nav.filing}
          </Link>
          <Link className="appNavLink" href="/workspace">
            {ownerCopy.nav.workspace}
          </Link>
          {isOperator ? (
            <Link className="appNavLink" data-variant="operator" href="/operator">
              {ownerCopy.nav.operator}
            </Link>
          ) : null}
        </nav>
        <div className="appNavRight">
          <span className="cardLabel">{user.email}</span>
          <form action={signOut}>
            <button className="btn btn--ghost" type="submit">
              {ownerCopy.nav.signOut}
            </button>
          </form>
        </div>
      </header>
      <main className="appMain">{children}</main>
    </div>
  );
}
