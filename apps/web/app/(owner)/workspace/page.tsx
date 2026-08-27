import { randomUUID } from "node:crypto";
import Link from "next/link";

import {
  acknowledgeFilingReviewComment,
  activateBillingSubscription,
  addFilingOverride,
  addFilingReviewComment,
  acceptWorkspaceInvitation,
  cancelBillingSubscription,
  completeCompanyDeletionRecord,
  confirmAuthorityPermission,
  confirmSimulatedRf1086Submission,
  createOpeningBalanceSetup,
  generateRf1086Preview,
  importBankCsv,
  inviteWorkspaceReviewer,
  lockCompanyYear,
  markBillingRefundEligible,
  markBillingUnsupported,
  postManualJournal,
  queueDeadlineReminders,
  recordAdminCost,
  recordAnnualAccountsTt02Evidence,
  recordAuthorityTestEvidence,
  recordCompanyTaxReturnTt02Evidence,
  recordDividendReceived,
  recordLaunchSignoff,
  recordOwnerDividendPayment,
  recordSharePurchase,
  recordShareSale,
  recordShareholderLoan,
  recordTaxSettlement,
  refreshAnnualReadinessSnapshots,
  recoverWorkspaceInvitationSideEffects,
  resendWorkspaceInvitation,
  administerWorkspaceMembership,
  requestCompanyCancellation,
  resumeCompanyCancellation,
  requestFilingPackagePayment,
  revokeWorkspaceInvitation,
  saveYearEndInterview,
  saveBillingAccount,
  signIn,
  signOut,
  signUp,
  uploadDocument,
} from "../../actions";
import { productionBillingGate } from "../../lib/billing";
import { buildCancellationLifecycle, cancellationStatusLabel } from "../../lib/cancellation";
import {
  authorityTestEvidenceGate,
  authorityTestEvidenceGateStatusLabel,
  authorityTestRunStatusLabel,
} from "../../lib/authority-test-evidence";
import {
  authorityObligationLabel,
  authorityObligations,
  authorityPermissionGateStatusLabel,
  productionAuthorityGate,
} from "../../lib/authority-permission";
import { buildLaunchSignoffGate, launchSignoffKeys, launchSignoffLabel } from "../../lib/launch-signoff";
import { buildDeadlineDashboard, buildDeadlineReminderPlan, deadlineStatusLabel, defaultReminderPreferences } from "../../lib/deadlines";
import { summarizeDividendReceivedAnnualImpact } from "../../lib/dividend-received";
import {
  deriveOpenDividendPayable,
  validateOwnerDividendPaymentInput,
} from "../../lib/owner-dividend-payment";
import { invitationStatus, reviewChecklistStatus } from "../../lib/invitations";
import { preProductionDirectFilingCopy, requiredNonAffiliationCopy } from "../../lib/launch-copy";
import { estimateAnnualTax } from "../../lib/tax-settlement";
import {
  getCurrentUser,
  hasSupabaseEnv,
  listAuthorityPermissions,
  listAuthorityTestRuns,
  listAnnualData,
  listBankTransactions,
  listBillingAccounts,
  listBillingPaymentEvents,
  listDocumentsForCompanies,
  listFilingPreviews,
  listFilingOverrides,
  listFilingReadinessSnapshots,
  listFilingReviewComments,
  listFilingSubmissions,
  listHoldingActions,
  listInvestmentPositions,
  listLaunchSignoffs,
  listLedgerEntries,
  listNotificationOutbox,
  listOpeningSetups,
  listPeriodLocks,
  searchOperatorSupportDashboard,
} from "../../lib/supabase/server";
import { loadWorkspaceData } from "../../lib/workspace-data";
import { ownerCopy } from "../../lib/copy";
import { buildWorkspaceSubmissionPresentation } from "./_submission-presentation";
import { loadPendingCancellationOperation } from "../../lib/cancellation-operation-state";

type WorkspaceProps = {
  searchParams?: Promise<{
    error?: string;
    operatorOrg?: string;
    dividendPayment?: string;
    recovery?: string;
    lockOperationId?: string;
    manualOperationId?: string;
    newYearOperationId?: string;
  }>;
};

export default async function WorkspacePage({ searchParams }: WorkspaceProps) {
  const params = await searchParams;
  const pendingCancellationOperation = await loadPendingCancellationOperation();
  const data = await loadWorkspaceData();
  const {
    user,
    error,
    cancellationLifecycleError,
    companies,
    documents,
    annualData,
    setups,
    shareholders,
    previews,
    submissions,
    overrides,
    readinessSnapshots,
    comments,
    authorityPermissions,
    authorityTestRuns,
    invitations,
    memberships,
    notifications,
    cancellations,
    billingAccounts,
    billingPaymentEvents,
    transactions,
    actions,
    positions,
    entries,
    locks,
    corporateDecisions,
    corporateDocumentSets,
    corporateDocumentEvents,
    corporateDecisionFinalizations,
    primaryCompanyId,
    unmatchedTransactions,
    adminCostEntries,
    taxSettlementEntries,
    taxSettlementActions,
    dividendReceivedActions,
    dividendAnnualImpact,
    manualJournalEntries,
    manualJournalWarnings,
    taxEstimate,
    incomeYears,
    primaryIncomeYear,
    primaryBillingAccount,
    primaryBillingEvents,
    primaryReadinessSnapshots,
    primaryAnnualData,
    primaryFilingReady,
    primaryBillingGate,
    primaryAuthorityPermissions,
    primaryAuthorityTestRuns,
    primaryInvitations,
    primaryNotifications,
    primaryCancellation,
    cancellationLifecycle,
    reviewChecklist,
    deadlines,
    deadlineReminderPlan,
    deadlineReminderPreferences,
  } = data;
  const ownerDividendPayables = corporateDecisionFinalizations.flatMap((finalization) => {
    if (finalization.finalization_kind !== "owner_dividend_declared") return [];
    const decision = corporateDecisions.find((candidate) => candidate.id === finalization.decision_id);
    const documentSet = corporateDocumentSets.find((candidate) => candidate.decision_id === finalization.decision_id);
    if (!decision || !documentSet) return [];
    try {
      return [deriveOpenDividendPayable({
        decision: decision as Parameters<typeof deriveOpenDividendPayable>[0]["decision"],
        documentSet,
        finalization,
        events: corporateDocumentEvents.filter((event) => event.decision_id === decision.id),
      })];
    } catch {
      return [];
    }
  }).filter((payable) => payable.companyId === primaryCompanyId);
  const eligibleDividendTransactions = (payable: (typeof ownerDividendPayables)[number]) =>
    transactions.filter((transaction) => {
      if (transaction.matched_entry_id || transaction.matched_action_id) return false;
      try {
        validateOwnerDividendPaymentInput({ payable, transaction });
        return true;
      } catch {
        return false;
      }
    });
  const submissionPresentation = buildWorkspaceSubmissionPresentation({
    submissions,
    authorityTestRuns: primaryAuthorityTestRuns,
  });
  return (
    <>
      <section className="band mutedBand">
        <div className="sectionHeader">
          <p className="eyebrow">{ownerCopy.workspace.boundaryEyebrow}</p>
          <h1>{ownerCopy.workspace.boundaryTitle}</h1>
        </div>
        <div className="readinessGrid">
          <div className="readinessItem">
            <span>{ownerCopy.workspace.authorities}</span>
            <strong data-status="warning">
              {ownerCopy.workspace.authoritiesValue}
            </strong>
            <p>{requiredNonAffiliationCopy}</p>
          </div>
          <div className="readinessItem">
            <span>{ownerCopy.workspace.directFiling}</span>
            <strong data-status="draft">
              {ownerCopy.workspace.directFilingValue}
            </strong>
            <p>{preProductionDirectFilingCopy}</p>
          </div>
        </div>
      </section>

      <section className="workspace" id="arbeidsflate">
        <div className="intro">
          <p className="eyebrow">{ownerCopy.workspace.introEyebrow}</p>
          <h1>{ownerCopy.workspace.introTitle}</h1>
          <p className="lede">{ownerCopy.workspace.introLede}</p>
          {params?.error ? <p className="errorText">{params.error}</p> : null}
          {params?.dividendPayment === "recorded" ? (
            <p data-status="ready">Utbyttebetalingen er avstemt mot den deklarerte gjelden.</p>
          ) : null}
          {!hasSupabaseEnv() ? (
            <p className="errorText">{ownerCopy.auth.unavailable}</p>
          ) : user ? (
            <form action={signOut}>
              <button className="secondaryButton" type="submit">
                {ownerCopy.nav.signOut}
              </button>
            </form>
          ) : null}
        </div>

        <aside className="statusPanel" aria-label={ownerCopy.workspace.statusHeading}>
          <div className="panelHeader">
            <span>{ownerCopy.workspace.statusHeading}</span>
            <strong>
              {user ? ownerCopy.workspace.signedIn : ownerCopy.workspace.signedOut}
            </strong>
          </div>
          <div className="metricGrid">
            <div>
              <span>{ownerCopy.workspace.companiesLabel}</span>
              <strong>{companies.length}</strong>
            </div>
            <div>
              <span>{ownerCopy.workspace.connectionLabel}</span>
              <strong>
                {error
                  ? ownerCopy.workspace.connectionError
                  : ownerCopy.workspace.connectionOk}
              </strong>
            </div>
          </div>
        </aside>
      </section>
          <section className="band" id="opprett">
            <div className="sectionHeader">
              <p className="eyebrow">{ownerCopy.workspace.createEyebrow}</p>
              <h2>{ownerCopy.workspace.createTitle}</h2>
            </div>
            <div className="dataPanel formPanel widePanel">
              <p>Sjekk hele selskapsåret gratis før du oppretter selskapet i Talli.</p>
              <Link className="primaryButton" href="/sjekk-selskapet">
                Sjekk selskapet gratis
              </Link>
            </div>
          </section>

          <section className="band mutedBand">
            <div className="sectionHeader">
              <p className="eyebrow">{ownerCopy.workspace.companiesEyebrow}</p>
              <h2>{ownerCopy.workspace.companiesTitle}</h2>
            </div>
            <div className="readinessGrid">
              {companies.map((company) => {
                return (
                  <div className="readinessItem" key={company.id}>
                    <span>{company.org_number}</span>
                    <strong>{company.name}</strong>
                    <p>Selskapet er opprettet gjennom den endelige selskapsårsjekken.</p>
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
                  <span>{ownerCopy.workspace.noCompaniesLabel}</span>
                  <strong data-status="draft">
                    {ownerCopy.workspace.noCompaniesStatus}
                  </strong>
                  <p>{ownerCopy.workspace.noCompaniesBody}</p>
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
                  <input
                    name="operationId"
                    type="hidden"
                    value={params?.newYearOperationId ?? randomUUID()}
                  />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <label>
                    Bankbalanse
                    <input name="bankBalance" inputMode="decimal" placeholder="0" required />
                  </label>
                  <label>
                    Aksjekapital
                    <input name="shareCapital" inputMode="decimal" placeholder="0" required />
                  </label>
                  <label>
                    Antall aksjer
                    <input name="shareCount" inputMode="numeric" placeholder="Antall" required />
                  </label>
                  <label>
                    Pålydende
                    <input name="nominalValue" inputMode="decimal" placeholder="Pålydende per aksje" required />
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
                    <input name="shareholderShareCount" inputMode="numeric" placeholder="Antall" required />
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
                        <input name="companyId" type="hidden" value={setup.company_id} />
                        <input name="setupId" type="hidden" value={setup.id} />
                        <button className="secondaryButton" type="submit">
                          Generer RF-1086
                        </button>
                      </form>
                    </div>
                  ))}
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Kansellering</p>
                  <h2>Arkiv først, deretter oppbevaringsstans før sletting.</h2>
                </div>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Arkiveksport</span>
                    <strong data-status={primaryCancellation?.evidence?.archiveExportedAt ? "ready" : "warning"}>
                      {primaryCancellation?.evidence?.archiveExportedAt ? "Registrert" : "Påkrevd"}
                    </strong>
                    <p>
                      {primaryCancellation?.evidence?.archiveDownloadPath
                        ? `Arkivsti: ${primaryCancellation.evidence.archiveDownloadPath}`
                        : "Eksporter selskapsarkiv før destruktive handlinger."}
                    </p>
                  </div>
                  <div className="readinessItem">
                    <span>Status</span>
                    <strong data-status={primaryCancellation ? "warning" : "draft"}>
                      {primaryCancellation ? cancellationStatusLabel(primaryCancellation.status) : "Ingen forespørsel"}
                    </strong>
                    <p>
                      {primaryCancellation
                        ? "Endelig sletting krever en oppbevaringsvurdering og juridisk og sikkerhetsmessig godkjenning."
                        : "Selskapet er aktivt. Kansellering oppretter en oppbevaringsstans, ikke umiddelbar sletting."}
                    </p>
                  </div>
                  <div className="readinessItem">
                    <span>Oppbevaringsplikt</span>
                    <strong data-status="warning">Lovpålagt vurdering</strong>
                    <p>
                      {primaryCancellation?.evidence?.retentionClasses?.join(", ") ??
                        "Dokumenter, regnskap, innsendingskvitteringer, fakturering og logg kan måtte beholdes."}
                    </p>
                  </div>
                  {cancellationLifecycle.map((item) => (
                    <div className="readinessItem" key={item.key}>
                      <span>{item.label}</span>
                      <strong data-status={item.state === "done" ? "ready" : item.state === "current" ? "warning" : "draft"}>
                        {item.state}
                      </strong>
                      <p>{item.message}</p>
                    </div>
                  ))}
                </div>
                {!cancellationLifecycleError && !primaryCancellation && primaryCompanyId ? (
                  <form className="dataPanel formPanel widePanel" action={requestCompanyCancellation}>
                    <input name="operationId" type="hidden" value={
                      pendingCancellationOperation?.command === "request"
                        && pendingCancellationOperation.companyId === primaryCompanyId
                        ? pendingCancellationOperation.operationId : randomUUID()
                    } />
                    <input name="companyId" type="hidden" value={primaryCompanyId} />
                    <input name="incomeYear" type="hidden" value={
                      pendingCancellationOperation?.command === "request"
                        && pendingCancellationOperation.companyId === primaryCompanyId
                        ? pendingCancellationOperation.incomeYear : primaryIncomeYear
                    } />
                    <label>
                      Begrunnelse
                      <input name="reason" placeholder="Kort begrunnelse" defaultValue={
                        pendingCancellationOperation?.command === "request"
                          && pendingCancellationOperation.companyId === primaryCompanyId
                          ? pendingCancellationOperation.reason : undefined
                      } />
                    </label>
                    <button className="secondaryButton" type="submit">
                      Be om kansellering
                    </button>
                  </form>
                ) : null}
                {!cancellationLifecycleError && primaryCancellation && primaryCancellation.status === "export_required" ? (
                  <form className="dataPanel formPanel widePanel" action={resumeCompanyCancellation}>
                    <input name="operationId" type="hidden" value={
                      pendingCancellationOperation?.command === "resume"
                        && pendingCancellationOperation.cancellationId === primaryCancellation.id
                        ? pendingCancellationOperation.operationId : randomUUID()
                    } />
                    <input name="companyId" type="hidden" value={primaryCancellation.company_id} />
                    <input name="cancellationId" type="hidden" value={primaryCancellation.id} />
                    <input name="incomeYear" type="hidden" value={
                      pendingCancellationOperation?.command === "resume"
                        && pendingCancellationOperation.cancellationId === primaryCancellation.id
                        ? pendingCancellationOperation.incomeYear : primaryIncomeYear
                    } />
                    <input name="expectedUpdatedAt" type="hidden" value={
                      pendingCancellationOperation?.command === "resume"
                        && pendingCancellationOperation.cancellationId === primaryCancellation.id
                        ? pendingCancellationOperation.expectedUpdatedAt : primaryCancellation.updated_at
                    } />
                    <p>Eksporter selskapsarkivet for valgt inntektsår. Fortsett deretter den eksisterende kanselleringsforespørselen.</p>
                    <button className="secondaryButton" type="submit">
                      Fortsett kansellering etter eksport
                    </button>
                  </form>
                ) : null}
                {!cancellationLifecycleError && primaryCancellation && primaryCancellation.status === "deletion_approved" ? (
                  <form className="dataPanel formPanel widePanel" action={completeCompanyDeletionRecord}>
                    <input name="operationId" type="hidden" value={
                      pendingCancellationOperation?.command === "finalize"
                        && pendingCancellationOperation.cancellationId === primaryCancellation.id
                        ? pendingCancellationOperation.operationId : randomUUID()
                    } />
                    <input name="companyId" type="hidden" value={
                      pendingCancellationOperation?.command === "finalize"
                        && pendingCancellationOperation.cancellationId === primaryCancellation.id
                        ? pendingCancellationOperation.companyId : primaryCancellation.company_id
                    } />
                    <input name="cancellationId" type="hidden" value={primaryCancellation.id} />
                    <input name="expectedUpdatedAt" type="hidden" value={
                      pendingCancellationOperation?.command === "finalize"
                        && pendingCancellationOperation.cancellationId === primaryCancellation.id
                        ? pendingCancellationOperation.expectedUpdatedAt : primaryCancellation.updated_at
                    } />
                    <p>Den uavhengige vurderingen er godkjent. Eksporter et nytt arkiv etter godkjenningen før du fullfører. Selskapet markeres som slettet uten fysisk sletting av oppbevaringspliktige data.</p>
                    <button className="secondaryButton" type="submit">
                      Fullfør slettestatus
                    </button>
                  </form>
                ) : null}
              </section>

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Periodelås</p>
                  <h2>Steng inntektsår etter filing eller godkjenning.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={lockCompanyYear}>
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <input name="operationId" type="hidden" value={params?.lockOperationId ?? randomUUID()} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <label>
                    Årsak
                    <input name="reason" placeholder="Hvorfor året låses" required />
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
                  <h2>Forhåndsvisning av RF-1086.</h2>
                </div>
                <form className="dataPanel formPanel widePanel" action={recoverWorkspaceInvitationSideEffects}>
                  <span className="panelLabel">Gjenopprett invitasjonshandling</span>
                  <p>
                    {params?.recovery === "invitation"
                      ? "Handlingen ble lagret, men varsling eller revisjonsspor må fullføres."
                      : "Fullfør eventuelle lagrede invitasjonsvarsler eller revisjonsspor uten å utføre handlingen på nytt."}
                  </p>
                  <button className="secondaryButton" type="submit">Fullfør lagret handling</button>
                </form>
                <form className="dataPanel formPanel widePanel" action={inviteWorkspaceReviewer}>
                  <input name="operationId" type="hidden" value={randomUUID()} />
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
                  <p>Krever ny identitetsbekreftelse. Vi sender e-postvarselet automatisk.</p>
                </form>
                <form className="dataPanel formPanel widePanel" action={acceptWorkspaceInvitation}>
                  <input name="operationId" type="hidden" value={randomUUID()} />
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
                        <p>{invitation.invitedEmail}</p>
                        <p>Utløper {new Date(invitation.expiresAt).toLocaleDateString("nb-NO")}</p>
                        {status === "pending" ? (
                          <div className="inlineActions">
                            <form action={resendWorkspaceInvitation}>
                              <input name="operationId" type="hidden" value={randomUUID()} />
                              <input name="companyId" type="hidden" value={primaryCompanyId} />
                              <input name="invitationId" type="hidden" value={invitation.id} />
                              <input name="expectedUpdatedAt" type="hidden" value={invitation.updatedAt} />
                              <button className="secondaryButton" type="submit">Send på nytt</button>
                            </form>
                            <form action={revokeWorkspaceInvitation}>
                              <input name="operationId" type="hidden" value={randomUUID()} />
                              <input name="companyId" type="hidden" value={primaryCompanyId} />
                              <input name="invitationId" type="hidden" value={invitation.id} />
                              <input name="expectedUpdatedAt" type="hidden" value={invitation.updatedAt} />
                              <button className="secondaryButton" type="submit">Tilbakekall</button>
                            </form>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                <div className="readinessGrid">
                  {memberships.map((membership) => (
                    <div className="readinessItem" key={membership.userId}>
                      <span>Medlem</span>
                      <strong data-status="ready">{membership.role}</strong>
                      <p>{membership.userId}</p>
                      <form action={administerWorkspaceMembership}>
                        <input name="operationId" type="hidden" value={randomUUID()} />
                        <input name="companyId" type="hidden" value={primaryCompanyId} />
                        <input name="userId" type="hidden" value={membership.userId} />
                        <input name="state" type="hidden" value="active" />
                        <input name="expectedRole" type="hidden" value={membership.role} />
                        <select
                          aria-label={`Medlemsrolle for ${membership.userId}`}
                          name="role"
                          defaultValue={membership.role}
                        >
                          <option value="reviewer">Reviewer</option>
                          <option value="read_only">Read-only</option>
                        </select>
                        <button className="secondaryButton" type="submit">Endre rolle</button>
                      </form>
                      <form action={administerWorkspaceMembership}>
                        <input name="operationId" type="hidden" value={randomUUID()} />
                        <input name="companyId" type="hidden" value={primaryCompanyId} />
                        <input name="userId" type="hidden" value={membership.userId} />
                        <input name="state" type="hidden" value="removed" />
                        <input name="expectedRole" type="hidden" value={membership.role} />
                        <button className="secondaryButton" type="submit">Fjern tilgang</button>
                      </form>
                    </div>
                  ))}
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
                              Jeg bekrefter at overstyringen skal vises i status og loggen.
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
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <label>
                    Lånedato
                    <input name="loanDate" type="date" required />
                  </label>
                  <label>
                    Beløp
                    <input name="amount" inputMode="decimal" placeholder="0" required />
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
                    <input name="counterpartyName" required />
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
                    <select name="documentStatus" defaultValue="not_required">
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
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <label>
                    Oppgjørsdato
                    <input name="settlementDate" type="date" required />
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
                    <input
                      name="amount"
                      inputMode="decimal"
                      defaultValue={taxEstimate.estimatedTax > 0 ? taxEstimate.estimatedTax : undefined}
                      placeholder="0"
                      required
                    />
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
                    <select name="documentStatus" defaultValue="not_required">
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
                    <p>{taxSettlementEntries.length} skatteoppgjørsposteringer i regnskapet.</p>
                    <p>Arkivet inkluderer skatteoppgjør med bilag og regnskapskobling.</p>
                  </div>
                </div>
              </section>

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Fakturering</p>
                  <h2>Abonnement og innsendingspakke.</h2>
                  <p>Endring av fakturering krever ny identitetsbekreftelse.</p>
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
                      <input name="reason" placeholder="Hvorfor saken er utenfor støttet løype" required />
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
                    <p>Kunde: {primaryBillingAccount?.provider_customer_ref ?? "Ikke opprettet"}</p>
                    <p>Abonnement: {primaryBillingAccount?.subscription_provider_ref ?? "Ikke betalt"}</p>
                  </div>
                  <div className="readinessItem">
                    <span>Innsendingspakke</span>
                    <strong data-status={primaryBillingGate?.allowed ? "ready" : primaryBillingGate?.chargeAllowed ? "warning" : "draft"}>
                      {primaryBillingGate?.status ?? "Faktureringskonto mangler"}
                    </strong>
                    <p>{primaryBillingGate?.message ?? "Opprett faktureringskonto før innsendingspakke."}</p>
                    <p>Status {primaryFilingReady ? "klar" : "ikke klar"} for {primaryIncomeYear}.</p>
                    <p>Innsendingspakke ref: {primaryBillingAccount?.filing_package_payment_ref ?? "Ikke betalt"}</p>
                    {primaryBillingAccount && !primaryBillingAccount.subscription_active ? (
                      <form action={activateBillingSubscription}>
                        <input name="companyId" type="hidden" value={primaryCompanyId} />
                        <button className="secondaryButton" type="submit">
                          Marker abonnement aktivt
                        </button>
                      </form>
                    ) : null}
                    {primaryBillingAccount?.subscription_active ? (
                      <form action={cancelBillingSubscription}>
                        <input name="companyId" type="hidden" value={primaryCompanyId} />
                        <button className="secondaryButton" type="submit">
                          Kanseller abonnement
                        </button>
                      </form>
                    ) : null}
                  </div>
                  <div className="readinessItem">
                    <span>Refusjon</span>
                    <strong data-status={primaryBillingAccount?.refund_completed ? "ready" : primaryBillingAccount?.refund_eligible ? "warning" : "draft"}>
                      {primaryBillingAccount?.refund_completed
                        ? "Refundert"
                        : primaryBillingAccount?.refund_eligible
                          ? "Refusjonsberettiget"
                          : "Ingen refusjon"}
                    </strong>
                    <p>{primaryBillingAccount?.refund_provider_ref ?? primaryBillingAccount?.no_charge_reason ?? "Støttet sak kan refunderes etter Talli-feil."}</p>
                    {primaryBillingAccount?.filing_package_paid && primaryBillingAccount.supported_case ? (
                      <form action={markBillingRefundEligible}>
                        <input name="companyId" type="hidden" value={primaryCompanyId} />
                        <input name="incomeYear" type="hidden" value={primaryIncomeYear} />
                        <button className="secondaryButton" type="submit">
                          Refunder filingpakke
                        </button>
                      </form>
                    ) : null}
                  </div>
                  <div className="readinessItem">
                    <span>Betalingshendelser</span>
                    <strong data-status={primaryBillingEvents.length ? "ready" : "draft"}>
                      {primaryBillingEvents.length} eventer
                    </strong>
                    <p>
                      {primaryBillingEvents[0]
                        ? `${primaryBillingEvents[0].kind}: ${primaryBillingEvents[0].status} (${primaryBillingEvents[0].provider_reference})`
                        : "Ingen providerhendelser lagret."}
                    </p>
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
                <form className="dataPanel formPanel widePanel" action={recordAuthorityTestEvidence}>
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
                    Miljø
                    <select name="environment" defaultValue="test">
                      <option value="test">Myndighet testmiljø</option>
                      <option value="manual_evidence">Manuell evidens</option>
                    </select>
                  </label>
                  <label>
                    Status
                    <select name="status" defaultValue="pending">
                      <option value="pending">Venter</option>
                      <option value="accepted">Akseptert</option>
                      <option value="rejected">Avvist</option>
                      <option value="blocked">Blokkert</option>
                    </select>
                  </label>
                  <label>
                    Testreferanse
                    <input name="testReference" placeholder="Altinn test-id, saksref eller manuell evidensref" required />
                  </label>
                  <label>
                    Kvitteringsref
                    <input name="receiptReference" placeholder="receipt-..." />
                  </label>
                  <label>
                    Arkivref
                    <input name="archiveReference" placeholder="archive-..." />
                  </label>
                  <label>
                    Evidens-URL
                    <input name="evidenceUrl" placeholder="https://..." />
                  </label>
                  <label>
                    Payload hash
                    <input name="payloadHash" placeholder="sha256:..." />
                  </label>
                  <label>
                    Feedback
                    <textarea name="feedbackSummary" placeholder="Kort myndighetsfeedback eller blokkering" />
                  </label>
                  <button className="secondaryButton" type="submit">
                    Lagre test-evidens
                  </button>
                  <p>Dette dokumenterer test/feedback. Produksjon krever fortsatt separat release gate.</p>
                </form>
                <form
                  className="dataPanel formPanel widePanel"
                  action={recordAnnualAccountsTt02Evidence}
                  encType="multipart/form-data"
                >
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <label>
                    Verifisert årsregnskap-evidens fra TT02
                    <input
                      name="evidenceFile"
                      type="file"
                      accept="application/json,.json"
                      required
                    />
                  </label>
                  <label>
                    Evidens-URL (valgfri)
                    <input name="evidenceUrl" placeholder="https://..." type="url" />
                  </label>
                  <button className="secondaryButton" type="submit">
                    Importer TT02-evidens
                  </button>
                  <p>
                    Importen validerer selskap, signatur, innsending, kvittering og arkiv.
                    Innboksstatus uten endelig myndighetsbeslutning lagres alltid som venter og
                    aktiverer aldri produksjon.
                  </p>
                </form>
                <form
                  className="dataPanel formPanel widePanel"
                  action={recordCompanyTaxReturnTt02Evidence}
                  encType="multipart/form-data"
                >
                  <input name="companyId" type="hidden" value={primaryCompanyId} />
                  <input name="incomeYear" type="hidden" value={primaryIncomeYear} />
                  <label>
                    Verifisert skattemelding-evidens fra TT02
                    <input
                      name="evidenceFile"
                      type="file"
                      accept="application/json,.json"
                      required
                    />
                  </label>
                  <label>
                    Evidens-URL (valgfri)
                    <input name="evidenceUrl" placeholder="https://..." type="url" />
                  </label>
                  <button className="secondaryButton" type="submit">
                    Importer skattemelding-evidens
                  </button>
                  <p>
                    Importen krever riktig selskap og år, eksakte TT02-scopes, validertOK,
                    fullført personbekreftelse, offisiell tilbakemelding og arkiv. Resultatet
                    lagres med tilstanden «Venter på klassifisering» og aktiverer aldri produksjon.
                  </p>
                </form>
                <div className="readinessGrid">
                  {authorityObligations.map((obligation) => {
                    const gate = productionAuthorityGate(primaryAuthorityPermissions, obligation);
                    const evidenceGate = authorityTestEvidenceGate(primaryAuthorityTestRuns, obligation);
                    const permission = primaryAuthorityPermissions.find((item) => item.obligation === obligation);
                    const latestRun = primaryAuthorityTestRuns.find((item) => item.obligation === obligation);
                    return (
                      <div className="readinessItem" key={obligation}>
                        <span>{authorityObligationLabel(obligation)}</span>
                        <strong data-status={gate.allowed ? "ready" : permission ? "warning" : "draft"}>
                          {authorityPermissionGateStatusLabel(gate.status)}
                        </strong>
                        <p>{gate.message}</p>
                        <p>Test-evidens: {authorityTestEvidenceGateStatusLabel(evidenceGate.status)}</p>
                        <p>{evidenceGate.message}</p>
                        <p>
                          Siste testref:{" "}
                          {latestRun
                            ? `${latestRun.test_reference} (${authorityTestRunStatusLabel(latestRun.status)})`
                            : "Ingen"}
                        </p>
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
                  {submissionPresentation.simulations.map(({ submission }) => (
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
                  {submissionPresentation.simulations.length === 0 ? (
                    <div className="readinessItem">
                      <span>Kvittering</span>
                      <strong data-status="draft">Ikke arkivert</strong>
                      <p>Generer klar RF-1086 og bekreft simulert innsending.</p>
                    </div>
                  ) : null}
                </div>
              </section>

              {submissionPresentation.testAuthority.length > 0 ? (
                <section className="band">
                  <div className="sectionHeader">
                    <p className="eyebrow">TT02-testinnsending</p>
                    <h2>Mottatt testtilbakemelding venter på klassifisering.</h2>
                  </div>
                  <div className="readinessGrid">
                    {submissionPresentation.testAuthority.map((item) => (
                      <div className="readinessItem" key={item.submission.id}>
                        <span>{item.submission.income_year}</span>
                        <strong data-status="warning">{item.statusLabel}</strong>
                        <p>
                          Dette er test-evidens fra TT02. Den er ikke en produksjonsinnsending og
                          dokumenterer ikke myndighetsaksept.
                        </p>
                        <p>Tilbakemeldingsdata-ID: {item.submission.receipt_id ?? "Mangler"}</p>
                        <p>Arkivreferanse: {item.archiveReference ?? "Mangler"}</p>
                        <a href={`/archive/${item.submission.company_id}/${item.submission.income_year}/download`}>
                          Eksporter arkiv
                        </a>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              <section className="band mutedBand">
                <div className="sectionHeader">
                  <p className="eyebrow">Frister</p>
                  <h2>Persistert filingstatus per inntektsår.</h2>
                </div>
                {primaryCompanyId ? (
                  <form className="dataPanel formPanel widePanel" action={queueDeadlineReminders}>
                    <input name="companyId" type="hidden" value={primaryCompanyId} />
                    <input name="incomeYear" type="hidden" value={primaryIncomeYear} />
                    <label>
                      Varseldager
                      <input name="leadDays" defaultValue="30,7,1,0,-1" />
                    </label>
                    {deadlineReminderPreferences.map((preference) => (
                      <label className="checkboxLabel" key={preference.filing}>
                        <input name={`reminder_${preference.filing}`} type="checkbox" defaultChecked />
                        {preference.filing}
                      </label>
                    ))}
                    <button className="secondaryButton" type="submit">
                      Kø fristvarsler
                    </button>
                  </form>
                ) : null}
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
                <div className="readinessGrid">
                  {deadlineReminderPlan.map((reminder) => (
                    <div className="readinessItem" key={reminder.dedupeKey}>
                      <span>{reminder.filing}</span>
                      <strong data-status={reminder.shouldQueue ? "ready" : "draft"}>
                        {reminder.shouldQueue ? "Varsles" : reminder.skipReason}
                      </strong>
                      <p>{reminder.subject}</p>
                      <p>{reminder.body}</p>
                    </div>
                  ))}
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
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
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

              <section className="band">
                <div className="sectionHeader">
                  <p className="eyebrow">Utbyttegjeld</p>
                  <h2>Avstem betaling etter sluttført utbyttebeslutning.</h2>
                  <p>
                    Deklarasjonen bokføres først som gjeld. Bank krediteres bare når en faktisk utgående
                    transaksjon matches her.
                  </p>
                </div>
                {ownerDividendPayables.length === 0 ? (
                  <div className="readinessItem">
                    <strong data-status="draft">Ingen sluttført deklarasjon</strong>
                    <p>Sluttfør en eierbekreftet utbyttebeslutning før betaling kan avstemmes.</p>
                  </div>
                ) : (
                  <div className="setupGrid">
                    {ownerDividendPayables.map((payable) => {
                      const eligible = eligibleDividendTransactions(payable);
                      return (
                        <div className="dataPanel formPanel" key={payable.finalizationId}>
                          <span className="panelLabel">Beslutning {payable.incomeYear}</span>
                          <strong>
                            Gjenstår {(payable.remainingAmountOre / 100).toLocaleString("nb-NO")} kr
                          </strong>
                          <p>
                            Deklarert {(payable.declaredAmountOre / 100).toLocaleString("nb-NO")} kr · betalt
                            {" "}{(payable.paidAmountOre / 100).toLocaleString("nb-NO")} kr
                          </p>
                          <a href={`/corporate-decisions/${payable.decisionId}`}>Se beslutning og dokumentasjon</a>
                          {payable.settled ? (
                            <p data-status="ready">Utbyttegjelden er fullt oppgjort.</p>
                          ) : process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED !== "true" ? (
                            <p data-status="warning">Betalingsmatching er deaktivert av release-gaten.</p>
                          ) : eligible.length === 0 ? (
                            <p data-status="warning">Ingen uavstemte utgående banktransaksjoner passer restgjelden.</p>
                          ) : (
                            <form action={recordOwnerDividendPayment}>
                              <input name="decisionId" type="hidden" value={payable.decisionId} />
                              <input name="documentSetId" type="hidden" value={payable.documentSetId} />
                              <input name="decisionHash" type="hidden" value={payable.decisionHash} />
                              <input name="holdingActionId" type="hidden" value={randomUUID()} />
                              <input name="ledgerEntryId" type="hidden" value={randomUUID()} />
                              <label>
                                Utgående banktransaksjon
                                <select name="bankTransactionId" required defaultValue="">
                                  <option value="" disabled>Velg transaksjon</option>
                                  {eligible.map((transaction) => (
                                    <option value={transaction.id} key={transaction.id}>
                                      {transaction.transaction_date} · {transaction.text} · {transaction.amount.toLocaleString("nb-NO")} kr
                                    </option>
                                  ))}
                                </select>
                              </label>
                              <button className="primaryButton" type="submit">Avstem utbyttebetaling</button>
                            </form>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
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
                      <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                    </label>
                    <label>
                      CSV
                      <textarea name="csvText" placeholder="date,text,amount,balance" required />
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
                      <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
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
                      <input name="payee" required />
                    </label>
                    <label>
                      Betalt dato
                      <input name="paidDate" type="date" required />
                    </label>
                    <label>
                      Beløp
                      <input name="amount" inputMode="decimal" placeholder="0" required />
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
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <label>
                    Utbetalende selskap
                    <input name="payingCompanyName" required />
                  </label>
                  <label>
                    Investering-ID
                    <input name="linkedInvestmentId" placeholder="Velg samme ID som investeringen" required />
                  </label>
                  <label>
                    Vedtaksdato
                    <input name="declaredDate" type="date" required />
                  </label>
                  <label>
                    Betalt dato
                    <input name="paidDate" type="date" required />
                  </label>
                  <label>
                    Brutto beløp
                    <input name="grossAmount" inputMode="decimal" placeholder="0" required />
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
                    <select name="documentStatus" defaultValue="not_required">
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
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <label>
                    Investering-ID
                    <input name="investmentKey" placeholder="Stabil intern ID" required />
                  </label>
                  <label>
                    Selskap
                    <input name="investmentName" required />
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
                    <input name="acquisitionDate" type="date" required />
                  </label>
                  <label>
                    Antall aksjer
                    <input name="shareCount" inputMode="decimal" placeholder="Antall" required />
                  </label>
                  <label>
                    Kjøpsbeløp
                    <input name="purchaseAmount" inputMode="decimal" placeholder="0" required />
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
                    <select name="documentStatus" defaultValue="not_required">
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
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
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
                    <input name="saleDate" type="date" required />
                  </label>
                  <label>
                    Solgte aksjer
                    <input name="soldShareCount" inputMode="decimal" placeholder="Antall" required />
                  </label>
                  <label>
                    Salgsproveny
                    <input name="proceeds" inputMode="decimal" placeholder="0" required />
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
                    <select name="documentStatus" defaultValue="not_required">
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
                  <h2>Opprett et gjennomgått beslutningsutkast før signering og bokføring.</h2>
                </div>
                <div className="readinessGrid">
                  <div className="readinessItem">
                    <span>Beslutningsdokumenter</span>
                    <strong data-status={process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true" ? "warning" : "draft"}>
                      {process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true" ? "Utkast tilgjengelig" : "Deaktivert"}
                    </strong>
                    <p>
                      {process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true"
                        ? "Gå til handlingsløypen for å gjennomgå alle fakta og lage PDF-utkast uten bokføring."
                        : "Løypen åpnes først etter navngitt juridisk og regnskapsfaglig godkjenning."}
                    </p>
                    {process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true" ? (
                      <a className="secondaryButton" href="/actions/owner-dividend">
                        Åpne utkastløype
                      </a>
                    ) : null}
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
                  <input name="operationId" type="hidden" value={params?.manualOperationId ?? randomUUID()} />
                  <label>
                    Inntektsår
                    <input name="incomeYear" inputMode="numeric" defaultValue={primaryIncomeYear} required />
                  </label>
                  <label>
                    Memo
                    <input name="memo" placeholder="Beskriv posteringen" required />
                  </label>
                  <label>
                    Konto debet
                    <input name="account0" inputMode="numeric" required />
                  </label>
                  <label>
                    Beskrivelse debet
                    <input name="description0" required />
                  </label>
                  <label>
                    Debet
                    <input name="debit0" inputMode="decimal" placeholder="0" required />
                  </label>
                  <input name="credit0" type="hidden" value="0" />
                  <label>
                    Konto kredit
                    <input name="account1" inputMode="numeric" required />
                  </label>
                  <label>
                    Beskrivelse kredit
                    <input name="description1" required />
                  </label>
                  <input name="debit1" type="hidden" value="0" />
                  <label>
                    Kredit
                    <input name="credit1" inputMode="decimal" placeholder="0" required />
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
      <section id="sikkerhet" className="split">
        <div>
          <p className="eyebrow">{ownerCopy.workspace.security.eyebrow}</p>
          <h2>{ownerCopy.workspace.security.title}</h2>
          <p>{ownerCopy.workspace.security.body}</p>
        </div>
        <ol className="actionList">
          {ownerCopy.workspace.security.points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ol>
      </section>
    </>
  );
}
