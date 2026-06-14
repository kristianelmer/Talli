import {
  confirmSimulatedRf1086Submission,
  createOpeningBalanceSetup,
  createWorkspace,
  generateRf1086Preview,
  signIn,
  signOut,
  signUp,
  uploadDocument,
} from "./actions";
import {
  getCurrentUser,
  hasSupabaseEnv,
  listCompanyWorkspaces,
  listDocumentsForCompanies,
  listFilingPreviews,
  listFilingSubmissions,
  listOpeningSetups,
} from "./lib/supabase/server";

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
  const { documents } = user ? await listDocumentsForCompanies(companies.map((company) => company.id)) : { documents: [] };
  const { setups, shareholders } = user ? await listOpeningSetups(companies.map((company) => company.id)) : { setups: [], shareholders: [] };
  const { previews } = user ? await listFilingPreviews(companies.map((company) => company.id)) : { previews: [] };
  const { submissions } = user ? await listFilingSubmissions(companies.map((company) => company.id)) : { submissions: [] };

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

          {companies.length > 0 ? (
            <>
              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Åpningsbalanse</p>
                  <h2>Lås første aksje- og bankgrunnlag.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={createOpeningBalanceSetup}>
                  <input name="companyId" type="hidden" value={companies[0].id} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Bankbalanse
                    <input name="bankBalance" inputMode="decimal" defaultValue="30000" required />
                  </label>
                  <label>
                    Aksjekapital
                    <input name="shareCapital" inputMode="decimal" defaultValue="30000" required />
                  </label>
                  <label>
                    Antall aksjer
                    <input name="shareCount" inputMode="numeric" defaultValue="100" required />
                  </label>
                  <label>
                    Pålydende
                    <input name="nominalValue" inputMode="decimal" defaultValue="300" required />
                  </label>
                  <label>
                    Aksjonærnavn
                    <input name="shareholderName" required />
                  </label>
                  <label>
                    Aksjonærtype
                    <select name="shareholderKind" defaultValue="norwegian_person">
                      <option value="norwegian_person">Norsk person</option>
                      <option value="norwegian_company">Norsk selskap</option>
                    </select>
                  </label>
                  <label>
                    Fødselsnummer
                    <input name="shareholderNationalId" inputMode="numeric" placeholder="11 sifre ved person" />
                  </label>
                  <label>
                    Organisasjonsnummer
                    <input name="shareholderOrgNumber" inputMode="numeric" placeholder="9 sifre ved selskap" />
                  </label>
                  <label>
                    Aksjer hos aksjonær
                    <input name="shareholderShareCount" inputMode="numeric" defaultValue="100" required />
                  </label>
                  <button className="primaryButton" type="submit">
                    Lås åpningsbalanse
                  </button>
                </form>
                <div className="readinessGrid">
                  {setups.map((setup) => (
                    <div className="readinessItem" key={setup.id}>
                      <span>{setup.income_year}</span>
                      <strong data-status="ready">{Number(setup.share_count)} aksjer</strong>
                      <p>Bank: {Number(setup.bank_balance).toFixed(2)} kr</p>
                      <p>Aksjekapital: {Number(setup.share_capital).toFixed(2)} kr</p>
                      <p>
                        Aksjonærer:{" "}
                        {shareholders
                          .filter((shareholder) => shareholder.setup_id === setup.id)
                          .map((shareholder) => `${shareholder.name} (${shareholder.share_count})`)
                          .join(", ")}
                      </p>
                      <form action={generateRf1086Preview}>
                        <input name="setupId" type="hidden" value={setup.id} />
                        <button className="secondaryButton" type="submit">
                          Generer RF-1086
                        </button>
                      </form>
                    </div>
                  ))}
                </div>
              </section>

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">RF-1086</p>
                  <h2>Forhåndsvisning fra Python-motoren.</h2>
                </div>
                <div className="readinessGrid">
                  {previews.map((preview) => (
                    <div className="readinessItem" key={preview.id}>
                      <span>{preview.income_year}</span>
                      <strong data-status={preview.status}>{preview.filing}</strong>
                      <p>Kilde: {preview.source}</p>
                      {preview.issues.map((issue) => (
                        <p key={issue.code}>{issue.message}</p>
                      ))}
                      <pre>{preview.preview}</pre>
                      {preview.status === "ready" ? (
                        <form className="confirmationPanel" action={confirmSimulatedRf1086Submission}>
                          <input name="previewId" type="hidden" value={preview.id} />
                          <label>
                            <input name="authorityConfirmed" type="checkbox" required />
                            Jeg bekrefter rett til å sende inn for selskapet.
                          </label>
                          <label>
                            <input name="previewConfirmed" type="checkbox" required />
                            Jeg har kontrollert endelig forhåndsvisning.
                          </label>
                          <button className="secondaryButton" type="submit">
                            Arkiver simulert kvittering
                          </button>
                        </form>
                      ) : null}
                    </div>
                  ))}
                  {previews.length === 0 ? (
                    <div className="readinessItem">
                      <span>RF-1086</span>
                      <strong data-status="draft">Ikke generert</strong>
                      <p>Generer fra låst åpningsbalanse for å se filingstatus.</p>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Simulert innsending</p>
                  <h2>Arkivert kvittering uten live Altinn-innsending.</h2>
                </div>
                <div className="readinessGrid">
                  {submissions.map((submission) => (
                    <div className="readinessItem" key={submission.id}>
                      <span>{submission.income_year}</span>
                      <strong data-status={submission.status}>{submission.receipt_id ?? "Ingen kvittering"}</strong>
                      <p>Kun simulering. Ingen live innsending er gjort.</p>
                      <p>{submission.calls.length} simulerte API-kall forberedt.</p>
                      <p>Bekreftet: {submission.preview_confirmed_at ? new Date(submission.preview_confirmed_at).toLocaleString("nb-NO") : "Nei"}</p>
                    </div>
                  ))}
                  {submissions.length === 0 ? (
                    <div className="readinessItem">
                      <span>Kvittering</span>
                      <strong data-status="draft">Ikke arkivert</strong>
                      <p>Generer klar RF-1086 og bekreft simulert innsending.</p>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Dokumenter</p>
                  <h2>Privat lagring med signert nedlasting.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={uploadDocument}>
                  <input name="companyId" type="hidden" value={companies[0].id} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Dokumenttype
                    <input name="documentType" defaultValue="bank_statement" required />
                  </label>
                  <label>
                    Knyttet til
                    <input name="linkedTo" defaultValue="aksjonærregisteroppgaven" required />
                  </label>
                  <label>
                    Fil
                    <input name="file" type="file" required />
                  </label>
                  <button className="primaryButton" type="submit">
                    Last opp dokument
                  </button>
                </form>
                <div className="table">
                  {documents.map((document) => (
                    <div className="tableRow" key={document.id}>
                      <span>{document.name}</span>
                      <span>{document.linked_to}</span>
                      <a href={`/documents/${document.id}/download`}>Signert nedlasting</a>
                    </div>
                  ))}
                </div>
              </section>
            </>
          ) : null}
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
