import { redirect } from "next/navigation";

import { getCurrentUser, hasSupabaseEnv } from "../lib/supabase/server";

export default async function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  if (hasSupabaseEnv()) {
    const user = await getCurrentUser();
    if (user) {
      redirect("/dashboard");
    }
  }
  return <div className="authShell">{children}</div>;
}
