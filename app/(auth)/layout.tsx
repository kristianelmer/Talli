import { redirect } from "next/navigation";

import { getCurrentUser, hasSupabaseEnv } from "../lib/supabase/server";

export default async function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  if (hasSupabaseEnv()) {
    const user = await getCurrentUser();
    if (user) {
      // A signed-in but unconfirmed owner belongs at the verification gate,
      // not in the app.
      if (!user.email_confirmed_at) {
        redirect("/verify-email");
      }
      redirect("/dashboard");
    }
  }
  return <div className="authShell">{children}</div>;
}
