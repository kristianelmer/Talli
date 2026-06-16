import {
  acknowledgeFilingReviewComment,
  activateBillingSubscription,
  addFilingOverride,
  addFilingReviewComment,
  acceptWorkspaceInvitation,
  confirmAuthorityPermission,
  confirmSimulatedRf1086Submission,
  createOpeningBalanceSetup,
  createWorkspace,
  generateRf1086Preview,
  importBankCsv,
  inviteWorkspaceReviewer,
  lockCompanyYear,
  markBillingRefundEligible,
  markBillingUnsupported,
  postManualJournal,
  recordAdminCost,
  recordDividendReceived,
  recordOwnerDividend,
  recordSharePurchase,
  recordShareSale,
  recordShareholderLoan,
  recordTaxSettlement,
  refreshAnnualReadinessSnapshots,
  resendWorkspaceInvitation,
  requestFilingPackagePayment,
  revokeWorkspaceInvitation,
  saveYearEndInterview,
  saveBillingAccount,
  signIn,
  signOut,
  signUp,
  uploadDocument,
} from "./actions";
import { productionBillingGate } from "./lib/billing";
import {
  authorityObligationLabel,
  authorityObligations,
  productionAuthorityGate,
} from "./lib/authority-permission";
import { buildDeadlineDashboard, deadlineStatusLabel } from "./lib/deadlines";
import { summarizeDividendReceivedAnnualImpact } from "./lib/dividend-received";
import { invitationStatus, reviewChecklistStatus } from "./lib/invitations";
import { estimateAnnualTax } from "./lib/tax-settlement";
import {
  getCurrentUser,
  hasSupabaseEnv,
  listAuthorityPermissions,
  listAnnualData,
  listBankTransactions,
  listBillingAccounts,
  listCompanyWorkspaces,
  listDocumentsForCompanies,
  listFilingPreviews,
  listFilingOverrides,
  listFilingReadinessSnapshots,
  listFilingReviewComments,
  listFilingSubmissions,
  listHoldingActions,
  listInvestmentPositions,
  listLedgerEntries,
  listNotificationOutbox,
  listOpeningSetups,
  listPeriodLocks,
  listWorkspaceInvitations,
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
  const { annualData } = user ? await listAnnualData(companies.map((company) => company.id)) : { annualData: [] };
  const { setups, shareholders } = user ? await listOpeningSetups(companies.map((company) => company.id)) : { setups: [], shareholders: [] };
  const { previews } = user ? await listFilingPreviews(companies.map((company) => company.id)) : { previews: [] };
  const { submissions } = user ? await listFilingSubmissions(companies.map((company) => company.id)) : { submissions: [] };
  const { overrides } = user ? await listFilingOverrides(companies.map((company) => company.id)) : { overrides: [] };
  const { readinessSnapshots } = user ? await listFilingReadinessSnapshots(companies.map((company) => company.id)) : { readinessSnapshots: [] };
  const { comments } = user ? await listFilingReviewComments(companies.map((company) => company.id)) : { comments: [] };
  const { authorityPermissions } = user ? await listAuthorityPermissions(companies.map((company) => company.id)) : { authorityPermissions: [] };
  const { invitations } = user ? await listWorkspaceInvitations(companies.map((company) => company.id)) : { invitations: [] };
  const { notifications } = user ? await listNotificationOutbox(companies.map((company) => company.id)) : { notifications: [] };
  const { billingAccounts } = user ? await listBillingAccounts(companies.map((company) => company.id)) : { billingAccounts: [] };
  const { transactions } = user ? await listBankTransactions(companies.map((company) => company.id)) : { transactions: [] };
  const { actions } = user ? await listHoldingActions(companies.map((company) => company.id)) : { actions: [] };
  const { positions } = user ? await listInvestmentPositions(companies.map((company) => company.id)) : { positions: [] };
  const { entries } = user ? await listLedgerEntries(companies.map((company) => company.id)) : { entries: [] };
  const { locks } = user ? await listPeriodLocks(companies.map((company) => company.id)) : { locks: [] };
  const primaryCompanyId = companies[0]?.id;
  const unmatchedTransactions = transactions.filter(
    (transaction) => !transaction.matched_entry_id && !transaction.matched_action_id && !transaction.accepted_warning,
  );
  const adminCostEntries = entries.filter((entry) => entry.entry_type === "admin_cost");
  const taxSettlementEntries = entries.filter((entry) => entry.entry_type === "tax_settlement");
  const taxSettlementActions = actions.filter((action) => action.action_type === "tax_settlement");
  const primaryShareholders = shareholders.filter((shareholder) => shareholder.company_id === primaryCompanyId);
  const dividendReceivedActions = actions.filter((action) => action.action_type === "dividend_received");
  const dividendAnnualImpact = summarizeDividendReceivedAnnualImpact(
    dividendReceivedActions.map((action) => ({
      action_type: action.action_type,
      payload: action.payload as { gross_amount?: number; taxable_add_back?: number },
    })),
  );
  const manualJournalEntries = entries.filter((entry) => entry.entry_type === "manual_journal");
  const manualJournalWarnings = manualJournalEntries.flatMap((entry) => entry.risk_flags ?? []);
  const taxEstimate = estimateAnnualTax({ ledgerEntries: entries, holdingActions: actions });
  const incomeYears = Array.from(
    new Set([
      ...setups.map((setup) => setup.income_year),
      ...previews.map((preview) => preview.income_year),
      ...overrides.map((override) => override.income_year),
      ...submissions.map((submission) => submission.income_year),
      ...transactions.map((transaction) => transaction.income_year),
      ...actions.map((action) => action.income_year),
      ...locks.map((lock) => lock.income_year),
    ]),
  ).sort((a, b) => b - a);
  const primaryIncomeYear = incomeYears[0] ?? 2025;
  const primaryBillingAccount = billingAccounts.find((account) => account.company_id === primaryCompanyId);
  const primaryReadinessSnapshots = readinessSnapshots.filter(
    (snapshot) => snapshot.company_id === primaryCompanyId && snapshot.income_year === primaryIncomeYear,
  );
  const primaryAnnualData = annualData.find(
    (item) => item.company_id === primaryCompanyId && item.income_year === primaryIncomeYear,
  );
  const primaryFilingReady = primaryReadinessSnapshots.some(
    (snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven" && snapshot.ready,
  );
  const primaryBillingGate = primaryBillingAccount ? productionBillingGate(primaryBillingAccount, primaryFilingReady) : null;
  const primaryAuthorityPermissions = authorityPermissions.filter((permission) => permission.company_id === primaryCompanyId);
  const primaryInvitations = invitations.filter((invitation) => invitation.company_id === primaryCompanyId);
  const primaryNotifications = notifications.filter((notification) => notification.company_id === primaryCompanyId);
  const reviewChecklist = reviewChecklistStatus(
    comments
      .filter((comment) => comment.company_id === primaryCompanyId)
      .map((comment) => ({ severity: comment.severity, acknowledged_by: comment.acknowledged_by })),
  );
  const deadlines = incomeYears.flatMap((incomeYear) => buildDeadlineDashboard({ incomeYear, submissions }));

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
                  <p className="eyebrow">Periodelås</p>
                  <h2>Steng inntektsår etter filing eller godkjenning.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={lockCompanyYear}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Årsak
                    <input name="reason" defaultValue="Filing fullført og arkivert" required />
                  </label>
                  <button className="primaryButton" type="submit">
                    Lås inntektsår
                  </button>
                </form>
                <div className="readinessGrid">
                  {locks.map((lock) => (
                    <div className="readinessItem" key={lock.id}>
                      <span>{lock.income_year}</span>
                      <strong data-status="ready">Låst</strong>
                      <p>{lock.reason}</p>
                      <p>Låst {new Date(lock.locked_at).toLocaleString("nb-NO")}</p>
                    </div>
                  ))}
                  {locks.length === 0 ? (
                    <div className="readinessItem">
                      <span>Periode</span>
                      <strong data-status="draft">Ingen lås</strong>
                      <p>Lås et inntektsår når filinggrunnlaget ikke lenger skal endres.</p>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">RF-1086</p>
                  <h2>Forhåndsvisning fra Python-motoren.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={inviteWorkspaceReviewer}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <span className="panelLabel">Inviter reviewer</span>
                  <label>
                    E-post
                    <input name="email" type="email" placeholder="reviewer@example.no" required />
                  </label>
                  <label>
                    Rolle
                    <select name="role" defaultValue="reviewer">
                      <option value="reviewer">Reviewer</option>
                      <option value="read_only">Read-only</option>
                    </select>
                  </label>
                  <button className="secondaryButton" type="submit">
                    Send invitasjon
                  </button>
                  <p>Krever fersk MFA/step-up. E-post legges i notification outbox.</p>
                </form>
                <form className="dataPanel formPanel widePanel" action={acceptWorkspaceInvitation}>
                  <span className="panelLabel">Godta invitasjon</span>
                  <label>
                    Invitasjonstoken
                    <input name="token" placeholder="Token fra e-postlenke" required />
                  </label>
                  <button className="secondaryButton" type="submit">
                    Godta tilgang
                  </button>
                </form>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Review checklist</span>
                    <strong data-status={reviewChecklist.readinessImpact === "hard_block" ? "blocked" : "advisory"}>
                      {reviewChecklist.readinessImpact === "hard_block" ? "Hard block" : "Advisory"}
                    </strong>
                    <p>{reviewChecklist.advisoryCount} advisory kommentarer, {reviewChecklist.acknowledgedAdvisoryCount} acknowledged.</p>
                    <p>{reviewChecklist.hardBlockCount} hard blocks må løses av systemregel eller ny kommentarstatus.</p>
                  </div>
                  <div className="readinessItem">
                    <span>Notification outbox</span>
                    <strong data-status={primaryNotifications.length ? "ready" : "draft"}>
                      {primaryNotifications.length} køet
                    </strong>
                    <p>Siste: {primaryNotifications[0]?.recipient_email ?? "Ingen invitasjonsmail køet."}</p>
                  </div>
                </div>
                <div className="readinessGrid">
                  {primaryInvitations.map((invitation) => {
                    const status = invitationStatus(invitation);
                    return (
                      <div className="readinessItem" key={invitation.id}>
                        <span>{invitation.role}</span>
                        <strong data-status={status === "pending" ? "warning" : status === "accepted" ? "ready" : "blocked"}>
                          {status}
                        </strong>
                        <p>{invitation.invited_email}</p>
                        <p>Utløper {new Date(invitation.expires_at).toLocaleDateString("nb-NO")}</p>
                        {status === "pending" ? (
                          <div className="inlineActions">
                            <form action={resendWorkspaceInvitation}>
                              <input name="companyId" type="hidden" value={primaryCompanyId} />
                              <input name="invitationId" type="hidden" value={invitation.id} />
                              <button className="secondaryButton" type="submit">Send på nytt</button>
                            </form>
                            <form action={revokeWorkspaceInvitation}>
                              <input name="companyId" type="hidden" value={primaryCompanyId} />
                              <input name="invitationId" type="hidden" value={invitation.id} />
                              <button className="secondaryButton" type="submit">Tilbakekall</button>
                            </form>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                <div className="readinessGrid">
                  {previews.map((preview) => {
                    const previewOverrides = overrides.filter(
                      (override) =>
                        override.preview_id === preview.id ||
                        (override.company_id === preview.company_id &&
                          override.income_year === preview.income_year &&
                          override.filing === preview.filing),
                    );
                    const hasBlockingOverride = previewOverrides.some((override) => override.risk_level === "block");
                    const displayStatus = hasBlockingOverride
                      ? "blocked"
                      : previewOverrides.length
                        ? "warning"
                        : preview.status;
                    return (
                        <div className="readinessItem" key={preview.id}>
                          <span>{preview.income_year}</span>
                          <strong data-status={displayStatus}>{preview.filing}</strong>
                          <p>Kilde: {preview.source}</p>
                          {preview.issues.map((issue) => (
                            <p key={issue.code}>{issue.message}</p>
                          ))}
                          <pre>{preview.preview}</pre>
                          <form className="confirmationPanel" action={addFilingOverride}>
                            <input name="previewId" type="hidden" value={preview.id} />
                            <label>
                              Felt
                              <input name="fieldTarget" placeholder="authority.field" required />
                            </label>
                            <label>
                              Gammel verdi
                              <input name="oldValue" placeholder="Systemverdi" />
                            </label>
                            <label>
                              Ny verdi
                              <input name="newValue" placeholder="Overstyrt verdi" />
                            </label>
                            <label>
                              Risiko
                              <select name="riskLevel" defaultValue="advisory">
                                <option value="advisory">Advisory</option>
                                <option value="warning">Warning</option>
                                <option value="block">Block</option>
                              </select>
                            </label>
                            <label>
                              Begrunnelse
                              <textarea name="reason" placeholder="Hvorfor trengs overstyring?" required />
                            </label>
                            <label>
                              <input name="ownerConfirmed" type="checkbox" required />
                              Jeg bekrefter at overstyringen skal vises i readiness og audit trail.
                            </label>
                            <button className="secondaryButton" type="submit">
                              Legg til overstyring
                            </button>
                          </form>
                          <div className="reviewList">
                            {previewOverrides.map((override) => (
                              <div className="reviewItem" key={override.id}>
                                <span>{override.risk_level}</span>
                                <p>
                                  {override.field_target}: {override.old_value || "(tom)"} -&gt; {override.new_value || "(tom)"}
                                </p>
                                <strong>{override.reason}</strong>
                              </div>
                            ))}
                          </div>
                          <form className="confirmationPanel" action={addFilingReviewComment}>
                            <input name="previewId" type="hidden" value={preview.id} />
                            <label>
                              Alvorlighet
                              <select name="severity" defaultValue="advisory">
                                <option value="advisory">Advisory</option>
                                <option value="hard_block">Hard block</option>
                              </select>
                            </label>
                            <label>
                              Kommentar
                              <textarea name="body" placeholder="Review-kommentar" required />
                            </label>
                            <button className="secondaryButton" type="submit">
                              Kommenter
                            </button>
                          </form>
                          <div className="reviewList">
                            {comments
                              .filter((comment) => comment.preview_id === preview.id)
                              .map((comment) => (
                                <div className="reviewItem" key={comment.id}>
                                  <span>{comment.severity}</span>
                                  <p>{comment.body}</p>
                                  <strong>{comment.acknowledged_at ? "Acknowledged" : "Åpen"}</strong>
                                  {comment.severity === "advisory" && !comment.acknowledged_at ? (
                                    <form action={acknowledgeFilingReviewComment}>
                                      <input name="commentId" type="hidden" value={comment.id} />
                                      <button className="secondaryButton" type="submit">
                                        Acknowledge
                                      </button>
                                    </form>
                                  ) : null}
                                </div>
                              ))}
                          </div>
                          {preview.status === "ready" && !hasBlockingOverride ? (
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
                    );
                  })}
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
                  <p className="eyebrow">Aksjonærlån</p>
                  <h2>Registrer støttet aksjonær- eller konsernlån.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={recordShareholderLoan}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Lånedato
                    <input name="loanDate" defaultValue="2025-07-01" required />
                  </label>
                  <label>
                    Beløp
                    <input name="amount" inputMode="decimal" defaultValue="20000" required />
                  </label>
                  <label>
                    Retning
                    <select name="direction" defaultValue="shareholder_to_company">
                      <option value="shareholder_to_company">Aksjonær til selskap</option>
                      <option value="company_to_corporate_shareholder">Selskap til selskapsaksjonær</option>
                      <option value="company_to_personal_shareholder">Selskap til personlig aksjonær</option>
                    </select>
                  </label>
                  <label>
                    Motpart
                    <input name="counterpartyName" defaultValue="Ola Nordmann" required />
                  </label>
                  <label>
                    Banktransaksjon
                    <select name="bankTransactionId" defaultValue="">
                      <option value="">Ingen bankmatch</option>
                      {unmatchedTransactions.map((transaction) => (
                        <option key={transaction.id} value={transaction.id}>
                          {transaction.transaction_date} {transaction.text} {Number(transaction.amount).toFixed(2)} kr
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Bilag
                    <select name="documentId" defaultValue="">
                      <option value="">Ingen bilagskobling</option>
                      {documents.map((document) => (
                        <option key={document.id} value={document.id}>
                          {document.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Dokumentstatus
                    <select name="documentStatus" defaultValue="attached">
                      <option value="attached">Vedlagt</option>
                      <option value="missing_accepted_warning">Mangler, akseptert varsel</option>
                      <option value="not_required">Ikke påkrevd</option>
                    </select>
                  </label>
                  <label>
                    <input name="interestModelled" type="checkbox" />
                    Rente er modellert
                  </label>
                  <label>
                    <input name="relatedPartySecurity" type="checkbox" />
                    Sikkerhet/garanti mellom nærstående
                  </label>
                  <button className="secondaryButton" type="submit">
                    Poster aksjonærlån
                  </button>
                </form>
              </section>

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Skatteoppgjør</p>
                  <h2>Beregn estimat og poster betaling eller refusjon.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={recordTaxSettlement}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Oppgjørsdato
                    <input name="settlementDate" defaultValue="2025-12-31" required />
                  </label>
                  <label>
                    Type
                    <select name="settlementType" defaultValue="payable">
                      <option value="payable">Betalbar skatt-estimat</option>
                      <option value="payment">Skatt betalt</option>
                      <option value="refund">Skatterefusjon mottatt</option>
                    </select>
                  </label>
                  <label>
                    Beløp
                    <input name="amount" inputMode="decimal" defaultValue={taxEstimate.estimatedTax || 1} required />
                  </label>
                  <label>
                    Banktransaksjon
                    <select name="bankTransactionId" defaultValue="">
                      <option value="">Ingen bankmatch</option>
                      {unmatchedTransactions.map((transaction) => (
                        <option key={transaction.id} value={transaction.id}>
                          {transaction.transaction_date} {transaction.text} {Number(transaction.amount).toFixed(2)} kr
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Bilag
                    <select name="documentId" defaultValue="">
                      <option value="">Ingen bilagskobling</option>
                      {documents.map((document) => (
                        <option key={document.id} value={document.id}>
                          {document.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Dokumentstatus
                    <select name="documentStatus" defaultValue="attached">
                      <option value="attached">Vedlagt</option>
                      <option value="missing_accepted_warning">Mangler, akseptert varsel</option>
                      <option value="not_required">Ikke påkrevd</option>
                    </select>
                  </label>
                  <button className="secondaryButton" type="submit">
                    Poster skatteoppgjør
                  </button>
                </form>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Estimert skatt</span>
                    <strong data-status={taxEstimate.status === "payable" ? "warning" : "ready"}>
                      {taxEstimate.estimatedTax.toFixed(2)} kr
                    </strong>
                    <p>Grunnlag: {taxEstimate.taxBasis.toFixed(2)} kr.</p>
                    <p>
                      Kostnader {taxEstimate.adminCosts.toFixed(2)} kr + fritaksmetoden {taxEstimate.fritaksmetodenAddBack.toFixed(2)} kr.
                    </p>
                  </div>
                  <div className="readinessItem">
                    <span>Oppgjør</span>
                    <strong data-status={taxSettlementActions.length ? "ready" : "draft"}>
                      {taxSettlementActions.length} postert
                    </strong>
                    <p>{taxSettlementEntries.length} skatteoppgjørsposteringer i ledger.</p>
                    <p>Arkivet inkluderer skatteoppgjør med bilag og ledger-lenke.</p>
                  </div>
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Billing</p>
                  <h2>Persistert abonnement og filingpakke uten betalingsleverandør.</h2>
                  <p>Billing-admin krever fersk MFA/step-up før server action får endre status.</p>
                </div>
                <div className="setupGrid">
                  <form className="dataPanel formPanel" action={saveBillingAccount}>
                    <span className="panelLabel">Prisplan</span>
                    <input name="companyId" type="hidden" value={primaryCompanyId} />
                    <label>
                      Plan
                      <select name="pricingPlan" defaultValue={primaryBillingAccount?.pricing_plan ?? "standard"}>
                        <option value="standard">Standard 49 kr / 499 kr</option>
                        <option value="founder">Founder 29 kr / 299 kr</option>
                      </select>
                    </label>
                    <label>
                      Founder-kull
                      <input
                        name="founderCohortNumber"
                        inputMode="numeric"
                        defaultValue={primaryBillingAccount?.founder_cohort_number ?? 1}
                      />
                    </label>
                    <button className="secondaryButton" type="submit">
                      Lagre billingkonto
                    </button>
                  </form>

                  <form className="dataPanel formPanel" action={requestFilingPackagePayment}>
                    <span className="panelLabel">Filingpakke</span>
                    <input name="companyId" type="hidden" value={primaryCompanyId} />
                    <label>
                      Inntektsår
                      <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                    </label>
                    <button className="primaryButton" type="submit">
                      Marker filingpakke betalt
                    </button>
                    <p>Kan bare lagres når readiness er klar og abonnementet er aktivt.</p>
                  </form>

                  <form className="dataPanel formPanel" action={markBillingUnsupported}>
                    <span className="panelLabel">No charge</span>
                    <input name="companyId" type="hidden" value={primaryCompanyId} />
                    <label>
                      Årsak
                      <input name="reason" defaultValue="Utenfor enkel holding-AS-løype" required />
                    </label>
                    <button className="secondaryButton" type="submit">
                      Marker utenfor støtte
                    </button>
                  </form>
                </div>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Pris</span>
                    <strong data-status={primaryBillingAccount ? "ready" : "draft"}>
                      {primaryBillingAccount
                        ? `${primaryBillingAccount.monthly_nok} kr/mnd + ${primaryBillingAccount.filing_package_nok} kr`
                        : "Ikke satt"}
                    </strong>
                    <p>
                      {primaryBillingAccount?.pricing_plan === "founder"
                        ? `Founder-kull ${primaryBillingAccount.founder_cohort_number}`
                        : "Standard eller ikke opprettet."}
                    </p>
                  </div>
                  <div className="readinessItem">
                    <span>Gate</span>
                    <strong data-status={primaryBillingGate?.allowed ? "ready" : primaryBillingGate?.chargeAllowed ? "warning" : "draft"}>
                      {primaryBillingGate?.status ?? "billing_account_missing"}
                    </strong>
                    <p>{primaryBillingGate?.message ?? "Opprett billingkonto før filingpakke."}</p>
                    <p>Readiness {primaryFilingReady ? "klar" : "ikke klar"} for {primaryIncomeYear}.</p>
                    {primaryBillingAccount && !primaryBillingAccount.subscription_active ? (
                      <form action={activateBillingSubscription}>
                        <input name="companyId" type="hidden" value={primaryCompanyId} />
                        <button className="secondaryButton" type="submit">
                          Marker abonnement aktivt
                        </button>
                      </form>
                    ) : null}
                  </div>
                  <div className="readinessItem">
                    <span>Refusjon</span>
                    <strong data-status={primaryBillingAccount?.refund_eligible ? "warning" : "draft"}>
                      {primaryBillingAccount?.refund_eligible ? "Refusjonsberettiget" : "Ingen refusjon"}
                    </strong>
                    <p>{primaryBillingAccount?.no_charge_reason ?? "Støttet sak kan markeres refusjonsberettiget etter Talli-feil."}</p>
                    {primaryBillingAccount?.filing_package_paid && primaryBillingAccount.supported_case ? (
                      <form action={markBillingRefundEligible}>
                        <input name="companyId" type="hidden" value={primaryCompanyId} />
                        <button className="secondaryButton" type="submit">
                          Marker refusjonsberettiget
                        </button>
                      </form>
                    ) : null}
                  </div>
                </div>
              </section>

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Year-end interview</p>
                  <h2>Strukturerte annual data for alle filingløp.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={saveYearEndInterview}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <label>
                    Årsverk
                    <input
                      name="annualFullTimeEquivalents"
                      inputMode="decimal"
                      min="0"
                      step="0.01"
                      defaultValue={primaryAnnualData?.annual_full_time_equivalents ?? 0}
                      required
                    />
                  </label>
                  {[
                    ["shares_owned_at_year_end", "Selskapet eide aksjer ved årsslutt"],
                    ["bought_or_sold_shares", "Kjøpte eller solgte aksjer"],
                    ["received_dividends", "Mottok utbytte"],
                    ["declared_owner_dividends", "Besluttet utbytte til eier"],
                    ["shareholder_loans", "Har aksjonær- eller konsernlån"],
                    ["paid_costs", "Betalte kostnader"],
                    ["bank_balance_confirmed", "Bankbalanse er kontrollert"],
                    ["has_unpaid_items", "Har ubetalte poster"],
                    ["general_meeting_approved", "Generalforsamling har godkjent årsregnskap"],
                    ["authority_to_submit_confirmed", "Eier bekrefter innsendingsrett"],
                  ].map(([name, label]) => (
                    <label className="checkboxLabel" key={name}>
                      <input
                        name={name}
                        type="checkbox"
                        defaultChecked={Boolean(primaryAnnualData?.answers?.[name as keyof typeof primaryAnnualData.answers])}
                      />
                      {label}
                    </label>
                  ))}
                  <button className="primaryButton" type="submit">
                    Lagre year-end answers
                  </button>
                </form>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Annual data</span>
                    <strong data-status={primaryAnnualData ? "ready" : "draft"}>
                      {primaryAnnualData ? "Lagret" : "Ikke lagret"}
                    </strong>
                    <p>No-activity: {primaryAnnualData?.no_activity_confirmed ? "Bekreftet" : "Ikke bekreftet"}</p>
                    <p>{primaryAnnualData?.confirmations.length ?? 0} strukturerte bekreftelser.</p>
                  </div>
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Annual loop readiness</p>
                  <h2>Separate gates for RF-1086, skattemelding og årsregnskap.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={refreshAnnualReadinessSnapshots}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <button className="primaryButton" type="submit">
                    Oppdater readiness
                  </button>
                </form>
                <div className="readinessGrid">
                  {authorityObligations.map((obligation) => {
                    const snapshot = primaryReadinessSnapshots.find((item) => item.obligation === obligation);
                    return (
                      <div className="readinessItem" key={obligation}>
                        <span>{authorityObligationLabel(obligation)}</span>
                        <strong data-status={snapshot?.status ?? "draft"}>{snapshot?.status ?? "Ikke vurdert"}</strong>
                        <p>{snapshot?.ready ? "Klar for neste produksjonsgate." : "Må oppdateres eller ryddes før filing."}</p>
                        <p>{snapshot?.hard_blocks.length ?? 0} harde blokkeringer.</p>
                        <p>{snapshot?.warnings.length ?? 0} åpne advarsler.</p>
                        <p>{snapshot?.accepted_warnings.length ?? 0} aksepterte advarsler.</p>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Innsendingsrett</p>
                  <h2>Bekreft hvem som kan sende inn per myndighetsplikt.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={confirmAuthorityPermission}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Plikt
                    <select name="obligation" defaultValue="aksjonaerregisteroppgaven">
                      {authorityObligations.map((obligation) => (
                        <option key={obligation} value={obligation}>
                          {authorityObligationLabel(obligation)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <input name="productionEnabled" type="checkbox" />
                    Intern produksjonsgate er aktivert for denne plikten
                  </label>
                  <button className="secondaryButton" type="submit">
                    Bekreft innsendingsrett
                  </button>
                  <p>Dette lagrer bare rettighetsbekreftelse. Ingen live innsending utføres her.</p>
                </form>
                <div className="readinessGrid">
                  {authorityObligations.map((obligation) => {
                    const gate = productionAuthorityGate(primaryAuthorityPermissions, obligation);
                    const permission = primaryAuthorityPermissions.find((item) => item.obligation === obligation);
                    return (
                      <div className="readinessItem" key={obligation}>
                        <span>{authorityObligationLabel(obligation)}</span>
                        <strong data-status={gate.allowed ? "ready" : permission ? "warning" : "draft"}>{gate.status}</strong>
                        <p>{gate.message}</p>
                        <p>
                          Bekreftet:{" "}
                          {permission?.confirmed_at ? new Date(permission.confirmed_at).toLocaleString("nb-NO") : "Nei"}
                        </p>
                      </div>
                    );
                  })}
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
                      <p>{submission.feedback_items.length} strukturerte tilbakemeldinger lagret.</p>
                      <p>Arkivreferanse: {submission.submitted_payload_ref?.payloadHash.slice(0, 12) ?? "Mangler"}</p>
                      <p>Bekreftet: {submission.preview_confirmed_at ? new Date(submission.preview_confirmed_at).toLocaleString("nb-NO") : "Nei"}</p>
                      <a href={`/archive/${submission.company_id}/${submission.income_year}/download`}>Eksporter arkiv</a>
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

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Frister</p>
                  <h2>Persistert filingstatus per inntektsår.</h2>
                </div>
                <div className="readinessGrid">
                  {deadlines.map((deadline) => (
                    <div className="readinessItem" key={`${deadline.incomeYear}-${deadline.filing}`}>
                      <span>{deadline.deadline}</span>
                      <strong data-status={deadline.status}>{deadlineStatusLabel(deadline.status)}</strong>
                      <p>
                        {deadline.filing} {deadline.incomeYear}
                      </p>
                      <p>{deadline.message}</p>
                    </div>
                  ))}
                  {deadlines.length === 0 ? (
                    <div className="readinessItem">
                      <span>Frister</span>
                      <strong data-status="draft">Ingen år</strong>
                      <p>Lås åpningsbalanse for å beregne filingfrister.</p>
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

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Bank og kostnader</p>
                  <h2>Importer bank og avstem enkel administrasjonskostnad.</h2>
                </div>
                <div className="setupGrid">
                  <form className="dataPanel formPanel" action={importBankCsv}>
                    <span className="panelLabel">Bank CSV</span>
                    <input name="companyId" type="hidden" value={primaryCompanyId} />
                    <label>
                      Inntektsår
                      <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                    </label>
                    <label>
                      CSV
                      <textarea
                        name="csvText"
                        defaultValue={"date,text,amount,balance\n2025-01-02,Opening,30000,30000\n2025-01-03,Bank fee,-50,29950"}
                        required
                      />
                    </label>
                    <button className="primaryButton" type="submit">
                      Importer bank
                    </button>
                  </form>

                  <form className="dataPanel formPanel" action={recordAdminCost}>
                    <span className="panelLabel">Administrasjonskostnad</span>
                    <input name="companyId" type="hidden" value={primaryCompanyId} />
                    <label>
                      Inntektsår
                      <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                    </label>
                    <label>
                      Banktransaksjon
                      <select name="bankTransactionId" required>
                        <option value="">Velg uavstemt utbetaling</option>
                        {unmatchedTransactions
                          .filter((transaction) => Number(transaction.amount) < 0)
                          .map((transaction) => (
                            <option key={transaction.id} value={transaction.id}>
                              {transaction.transaction_date} {transaction.text} {Number(transaction.amount).toFixed(2)} kr
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      Kategori
                      <select name="category" defaultValue="bank_fee">
                        <option value="bank_fee">Bankgebyr</option>
                        <option value="accounting_fee">Regnskap</option>
                        <option value="software">Programvare</option>
                        <option value="public_fee">Offentlig gebyr</option>
                        <option value="legal_advisory">Juridisk rådgivning</option>
                        <option value="other_admin_cost">Annen administrasjon</option>
                      </select>
                    </label>
                    <label>
                      Mottaker
                      <input name="payee" defaultValue="Bank" required />
                    </label>
                    <label>
                      Betalt dato
                      <input name="paidDate" defaultValue="2025-01-03" required />
                    </label>
                    <label>
                      Beløp
                      <input name="amount" inputMode="decimal" defaultValue="50" required />
                    </label>
                    <label>
                      Bilag
                      <select name="documentId" defaultValue="">
                        <option value="">Ingen bilagskobling</option>
                        {documents.map((document) => (
                          <option key={document.id} value={document.id}>
                            {document.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className="secondaryButton" type="submit">
                      Poster og avstem
                    </button>
                  </form>
                </div>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Bank</span>
                    <strong data-status={unmatchedTransactions.length ? "warning" : "ready"}>
                      {unmatchedTransactions.length} uavstemt
                    </strong>
                    <p>{transactions.length} transaksjoner importert.</p>
                  </div>
                  <div className="readinessItem">
                    <span>Kostnader</span>
                    <strong data-status={adminCostEntries.length ? "ready" : "draft"}>
                      {adminCostEntries.length} postert
                    </strong>
                    <p>Posterte administrasjonskostnader påvirker årsavslutning og arkivgrunnlag.</p>
                  </div>
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Mottatt utbytte</p>
                  <h2>Poster kvalifiserende utbytte fra porteføljeselskap.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={recordDividendReceived}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Utbetalende selskap
                    <input name="payingCompanyName" defaultValue="Portfolio AS" required />
                  </label>
                  <label>
                    Investering-ID
                    <input name="linkedInvestmentId" defaultValue="portfolio-as" required />
                  </label>
                  <label>
                    Vedtaksdato
                    <input name="declaredDate" defaultValue="2025-04-01" required />
                  </label>
                  <label>
                    Betalt dato
                    <input name="paidDate" defaultValue="2025-04-15" required />
                  </label>
                  <label>
                    Brutto beløp
                    <input name="grossAmount" inputMode="decimal" defaultValue="1000" required />
                  </label>
                  <label>
                    Skattebehandling
                    <select name="taxTreatment" defaultValue="fritaksmetoden">
                      <option value="fritaksmetoden">Fritaksmetoden</option>
                      <option value="outside_fritaksmetoden">Utenfor fritaksmetoden</option>
                      <option value="needs_accountant">Må vurderes</option>
                    </select>
                  </label>
                  <label>
                    Banktransaksjon
                    <select name="bankTransactionId" defaultValue="">
                      <option value="">Ingen bankmatch</option>
                      {unmatchedTransactions
                        .filter((transaction) => Number(transaction.amount) > 0)
                        .map((transaction) => (
                          <option key={transaction.id} value={transaction.id}>
                            {transaction.transaction_date} {transaction.text} {Number(transaction.amount).toFixed(2)} kr
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Bilag
                    <select name="documentId" defaultValue="">
                      <option value="">Ingen bilagskobling</option>
                      {documents.map((document) => (
                        <option key={document.id} value={document.id}>
                          {document.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Dokumentstatus
                    <select name="documentStatus" defaultValue="attached">
                      <option value="attached">Vedlagt</option>
                      <option value="missing_accepted_warning">Mangler, akseptert varsel</option>
                      <option value="not_required">Ikke påkrevd</option>
                    </select>
                  </label>
                  <button className="secondaryButton" type="submit">
                    Poster mottatt utbytte
                  </button>
                </form>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Utbytteinntekt</span>
                    <strong data-status={dividendReceivedActions.length ? "ready" : "draft"}>
                      {dividendAnnualImpact.dividendIncome.toFixed(2)} kr
                    </strong>
                    <p>{dividendReceivedActions.length} mottatte utbytter postert.</p>
                  </div>
                  <div className="readinessItem">
                    <span>Fritaksmetoden</span>
                    <strong data-status={dividendAnnualImpact.fritaksmetodenAddBack ? "warning" : "draft"}>
                      {dividendAnnualImpact.fritaksmetodenAddBack.toFixed(2)} kr
                    </strong>
                    <p>3 prosent inntektsføring for skattemelding/readiness.</p>
                  </div>
                </div>
              </section>

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Aksjekjøp</p>
                  <h2>Registrer kjøp og oppdater investeringsregister.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={recordSharePurchase}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Investering-ID
                    <input name="investmentKey" defaultValue="portfolio-as" required />
                  </label>
                  <label>
                    Selskap
                    <input name="investmentName" defaultValue="Portfolio AS" required />
                  </label>
                  <label>
                    Organisasjonsnummer
                    <input name="orgNumber" inputMode="numeric" placeholder="9 sifre" />
                  </label>
                  <label>
                    Investeringstype
                    <select name="investmentKind" defaultValue="norwegian_private_company">
                      <option value="norwegian_private_company">Norsk privat AS</option>
                      <option value="simple_listed_security">Børsnotert/annet</option>
                    </select>
                  </label>
                  <label>
                    Skattebehandling
                    <select name="taxTreatment" defaultValue="fritaksmetoden">
                      <option value="fritaksmetoden">Fritaksmetoden</option>
                      <option value="outside_fritaksmetoden">Utenfor fritaksmetoden</option>
                      <option value="needs_accountant">Må vurderes</option>
                    </select>
                  </label>
                  <label>
                    Kjøpsdato
                    <input name="acquisitionDate" defaultValue="2025-05-01" required />
                  </label>
                  <label>
                    Antall aksjer
                    <input name="shareCount" inputMode="decimal" defaultValue="100" required />
                  </label>
                  <label>
                    Kjøpsbeløp
                    <input name="purchaseAmount" inputMode="decimal" defaultValue="50000" required />
                  </label>
                  <label>
                    Banktransaksjon
                    <select name="bankTransactionId" defaultValue="">
                      <option value="">Ingen bankmatch</option>
                      {unmatchedTransactions
                        .filter((transaction) => Number(transaction.amount) < 0)
                        .map((transaction) => (
                          <option key={transaction.id} value={transaction.id}>
                            {transaction.transaction_date} {transaction.text} {Number(transaction.amount).toFixed(2)} kr
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Bilag
                    <select name="documentId" defaultValue="">
                      <option value="">Ingen bilagskobling</option>
                      {documents.map((document) => (
                        <option key={document.id} value={document.id}>
                          {document.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Dokumentstatus
                    <select name="documentStatus" defaultValue="attached">
                      <option value="attached">Vedlagt</option>
                      <option value="missing_accepted_warning">Mangler, akseptert varsel</option>
                      <option value="not_required">Ikke påkrevd</option>
                    </select>
                  </label>
                  <button className="secondaryButton" type="submit">
                    Poster aksjekjøp
                  </button>
                </form>
                <div className="readinessGrid">
                  {positions.map((position) => (
                    <div className="readinessItem" key={position.id}>
                      <span>{position.investment_key}</span>
                      <strong data-status="ready">{position.name}</strong>
                      <p>{Number(position.share_count).toFixed(2)} aksjer</p>
                      <p>Kostpris: {Number(position.cost_basis).toFixed(2)} kr</p>
                      <p>Bevegelser: {position.movements.length}</p>
                    </div>
                  ))}
                  {positions.length === 0 ? (
                    <div className="readinessItem">
                      <span>Register</span>
                      <strong data-status="draft">Ingen posisjoner</strong>
                      <p>Registrer første støttede aksjekjøp for å etablere investeringsregister.</p>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Aksjesalg</p>
                  <h2>Selg fra eksisterende investeringsposisjon.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={recordShareSale}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Posisjon
                    <select name="positionId" required>
                      <option value="">Velg posisjon</option>
                      {positions
                        .filter((position) => Number(position.share_count) > 0)
                        .map((position) => (
                          <option key={position.id} value={position.id}>
                            {position.name} ({Number(position.share_count).toFixed(2)} aksjer)
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Salgsdato
                    <input name="saleDate" defaultValue="2025-08-01" required />
                  </label>
                  <label>
                    Solgte aksjer
                    <input name="soldShareCount" inputMode="decimal" defaultValue="40" required />
                  </label>
                  <label>
                    Salgsproveny
                    <input name="proceeds" inputMode="decimal" defaultValue="30000" required />
                  </label>
                  <label>
                    Banktransaksjon
                    <select name="bankTransactionId" defaultValue="">
                      <option value="">Ingen bankmatch</option>
                      {unmatchedTransactions
                        .filter((transaction) => Number(transaction.amount) > 0)
                        .map((transaction) => (
                          <option key={transaction.id} value={transaction.id}>
                            {transaction.transaction_date} {transaction.text} {Number(transaction.amount).toFixed(2)} kr
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Bilag
                    <select name="documentId" defaultValue="">
                      <option value="">Ingen bilagskobling</option>
                      {documents.map((document) => (
                        <option key={document.id} value={document.id}>
                          {document.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Dokumentstatus
                    <select name="documentStatus" defaultValue="attached">
                      <option value="attached">Vedlagt</option>
                      <option value="missing_accepted_warning">Mangler, akseptert varsel</option>
                      <option value="not_required">Ikke påkrevd</option>
                    </select>
                  </label>
                  <button className="secondaryButton" type="submit">
                    Poster aksjesalg
                  </button>
                </form>
              </section>

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Eierutbytte</p>
                  <h2>Poster utbytte til aksjonær og opprett selskapsdokumenter.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={recordOwnerDividend}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Aksjonær
                    <select name="shareholderId" required>
                      <option value="">Velg aksjonær</option>
                      {primaryShareholders.map((shareholder) => (
                        <option key={shareholder.id} value={shareholder.id}>
                          {shareholder.name} ({shareholder.share_count} aksjer)
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Beslutningsdato
                    <input name="decisionDate" defaultValue="2025-06-01" required />
                  </label>
                  <label>
                    Betalingsdato
                    <input name="paymentDate" defaultValue="2025-06-15" required />
                  </label>
                  <label>
                    Totalutbytte
                    <input name="totalAmount" inputMode="decimal" defaultValue="1000" required />
                  </label>
                  <label>
                    Allokert beløp
                    <input name="allocationAmount" inputMode="decimal" defaultValue="1000" required />
                  </label>
                  <label>
                    Fri egenkapital
                    <input name="distributableEquity" inputMode="decimal" defaultValue="5000" required />
                  </label>
                  <label>
                    Likviditet etter betaling
                    <input name="liquidityAfterPayment" inputMode="decimal" defaultValue="1000" required />
                  </label>
                  <label>
                    Dokumentstatus
                    <select name="documentStatus" defaultValue="missing_accepted_warning">
                      <option value="attached">Vedlagt</option>
                      <option value="missing_accepted_warning">Mangler, akseptert varsel</option>
                      <option value="not_required">Ikke påkrevd</option>
                    </select>
                  </label>
                  <button className="secondaryButton" type="submit">
                    Poster eierutbytte
                  </button>
                </form>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Selskapsdokumenter</span>
                    <strong data-status={documents.some((document) => document.linked_to && document.document_type === "corporate_document") ? "warning" : "draft"}>
                      {documents.filter((document) => document.document_type === "corporate_document").length}
                    </strong>
                    <p>Styreforslag og generalforsamlingsprotokoll opprettes som arkivklare placeholders.</p>
                  </div>
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Manuell journal</p>
                  <h2>Escape hatch for sjeldne justeringer.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={postManualJournal}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue="2025" required />
                  </label>
                  <label>
                    Memo
                    <input name="memo" defaultValue="Manuell justering" required />
                  </label>
                  <label>
                    Konto debet
                    <input name="account0" defaultValue="7795" inputMode="numeric" required />
                  </label>
                  <label>
                    Beskrivelse debet
                    <input name="description0" defaultValue="Manuell kostnad" required />
                  </label>
                  <label>
                    Debet
                    <input name="debit0" inputMode="decimal" defaultValue="100" required />
                  </label>
                  <input name="credit0" type="hidden" value="0" />
                  <label>
                    Konto kredit
                    <input name="account1" defaultValue="1920" inputMode="numeric" required />
                  </label>
                  <label>
                    Beskrivelse kredit
                    <input name="description1" defaultValue="Bank" required />
                  </label>
                  <input name="debit1" type="hidden" value="0" />
                  <label>
                    Kredit
                    <input name="credit1" inputMode="decimal" defaultValue="100" required />
                  </label>
                  <label>
                    <input name="warningAccepted" type="checkbox" />
                    Jeg aksepterer at filing-sensitive kontoer kan redusere filing-tillit.
                  </label>
                  <button className="secondaryButton" type="submit">
                    Poster manuell journal
                  </button>
                </form>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Unstructured</span>
                    <strong data-status={manualJournalWarnings.length ? "warning" : "draft"}>
                      {manualJournalEntries.length} journaler
                    </strong>
                    <p>{manualJournalWarnings.length} filing-sensitive advarsler.</p>
                  </div>
                </div>
              </section>
            </>
          ) : null}
        </>
      )}

      <section id="sikkerhet" className="split">
        <div>
          <p className="eyebrow">Sikkerhet</p>
          <h2>Sensitive handlinger feiler lukket uten fersk MFA/step-up.</h2>
          <p>
            Produksjonsfiling, innsendingsrett, reviewer-invitasjon, rolleendring,
            arkiveksport, billing-admin og sletting krever server-side step-up-kontroll.
            Blokkerte og tillatte forsøk logges som audit events uten hemmeligheter.
          </p>
        </div>
        <ol className="actionList">
          <li>Supabase Auth-session</li>
          <li>Company membership med owner-rolle</li>
          <li>RLS-basert tenant-isolasjon</li>
          <li>Fersk MFA/step-up innen 15 minutter for sensitive handlinger</li>
          <li>Audit event for tillatt og blokkert sensitiv handling</li>
        </ol>
      </section>
    </main>
  );
}
