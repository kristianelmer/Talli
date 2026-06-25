import { redirect } from "next/navigation";

import { signOut } from "../actions";
import { getOperatorContext } from "../lib/supabase/server";
import { ownerCopy } from "../lib/copy";
import { AppNav } from "./AppNav";

export default async function OwnerLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { user, isOperator } = await getOperatorContext();
  if (!user) {
    redirect("/login");
  }
  if (!user.email_confirmed_at) {
    redirect("/verify-email");
  }
  return (
    <div className="appShell">
      <header className="appTopbar">
        <div className="appBrand">
          <span className="appBrandMark" aria-hidden="true" />
          <span>{ownerCopy.brand}</span>
        </div>
        <AppNav isOperator={isOperator}>
          <span className="appUserEmail">{user.email}</span>
          <form action={signOut}>
            <button className="btn btn--ghost" type="submit">
              {ownerCopy.nav.signOut}
            </button>
          </form>
        </AppNav>
      </header>
      <main className="appMain">{children}</main>
    </div>
  );
}
