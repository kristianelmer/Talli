import { redirect } from "next/navigation";
import { createSupabaseServerClient, hasSupabaseEnv } from "../../lib/supabase/server";
import { MfaPanel } from "./MfaPanel";

export const dynamic = "force-dynamic";

export default async function MfaPage() {
  if (!hasSupabaseEnv()) redirect("/?error=Supabase%20env%20mangler");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/?error=Innlogging%20kreves");

  const [{ data: factors, error: factorError }, { data: assurance, error: assuranceError }] = await Promise.all([
    supabase.auth.mfa.listFactors(),
    supabase.auth.mfa.getAuthenticatorAssuranceLevel(),
  ]);
  if (factorError || assuranceError) {
    return (
      <main className="shell">
        <section className="band">
          <p className="errorText">Kunne ikke lese MFA-status. Prøv igjen senere.</p>
          <a className="secondaryButton" href="/">Tilbake</a>
        </section>
      </main>
    );
  }

  const verifiedFactors = factors.totp.map((factor) => ({
    id: factor.id,
    label: factor.friendly_name || "TOTP authenticator",
  }));

  return (
    <main className="shell">
      <nav className="topbar" aria-label="Primær">
        <a className="brand" href="/"><span className="brandMark" aria-hidden="true" />Talli</a>
      </nav>
      <section className="band">
        <div className="sectionHeader">
          <p className="eyebrow">Sikkerhet</p>
          <h1>MFA og fersk step-up</h1>
          <p className="lede">TOTP-verifisering beskytter innsendingsrett, arkiveksport, billing og produksjonsfiling.</p>
        </div>
        <MfaPanel verifiedFactors={verifiedFactors} currentLevel={assurance.currentLevel ?? "aal1"} />
      </section>
    </main>
  );
}
