import { evaluateAnnualReadinessGates, type AnnualReadinessInput } from "./annual-readiness.ts";
import type { AuthorityPermission } from "./authority-permission.ts";
import type { AuthorityTestRun } from "./authority-test-evidence.ts";
import type { LaunchSignoff } from "./launch-signoff.ts";
import {
  Rf1086ProductionRunnerError,
  type Rf1086ProductionReleaseContext,
} from "./rf1086-production-runner.ts";
import type { Rf1086SubmissionConfirmations } from "./rf1086-submission.ts";
import type {
  CompanyMembershipRow,
  FilingPreviewRow,
  FilingReviewCommentRow,
  LaunchSignoffRow,
} from "./supabase/server.ts";
import type { StepUpContext } from "./security.ts";

export type Rf1086ProductionStateInput = Omit<AnnualReadinessInput, "authorityPermissions"> & {
  actorId: string;
  preview: FilingPreviewRow;
  membership: CompanyMembershipRow | null;
  authorityPermissions: AuthorityPermission[];
  authorityTestRuns: Pick<
    AuthorityTestRun,
    "company_id" | "obligation" | "status" | "receipt_reference" | "archive_reference" | "recorded_at"
  >[];
  stepUpContext: StepUpContext;
  launchSignoffRows: LaunchSignoffRow[];
  reviewComments: Pick<FilingReviewCommentRow, "preview_id" | "severity">[];
  confirmations: Rf1086SubmissionConfirmations;
  now?: Date;
};

function stateInvalid() {
  return new Rf1086ProductionRunnerError(
    "rf1086_production_state_invalid",
    "RF-1086 production state is inconsistent.",
  );
}

function normalizeLaunchSignoff(row: LaunchSignoffRow): LaunchSignoff {
  return {
    key: row.key,
    status: row.status,
    reviewer: row.reviewer,
    reviewedAt: row.reviewed_at,
    evidenceLink: row.evidence_link,
    decision: row.decision,
  };
}

export function deriveRf1086ProductionState(input: Rf1086ProductionStateInput): {
  preview: FilingPreviewRow;
  release: Rf1086ProductionReleaseContext;
} {
  const { preview, company, incomeYear } = input;
  if (
    preview.company_id !== company.id ||
    preview.income_year !== incomeYear ||
    (input.annualData &&
      (input.annualData.company_id !== company.id || input.annualData.income_year !== incomeYear)) ||
    (input.billingAccount && input.billingAccount.company_id !== company.id)
  ) {
    throw stateInvalid();
  }

  const samePeriod = <T extends { company_id: string; income_year: number }>(rows: T[]) =>
    rows.filter((row) => row.company_id === company.id && row.income_year === incomeYear);
  const overrides = samePeriod(input.overrides);
  const authorityPermissions = input.authorityPermissions.filter((row) => row.company_id === company.id);
  const currentReadiness = evaluateAnnualReadinessGates({
    company,
    incomeYear,
    setups: samePeriod(input.setups),
    ledgerEntries: samePeriod(input.ledgerEntries),
    holdingActions: samePeriod(input.holdingActions),
    bankTransactions: samePeriod(input.bankTransactions),
    documents: samePeriod(input.documents),
    overrides,
    locks: samePeriod(input.locks),
    annualData: input.annualData,
    billingAccount: input.billingAccount,
    authorityPermissions,
    filingPreviews: samePeriod(input.filingPreviews),
    filingSubmissions: samePeriod(input.filingSubmissions),
  }).find((snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven");

  return {
    preview,
    release: {
      actorId: input.actorId,
      membership: input.membership,
      authorityPermissions,
      authorityTestRuns: input.authorityTestRuns.filter((row) => row.company_id === company.id),
      billingAccount: input.billingAccount,
      filingReady: currentReadiness?.status === "ready",
      stepUpContext: input.stepUpContext,
      launchSignoffs: input.launchSignoffRows.map(normalizeLaunchSignoff),
      hardReviewBlockCount: input.reviewComments.filter(
        (row) => row.preview_id === preview.id && row.severity === "hard_block",
      ).length,
      blockingOverrideCount: overrides.filter(
        (row) =>
          row.risk_level === "block" &&
          (row.preview_id === preview.id ||
            row.filing === preview.filing ||
            row.field_target.startsWith("rf1086.")),
      ).length,
      confirmations: input.confirmations,
      ...(input.now ? { now: input.now } : {}),
    },
  };
}
