import Link from "next/link";
import { notFound } from "next/navigation";

import {
  confirmSimulatedRf1086Submission,
  approveProductionFiling,
  generateRf1086Preview,
  reconcileRf1086ProductionAction,
  refreshAnnualReadinessSnapshots,
  sendApprovedRf1086ProductionFiling,
} from "../../../actions";
import {
  Banner,
  EmptyState,
  LinkButton,
  StatusBadge,
  Stepper,
  SubmitButton,
} from "../../../components/ui";
import {
  evaluateObligationReadiness,
  type AnnualReadinessIssue,
} from "../../../lib/annual-readiness";
import { evaluateCorporateDocumentReadiness } from "../../../lib/corporate-document-readiness";
import type { AuthorityObligation } from "../../../lib/authority-permission";
import { ownerCopy } from "../../../lib/copy";
import {
  buildRf1086OwnerProductionPresentation,
  rf1086OwnerActionErrorMessage,
  selectLatestRf1086ProductionSubmission,
} from "../../../lib/rf1086-production-presentation";
import { createSupabaseServerClient } from "../../../lib/supabase/server";
import { loadWorkspaceData } from "../../../lib/workspace-data";
import {
  loadSystemUserRequestPresentations,
  systemUserFilingPresentation,
} from "../../connections/_presentation";
import {
  buildReadinessInput,
  isFilingObligation,
} from "../_readiness";
import { buildOwnerFilingPresentation } from "../_presentation";
import { Rf1086ReconciliationControl } from "../_submission-presentation";

export const dynamic = "force-dynamic";

const f = ownerCopy.filing;

// Blocker codes that have their own dedicated step further down the flow, so
// they are not repeated in the "Sjekk" checklist.
const STEP_CODES = new Set([
  "rf1086_preview_missing",
  "rf1086_preview_not_ready",
  "missing_authority_confirmation",
  "production_disabled",
]);

const SUBMISSION_STATUS_LABELS: Record<string, string> = {
  receipt_stored: "Kvittering arkivert",
  submitted: "Sendt (simulert)",
  feedback_ready: "Tilbakemelding klar",
  preview_confirmed: "Bekreftet",
  authority_confirmed: "Bekreftet",
  failed_retryable: "Feilet – kan prøves igjen",
  failed_blocked: "Feilet – blokkert",
};

/** Removes residual infra jargon from raw engine messages used as a fallback. */
function plainize(message: string): string {
  return message
    .replace(/Year-end interview/gi, "årsavslutningen")
    .replace(/readiness/gi, "status")
    .replace(/Billingkonto/gi, "Faktureringskonto")
    .replace(/billing/gi, "fakturering");
}

function blockerCopy(issue: AnnualReadinessIssue) {
  const mapped = f.blockers[issue.code];
  if (mapped) return mapped;
  return { message: plainize(issue.message), fixHref: undefined, fixLabel: undefined };
}

function Blockers({ issues }: { issues: AnnualReadinessIssue[] }) {
  return (
    <ul className="blockerList">
      {issues.map((issue) => {
        const copy = blockerCopy(issue);
        return (
          <li
            key={`${issue.code}-${issue.message}`}
            className={`blockerItem${issue.level === "warning" ? " blockerItem--warn" : ""}`}
          >
            <span className="blockerMessage">{copy.message}</span>
            {copy.fixHref ? (
              <Link className="blockerFix" href={copy.fixHref}>
                {copy.fixLabel ?? f.check.fixCta}
              </Link>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

type FilingFlowProps = {
  params: Promise<{ obligation: string }>;
  searchParams?: Promise<{ error?: string; posted?: string; productionError?: string }>;
};

export default async function FilingObligationPage({
  params,
  searchParams,
}: FilingFlowProps) {
  const { obligation: raw } = await params;
  if (!isFilingObligation(raw)) {
    notFound();
  }
  const obligation = raw as AuthorityObligation;
  const query = await searchParams;
  const data = await loadWorkspaceData();
  const input = buildReadinessInput(data);
  const meta = f.obligations[obligation];

  if (!input) {
    return (
      <div>
        <div className="pageHead">
          <h1 className="pageTitle">{meta.label}</h1>
          <p className="pageLede">{meta.lede}</p>
        </div>
        <EmptyState
          title={f.needsCompanyTitle}
          action={
            <LinkButton variant="primary" href="/onboarding">
              {f.needsCompanyCta}
            </LinkButton>
          }
        >
          {f.needsCompanyBody}
        </EmptyState>
      </div>
    );
  }

  const returnTo = `/filing/${obligation}`;
  const snapshot = evaluateObligationReadiness(input, obligation);
  const corporateReadiness = input.corporateDocuments?.enabled
    ? evaluateCorporateDocumentReadiness(input.corporateDocuments.lifecycle)
    : null;
  const annualCorporateDecision = data.corporateDecisions.find(
    (decision) => decision.company_id === input.company.id
      && decision.income_year === input.incomeYear
      && decision.decision_kind === "annual_close",
  );
  const annualCorporateSet = annualCorporateDecision
    ? data.corporateDocumentSets.find((set) => set.decision_id === annualCorporateDecision.id)
    : null;
  const prereqBlocks = snapshot.hard_blocks.filter((issue) => !STEP_CODES.has(issue.code));
  const prerequisitesClear = prereqBlocks.length === 0;
  const checklist = [...prereqBlocks, ...snapshot.warnings];
  const presentation = buildOwnerFilingPresentation({
    obligation,
    incomeYear: input.incomeYear,
    submissions: input.filingSubmissions,
    posted: Boolean(query?.posted),
    error: query?.productionError
      ? rf1086OwnerActionErrorMessage(query.productionError, f.production.errors)
      : query?.error,
  });
  const filingString = presentation.filing;
  const submission = presentation.primarySubmission;
  const submitted = presentation.submitted;

  const header = (
    <div className="pageHead">
      <Link className="backLink" href="/filing">
        ← {f.backToHub}
      </Link>
      <h1 className="pageTitle">{meta.label}</h1>
      <p className="pageLede">{meta.lede}</p>
      <p className="cardNote">{f.yearLabel(input.incomeYear)}</p>
    </div>
  );

  const banners = (
    <>
      {presentation.showPostedSuccessBanner ? <Banner variant="success">{f.posted}</Banner> : null}
      {presentation.errorMessage ? <Banner variant="danger">{presentation.errorMessage}</Banner> : null}
    </>
  );

  // --- Skattemelding / Årsregnskap: readiness + honest placeholder. ---
  if (obligation !== "aksjonaerregisteroppgaven") {
    return (
      <div>
        {header}
        {banners}
        <section className="filingStep">
          <div className="filingStepHead">
            <h2 className="filingStepTitle">{f.check.title}</h2>
            <StatusBadge
              variant={snapshot.ready ? "success" : snapshot.status === "warning" ? "warning" : "danger"}
              label={snapshot.ready ? f.status.ready : snapshot.status === "warning" ? f.status.warning : f.status.blocked}
              icon={snapshot.ready ? "check" : "alert"}
            />
          </div>
          <div className="filingStepBody">
            {snapshot.ready && checklist.length === 0 ? (
              <p className="cardNote">{f.check.readyBody}</p>
            ) : (
              <>
                <p className="cardNote">
                  {prerequisitesClear ? f.check.warningBody : f.check.blockedBody}
                </p>
                <Blockers issues={checklist} />
              </>
            )}
          </div>
        </section>
        {obligation === "aarsregnskap" ? (
          <section className="filingStep">
            <div className="filingStepHead">
              <h2 className="filingStepTitle">Beslutningsdokumenter</h2>
              <StatusBadge
                variant={corporateReadiness?.annualSubmissionReady ? "success" : "danger"}
                label={corporateReadiness?.annualSubmissionReady ? "Sluttført" : "Ikke sluttført"}
                icon={corporateReadiness?.annualSubmissionReady ? "check" : "alert"}
              />
            </div>
            <div className="filingStepBody">
              {input.corporateDocuments?.enabled ? (
                <>
                  <p className="cardNote">
                    Tilstand: {corporateReadiness?.state ?? "draft"}. Årsregnskapet er ikke produksjonsklart før
                    begge protokoller er signert, eierbekreftet og beslutningen er sluttført.
                  </p>
                  {annualCorporateDecision ? (
                    <p className="cardNote">
                      Beslutningshash: <code>{annualCorporateDecision.decision_hash}</code><br />
                      Kildehash: <code>{annualCorporateDecision.source_hash}</code><br />
                      Malversjon: <code>{annualCorporateSet?.template_version ?? "mangler"}</code>
                    </p>
                  ) : null}
                  <LinkButton variant="secondary" href="/year-end">
                    Åpne årsbeslutningen
                  </LinkButton>
                </>
              ) : (
                <p className="cardNote">
                  Beslutningsdokumentløpet er deaktivert i denne utrullingen og kan ikke markeres produksjonsklart.
                </p>
              )}
            </div>
          </section>
        ) : null}
        {presentation.pendingFeedback ? (
          <section className="filingStep">
            <div className="filingStepHead">
              <h2 className="filingStepTitle">{presentation.pendingFeedback.title}</h2>
              <StatusBadge
                variant="warning"
                label={presentation.pendingFeedback.badgeLabel}
                icon="alert"
              />
            </div>
            <div className="filingStepBody">
              <Banner variant="warning">
                {presentation.pendingFeedback.body}
              </Banner>
              <p className="cardNote">
                Tilbakemeldingsdata-ID: <code>{presentation.pendingFeedback.receiptId ?? "mangler"}</code><br />
                Arkivreferanse: <code>{presentation.pendingFeedback.archiveReference ?? "mangler"}</code>
              </p>
            </div>
          </section>
        ) : (
          <section className="filingStep">
            <div className="filingStepHead">
              <h2 className="filingStepTitle">{f.preview.title}</h2>
              <StatusBadge variant="info" label={f.status.preparing} />
            </div>
            <div className="filingStepBody">
              <p className="cardNote">{f.preview.preparing}</p>
            </div>
          </section>
        )}
      </div>
    );
  }

  // --- Aksjonærregisteroppgaven: full guided flow. ---
  let systemUserConnection = null;
  let systemUserConnectionLoadFailed = false;
  try {
    const supabase = await createSupabaseServerClient();
    const connections = await loadSystemUserRequestPresentations(
      supabase,
      [input.company.id],
      ownerCopy.connections,
    );
    systemUserConnection = connections.find(
      (connection) => connection.companyId === input.company.id,
    ) ?? null;
  } catch {
    systemUserConnectionLoadFailed = true;
  }
  const systemUserFiling = systemUserConnectionLoadFailed
    ? ownerCopy.connections.filing.action
    : systemUserFilingPresentation(systemUserConnection, ownerCopy.connections);
  const systemUserConnectionHref = `/connections?company=${input.company.id}`;

  const preview = input.filingPreviews.find(
    (item) => item.filing === filingString && item.income_year === input.incomeYear,
  );
  const previewReady = preview?.status === "ready";
  const pilotEntitlement = data.productionPilotEntitlements.find(
    (item) => item.company_id === input.company.id
      && item.user_id === data.user?.id
      && item.income_year === input.incomeYear
      && item.obligation === obligation
      && item.case_profile === "rf1086_no_activity_v1"
      && item.status === "active"
      && new Date(item.starts_at) <= new Date()
      && new Date(item.expires_at) > new Date(),
  );
  const productionApproval = preview
    ? data.filingApprovalSnapshots.find(
      (item) => item.preview_id === preview.id && item.invalidated_at === null,
    )
    : null;
  const productionSubmission = selectLatestRf1086ProductionSubmission(
    data.productionFilingSubmissions,
    {
      companyId: input.company.id,
      userId: data.user?.id ?? "",
      incomeYear: input.incomeYear,
      obligation,
      caseProfile: "rf1086_no_activity_v1",
      environment: "production",
    },
  );
  const productionFeedbackArtifacts = productionSubmission
    ? data.productionFeedbackArtifacts.filter((artifact) => artifact.submission_id === productionSubmission.id)
    : [];
  const productionPresentation = buildRf1086OwnerProductionPresentation({
    feedbackState: productionSubmission?.feedback_state,
    submissionStatus: productionSubmission?.status,
    approved: Boolean(productionApproval),
    artifacts: productionFeedbackArtifacts,
  }, f.production);

  const setup = input.setups.find((item) => item.income_year === input.incomeYear);
  const storedReady = data.primaryReadinessSnapshots.some(
    (item) => item.obligation === obligation && item.ready,
  );
  const hasBlockingOverride = input.overrides.some(
    (item) =>
      item.income_year === input.incomeYear &&
      item.risk_level === "block" &&
      (item.filing === filingString || item.field_target.startsWith("rf1086.")),
  );
  const hasHardReviewBlock = preview
    ? data.comments.some(
        (comment) =>
          comment.preview_id === preview.id &&
          comment.severity === "hard_block" &&
          !comment.acknowledged_at,
      )
    : false;

  const confirmReady =
    prerequisitesClear &&
    previewReady &&
    systemUserFiling.ready &&
    storedReady &&
    !hasBlockingOverride &&
    !hasHardReviewBlock;

  const currentStep = submitted
    ? 4
    : !prerequisitesClear
      ? 0
      : !previewReady
        ? 1
        : !systemUserFiling.ready
          ? 2
          : 3;

  const steps = [
    f.steps.check,
    f.steps.preview,
    f.steps.authority,
    f.steps.confirm,
    f.steps.receipt,
  ];

  return (
    <div>
      {header}
      {banners}
      <Stepper steps={steps} current={currentStep} className="filingStepper" />

      <div className="filingFlow">
        {productionSubmission || (pilotEntitlement && previewReady) ? (
          <section className="filingStep">
            <div className="filingStepHead">
              <h2 className="filingStepTitle">{f.production.title}</h2>
              <StatusBadge
                variant={productionPresentation.status.variant}
                label={productionPresentation.status.label}
              />
            </div>
            <div className="filingStepBody">
              <Banner variant="warning">
                {f.production.warning}
              </Banner>
              <p className="cardNote">
                {f.production.companyLabel}: {input.company.name}<br />
                {f.production.yearLabel}: {input.incomeYear}<br />
                {f.production.caseLabel}: {f.production.supportedCase}
              </p>
              {preview ? <pre className="filingPreview">{preview.preview}</pre> : null}
              {productionSubmission ? (
                <>
                  <p className="cardNote">
                    {productionPresentation.status.body} {f.production.privateFeedback}
                  </p>
                  <Rf1086ReconciliationControl
                    action={reconcileRf1086ProductionAction}
                    submissionId={productionSubmission.id}
                    initialState={{
                      state: productionSubmission.feedback_state,
                      errorCode: null,
                      requiresManualRetry: false,
                    }}
                  />
                  {productionPresentation.artifacts.length > 0 ? (
                    <ul className="blockerList">
                      {productionPresentation.artifacts.map((artifact) => (
                        <li key={artifact.id} className="blockerItem">
                          <Link href={`/documents/${artifact.documentId}/download`}>
                            {artifact.label}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : !productionApproval ? (
                <form action={approveProductionFiling} className="filingConfirmForm">
                  <input type="hidden" name="returnTo" value={returnTo} />
                  <input type="hidden" name="previewId" value={preview?.id ?? ""} />
                  <input type="hidden" name="entitlementId" value={pilotEntitlement?.id ?? ""} />
                  <label className="filingCheck">
                    <input type="checkbox" name="realFilingConfirmed" required />
                    {f.production.approveCheck}
                  </label>
                  <SubmitButton pendingLabel={f.production.approvePending}>{f.production.approveCta}</SubmitButton>
                </form>
              ) : (
                <form action={sendApprovedRf1086ProductionFiling} className="filingConfirmForm">
                  <input type="hidden" name="returnTo" value={returnTo} />
                  <input type="hidden" name="approvalId" value={productionApproval.id} />
                  <SubmitButton pendingLabel={f.production.sendPending}>{f.production.sendCta}</SubmitButton>
                </form>
              )}
            </div>
          </section>
        ) : null}
        {/* Step 1 — readiness check */}
        <section className="filingStep">
          <div className="filingStepHead">
            <h2 className="filingStepTitle">{f.check.title}</h2>
            <StatusBadge
              variant={prerequisitesClear ? (checklist.length ? "warning" : "success") : "danger"}
              label={prerequisitesClear ? (checklist.length ? f.status.warning : f.status.ready) : f.status.blocked}
              icon={prerequisitesClear && !checklist.length ? "check" : "alert"}
            />
          </div>
          <div className="filingStepBody">
            {prerequisitesClear && checklist.length === 0 ? (
              <p className="cardNote">{f.check.readyBody}</p>
            ) : (
              <>
                <p className="cardNote">
                  {prerequisitesClear ? f.check.warningBody : f.check.blockedBody}
                </p>
                <Blockers issues={checklist} />
              </>
            )}
          </div>
        </section>

        {/* Step 2 — preview */}
        <section className="filingStep">
          <div className="filingStepHead">
            <h2 className="filingStepTitle">{f.preview.title}</h2>
            {previewReady ? (
              <StatusBadge variant="success" label={f.status.ready} icon="check" />
            ) : preview ? (
              <StatusBadge variant="warning" label={f.preview.notReady} icon="alert" />
            ) : null}
          </div>
          <div className="filingStepBody">
            {!prerequisitesClear ? (
              <p className="filingLockNote">{f.preview.lockedNote}</p>
            ) : !preview ? (
              <>
                <p className="cardNote">{f.preview.generateIntro}</p>
                <form action={generateRf1086Preview}>
                  <input type="hidden" name="returnTo" value={returnTo} />
                  <input type="hidden" name="setupId" value={setup?.id ?? ""} />
                  <SubmitButton pendingLabel={f.preview.generatePending}>
                    {f.preview.generateCta}
                  </SubmitButton>
                </form>
              </>
            ) : (
              <>
                <p className="cardNote">{f.preview.intro}</p>
                <pre className="filingPreview">{preview.preview}</pre>
                {preview.issues.length > 0 ? (
                  <ul className="blockerList">
                    {preview.issues.map((issue) => (
                      <li key={issue.code} className="blockerItem blockerItem--warn">
                        <span className="blockerMessage">{plainize(issue.message)}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {!previewReady ? (
                  <p className="filingLockNote">{f.preview.notReady}</p>
                ) : null}
                <form action={generateRf1086Preview}>
                  <input type="hidden" name="returnTo" value={returnTo} />
                  <input type="hidden" name="setupId" value={setup?.id ?? ""} />
                  <SubmitButton variant="ghost" pendingLabel={f.preview.generatePending}>
                    {f.preview.regenerateCta}
                  </SubmitButton>
                </form>
              </>
            )}
          </div>
        </section>

        {/* Step 3 — authority */}
        <section className="filingStep">
          <div className="filingStepHead">
            <h2 className="filingStepTitle">{f.authority.connectionTitle}</h2>
            <StatusBadge
              variant={systemUserFiling.variant}
              label={systemUserFiling.label}
              icon={systemUserFiling.ready ? "check" : "alert"}
            />
          </div>
          <div className="filingStepBody">
            <p className="cardNote">
              {systemUserConnectionLoadFailed
                ? f.authority.connectionLoadError
                : systemUserFiling.body}
            </p>
            <LinkButton variant="secondary" href={systemUserConnectionHref}>
              {f.authority.connectionCta}
            </LinkButton>
          </div>
        </section>

        {/* Step 4 — confirm & archive */}
        {!submitted ? (
          <section className="filingStep">
            <div className="filingStepHead">
              <h2 className="filingStepTitle">{f.confirm.title}</h2>
            </div>
            <div className="filingStepBody">
              {!(prerequisitesClear && previewReady && systemUserFiling.ready) ? (
                <p className="filingLockNote">{f.confirm.lockedNote}</p>
              ) : !confirmReady ? (
                <>
                  <p className="cardNote">{f.confirm.intro}</p>
                  {hasBlockingOverride || hasHardReviewBlock ? (
                    <p className="filingLockNote">{f.confirm.lockedNote}</p>
                  ) : (
                    <form action={refreshAnnualReadinessSnapshots} className="filingConfirmForm">
                      <input type="hidden" name="returnTo" value={returnTo} />
                      <input type="hidden" name="companyId" value={input.company.id} />
                      <input type="hidden" name="incomeYear" value={input.incomeYear} />
                      <SubmitButton variant="secondary" pendingLabel={f.check.refreshPending}>
                        {f.check.refreshCta}
                      </SubmitButton>
                    </form>
                  )}
                </>
              ) : (
                <>
                  <Banner variant="info">{f.confirm.intro}</Banner>
                  <form action={confirmSimulatedRf1086Submission} className="filingConfirmForm">
                    <input type="hidden" name="returnTo" value={returnTo} />
                    <input type="hidden" name="previewId" value={preview?.id ?? ""} />
                    <label className="filingCheck">
                      <input type="checkbox" name="authorityConfirmed" required />
                      {f.confirm.authorityCheck}
                    </label>
                    <label className="filingCheck">
                      <input type="checkbox" name="previewConfirmed" required />
                      {f.confirm.previewCheck}
                    </label>
                    <SubmitButton pendingLabel={f.confirm.pending}>
                      {f.confirm.cta}
                    </SubmitButton>
                  </form>
                </>
              )}
            </div>
          </section>
        ) : null}

        {/* Step 5 — receipt */}
        {submitted && submission ? (
          <section className="filingStep">
            <div className="filingStepHead">
              <h2 className="filingStepTitle">{f.receipt.title}</h2>
              <StatusBadge variant="success" label={f.status.submitted} icon="check" />
            </div>
            <div className="filingStepBody">
              <Banner variant="info">{f.receipt.simulatedNote}</Banner>
              <dl className="filingReceipt">
                <div className="filingReceiptRow">
                  <dt>{f.receipt.receiptLabel}</dt>
                  <dd>{submission.receipt_id}</dd>
                </div>
                <div className="filingReceiptRow">
                  <dt>{f.receipt.statusLabel}</dt>
                  <dd>{SUBMISSION_STATUS_LABELS[submission.status] ?? submission.status}</dd>
                </div>
              </dl>
              <LinkButton
                variant="secondary"
                href={`/archive/${submission.company_id}/${submission.income_year}/download`}
              >
                {f.receipt.exportCta}
              </LinkButton>
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
