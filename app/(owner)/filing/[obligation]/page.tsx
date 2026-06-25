import Link from "next/link";
import { notFound } from "next/navigation";

import {
  confirmAuthorityPermission,
  confirmSimulatedRf1086Submission,
  generateRf1086Preview,
  refreshAnnualReadinessSnapshots,
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
import type { AuthorityObligation } from "../../../lib/authority-permission";
import { ownerCopy } from "../../../lib/copy";
import { loadWorkspaceData } from "../../../lib/workspace-data";
import {
  buildReadinessInput,
  isFilingObligation,
  obligationFilingString,
} from "../_readiness";

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
  searchParams?: Promise<{ error?: string; posted?: string }>;
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
  const prereqBlocks = snapshot.hard_blocks.filter((issue) => !STEP_CODES.has(issue.code));
  const prerequisitesClear = prereqBlocks.length === 0;
  const checklist = [...prereqBlocks, ...snapshot.warnings];

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
      {query?.posted ? <Banner variant="success">{f.posted}</Banner> : null}
      {query?.error ? <Banner variant="danger">{query.error}</Banner> : null}
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
        <section className="filingStep">
          <div className="filingStepHead">
            <h2 className="filingStepTitle">{f.preview.title}</h2>
            <StatusBadge variant="info" label={f.status.preparing} />
          </div>
          <div className="filingStepBody">
            <p className="cardNote">{f.preview.preparing}</p>
          </div>
        </section>
      </div>
    );
  }

  // --- Aksjonærregisteroppgaven: full guided flow. ---
  const filingString = obligationFilingString(obligation);
  const preview = input.filingPreviews.find(
    (item) => item.filing === filingString && item.income_year === input.incomeYear,
  );
  const previewReady = preview?.status === "ready";
  const submission = input.filingSubmissions.find(
    (item) => item.filing === filingString && item.income_year === input.incomeYear,
  );
  const submitted = Boolean(submission?.receipt_id);
  const permission = input.authorityPermissions.find(
    (item) => item.obligation === obligation,
  );
  const authorityConfirmed = Boolean(permission?.confirmed_at && permission?.production_enabled);

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
    authorityConfirmed &&
    storedReady &&
    !hasBlockingOverride &&
    !hasHardReviewBlock;

  const currentStep = submitted
    ? 4
    : !prerequisitesClear
      ? 0
      : !previewReady
        ? 1
        : !authorityConfirmed
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
            <h2 className="filingStepTitle">{f.authority.title}</h2>
            {authorityConfirmed ? (
              <StatusBadge variant="success" label={f.authority.confirmed} icon="check" />
            ) : null}
          </div>
          <div className="filingStepBody">
            {!prerequisitesClear || !previewReady ? (
              <p className="filingLockNote">{f.authority.lockedNote}</p>
            ) : authorityConfirmed ? (
              <p className="cardNote">{f.authority.confirmed}</p>
            ) : (
              <>
                <p className="cardNote">{f.authority.intro}</p>
                <form action={confirmAuthorityPermission} className="filingConfirmForm">
                  <input type="hidden" name="returnTo" value={returnTo} />
                  <input type="hidden" name="companyId" value={input.company.id} />
                  <input type="hidden" name="obligation" value={obligation} />
                  <input type="hidden" name="productionEnabled" value="on" />
                  <label className="filingCheck">
                    <input type="checkbox" name="ack" required />
                    {f.authority.confirmLabel}
                  </label>
                  <SubmitButton pendingLabel={f.authority.pending}>
                    {f.authority.cta}
                  </SubmitButton>
                </form>
              </>
            )}
          </div>
        </section>

        {/* Step 4 — confirm & archive */}
        {!submitted ? (
          <section className="filingStep">
            <div className="filingStepHead">
              <h2 className="filingStepTitle">{f.confirm.title}</h2>
            </div>
            <div className="filingStepBody">
              {!(prerequisitesClear && previewReady && authorityConfirmed) ? (
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
