import { redirect } from "next/navigation";

import { sanitizeInternalRedirect } from "../lib/internal-redirect";
import {
  getCurrentUser,
  hasSupabaseEnv,
  needsEmailVerification,
} from "../lib/supabase/server";
import { OwnerMfa } from "./OwnerMfa";

type OwnerMfaPageProps = {
  searchParams?: Promise<{ next?: string; fresh?: string }>;
};

export default async function OwnerMfaPage({
  searchParams,
}: OwnerMfaPageProps) {
  const params = await searchParams;
  const returnTo = sanitizeInternalRedirect(params?.next, "/onboarding");
  const requireFreshChallenge = params?.fresh === "1";
  const resumePath = `/mfa?${requireFreshChallenge ? "fresh=1&" : ""}next=${encodeURIComponent(returnTo)}`;

  if (!hasSupabaseEnv()) {
    redirect(
      `/login?next=${encodeURIComponent(resumePath)}&error=${encodeURIComponent("Tjenesten er midlertidig utilgjengelig.")}`,
    );
  }
  const user = await getCurrentUser();
  if (!user) {
    redirect(`/login?next=${encodeURIComponent(resumePath)}`);
  }
  if (needsEmailVerification(user)) {
    redirect("/verify-email");
  }

  return (
    <main className="authShell">
      <OwnerMfa
        returnTo={returnTo}
        requireFreshChallenge={requireFreshChallenge}
        supabaseUrl={process.env.SUPABASE_URL!}
        supabaseAnonKey={process.env.SUPABASE_ANON_KEY!}
      />
    </main>
  );
}
