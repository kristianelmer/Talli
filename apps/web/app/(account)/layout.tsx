import { redirect } from "next/navigation";
import { AppNav } from "../(owner)/AppNav";
import { signOut } from "../actions";
import { ownerCopy } from "../lib/copy";
import { getOperatorContext, needsEmailVerification } from "../lib/supabase/server";

/** Account recovery and cancellation remain available without accepting new terms.
 * The billing page and its backend establish company ownership and fresh MFA.
 */
export default async function AccountLayout({ children }: { children: React.ReactNode }) {
  const { user, isOperator } = await getOperatorContext();
  // The page preserves its scoped return URL when it needs to establish a session.
  if (!user) return children;
  if (needsEmailVerification(user)) redirect("/verify-email");
  return <div className="appShell">
    <header className="appTopbar">
      <div className="appBrand"><span className="appBrandMark" aria-hidden="true" />
        <span>{ownerCopy.brand}</span></div>
      <AppNav isOperator={isOperator}>
        <span className="appUserEmail">{user.email}</span>
        <form action={signOut}><button className="btn btn--ghost" type="submit">
          {ownerCopy.nav.signOut}
        </button></form>
      </AppNav>
    </header>
    <main className="appMain">{children}</main>
  </div>;
}
