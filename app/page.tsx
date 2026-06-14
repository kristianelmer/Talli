import { createWorkspace, signIn, signOut, signUp } from "./actions";
import { getCurrentUser, hasSupabaseEnv, listCompanyWorkspaces } from "./lib/supabase/server";

type HomeProps = {
  searchParams?: Promise<{ error?: string }>;
};

function supportBoundary(entityType: string) {
  if (entityType !== "AS") {
    return {
      status: "blocked",
      label: "Blokkert",
      message: "Talli støtter kun AS i første versjon.",
    };
  }
  return {
    status: "ready",
    label: "Klar",
    message: "Selskapet passer enkel holding AS-løypen.",
  };
}

export default async function Home({ searchParams }: HomeProps) {
  const params = await searchParams;
  const user = await getCurrentUser();
  const { companies, error } = user ? await listCompanyWorkspaces() : { companies: [], error: null };

  return (
    <main className="shell">
      <nav className="topbar" aria-label="Primær">
        <div className="brand">
          <span className="brandMark" aria-hidden="true" />
          <span>Talli</span>
        </div>
        <div className="navLinks">
          <a href="#arbeidsflate">Arbeidsflate</a>
          <a href="#opprett">Opprett</a>
          <a href="#sikkerhet">Sikkerhet</a>
        </div>
      </nav>

      <section className="workspace" id="arbeidsflate">
        <div className="intro">
          <p className="eyebrow">Supabase arbeidsflate</p>
          <h1>Holding workspace</h1>
          <p className="lede">
            Første ekte SaaS-snitt: innlogging, selskap, medlemskap, RLS og audit trail i
            Supabase. Demo-data brukes ikke for denne arbeidsflaten.
          </p>
          {params?.error ? <p className="errorText">{params.error}</p> : null}
          {!hasSupabaseEnv() ? (
            <p className="errorText">Supabase-miljøvariabler mangler.</p>
          ) : user ? (
            <form action={signOut}>
              <button className="secondaryButton" type="submit">
                Logg ut
              </button>
            </form>
          ) : null}
        </div>

        <aside className="statusPanel" aria-label="Innlogging">
          <div className="panelHeader">
            <span>Status</span>
            <strong>{user ? "Innlogget" : "Ikke innlogget"}</strong>
          </div>
          <div className="metricGrid">
            <div>
              <span>Selskaper</span>
              <strong>{companies.length}</strong>
            </div>
            <div>
              <span>DB</span>
              <strong>{error ? "Feil" : "OK"}</strong>
            </div>
            <div>
              <span>RLS</span>
              <strong>På</strong>
            </div>
          </div>
        </aside>
      </section>

      {!user ? (
        <section className="band" id="opprett">
          <div className="sectionHeader">
            <p className="eyebrow">Innlogging</p>
            <h2>Supabase Auth kreves før arbeidsflate.</h2>
          </div>
          <div className="setupGrid">
            <form className="dataPanel formPanel" action={signIn}>
              <span className="panelLabel">Logg inn</span>
              <label>
                E-post
                <input name="email" type="email" required />
              </label>
              <label>
                Passord
                <input name="password" type="password" minLength={6} required />
              </label>
              <button className="primaryButton" type="submit">
                Logg inn
              </button>
            </form>
            <form className="dataPanel formPanel" action={signUp}>
              <span className="panelLabel">Ny bruker</span>
              <label>
                E-post
                <input name="email" type="email" required />
              </label>
              <label>
                Passord
                <input name="password" type="password" minLength={6} required />
              </label>
              <button className="secondaryButton" type="submit">
                Opprett bruker
              </button>
            </form>
          </div>
        </section>
      ) : (
        <>
          <section className="band" id="opprett">
            <div className="sectionHeader">
              <p className="eyebrow">Selskapsarbeidsflate</p>
              <h2>Opprett AS-workspace i Supabase.</h2>
            </div>
            <form className="dataPanel formPanel widePanel" action={createWorkspace}>
              <label>
                Organisasjonsnummer
                <input name="orgNumber" inputMode="numeric" pattern="[0-9]{9}" required />
              </label>
              <button className="primaryButton" type="submit">
                Hent fra Brønnøysund og opprett
              </button>
              <p>
                Kun AS går videre. ENK, NUF, ASA og andre selskapsformer stoppes før
                arbeidsflate opprettes.
              </p>
            </form>
          </section>

          <section className="band mutedBand">
            <div className="sectionHeader">
              <p className="eyebrow">Persistente selskaper</p>
              <h2>Arbeidsflater leses fra Supabase.</h2>
            </div>
            <div className="readinessGrid">
              {companies.map((company) => {
                const boundary = supportBoundary(company.entity_type);
                return (
                  <div className="readinessItem" key={company.id}>
                    <span>{company.org_number}</span>
                    <strong data-status={boundary.status}>{company.name}</strong>
                    <p>{boundary.message}</p>
                    <p>
                      {company.address ? `${company.address}, ` : ""}
                      {company.postal_code} {company.city}
                    </p>
                    <p>Kilde: {company.source}. Innsendingsrett må fortsatt bekreftes i relevant myndighetsflyt.</p>
                  </div>
                );
              })}
              {companies.length === 0 ? (
                <div className="readinessItem">
                  <span>Ingen selskap</span>
                  <strong data-status="draft">Utkast</strong>
                  <p>Opprett første arbeidsflate for å teste DB, RLS og audit trail.</p>
                </div>
              ) : null}
            </div>
          </section>
        </>
      )}

      <section id="sikkerhet" className="split">
        <div>
          <p className="eyebrow">Prototype-grense</p>
          <h2>JSON/demo state er ikke produktstien.</h2>
          <p>
            Denne siden bruker Supabase Auth, RLS-beskyttede tabeller og persistente
            medlemskap for selskap. Neste slice bygger Brønnøysund-oppslag på samme sti.
          </p>
        </div>
        <ol className="actionList">
          <li>Supabase Auth-session</li>
          <li>Company membership med owner-rolle</li>
          <li>RLS-basert tenant-isolasjon</li>
          <li>Audit event for opprettet arbeidsflate</li>
        </ol>
      </section>
    </main>
  );
}
