import { redirect } from "next/navigation";

import { getCurrentUser, hasSupabaseEnv, needsEmailVerification } from "../lib/supabase/server";

export default async function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  if (hasSupabaseEnv()) {
    const user = await getCurrentUser();
    if (user) {
      // A signed-in but unconfirmed owner belongs at the verification gate,
      // not in the app.
      if (needsEmailVerification(user)) {
        redirect("/verify-email");
      }
      redirect("/dashboard");
    }
  }
  return <div className="authShell">{children}</div>;
}
