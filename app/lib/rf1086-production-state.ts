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
import { stepUpContextFromRecords } from "./security.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export type Rf1086ProductionStateDatabaseClient = {
  from(table: string): any;
};

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

function stateLoadFailed() {
  return new Rf1086ProductionRunnerError(
    "rf1086_production_state_load_failed",
    "RF-1086 production state could not be loaded.",
  );
}

async function loadQuery<T>(query: PromiseLike<{ data: T; error: unknown }>): Promise<T> {
  try {
    const result = await query;
    if (result.error) throw stateLoadFailed();
    return result.data;
  } catch (error) {
    if (error instanceof Rf1086ProductionRunnerError) throw error;
    throw stateLoadFailed();
  }
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

export async function loadRf1086ProductionState(input: {
  databaseClient: Rf1086ProductionStateDatabaseClient;
  actorId: string;
  previewId: string;
  confirmations: Rf1086SubmissionConfirmations;
  now?: Date;
}) {
  if (
    !input.databaseClient ||
    typeof input.databaseClient.from !== "function" ||
    !UUID_PATTERN.test(input.actorId) ||
    !UUID_PATTERN.test(input.previewId) ||
    (input.now && Number.isNaN(input.now.getTime())) ||
    input.confirmations?.authorityConfirmed !== true ||
    input.confirmations?.previewConfirmed !== true
  ) {
    throw stateInvalid();
  }

  const preview = await loadQuery<FilingPreviewRow | null>(
    input.databaseClient
      .from("filing_previews")
      .select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at")
      .eq("id", input.previewId)
      .maybeSingle(),
  );
  if (
    !preview ||
    preview.id !== input.previewId ||
    !UUID_PATTERN.test(preview.company_id) ||
    !Number.isInteger(preview.income_year) ||
    preview.income_year < 2000 ||
    preview.income_year > 2100
  ) {
    throw stateLoadFailed();
  }

  const membership = await loadQuery<CompanyMembershipRow | null>(
    input.databaseClient
      .from("company_memberships")
      .select("company_id, user_id, role, accepted_at")
      .eq("company_id", preview.company_id)
      .eq("user_id", input.actorId)
      .eq("role", "owner")
      .maybeSingle(),
  );
  if (
    !membership ||
    membership.company_id !== preview.company_id ||
    membership.user_id !== input.actorId ||
    membership.role !== "owner" ||
    !membership.accepted_at
  ) {
    throw new Rf1086ProductionRunnerError(
      "rf1086_production_owner_required",
      "RF-1086 production requires an accepted company owner.",
    );
  }

  const companyId = preview.company_id;
  const incomeYear = preview.income_year;
  const [
    company,
    setups,
    ledgerEntries,
    holdingActions,
    bankTransactions,
    documents,
    overrides,
    locks,
    annualData,
    billingAccount,
    authorityPermissions,
    filingPreviews,
    filingSubmissions,
    authorityTestRuns,
    stepUpEvent,
    securityGrant,
    launchSignoffRows,
    reviewComments,
  ] = await Promise.all([
    loadQuery<any>(input.databaseClient.from("companies").select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at").eq("id", companyId).maybeSingle()),
    loadQuery<any[]>(input.databaseClient.from("opening_balance_setups").select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any[]>(input.databaseClient.from("ledger_entries").select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any[]>(input.databaseClient.from("holding_actions").select("id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any[]>(input.databaseClient.from("bank_transactions").select("id, company_id, income_year, transaction_date, text, amount, balance, source_hash, matched_entry_id, matched_action_id, accepted_warning, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any[]>(input.databaseClient.from("documents").select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any[]>(input.databaseClient.from("filing_overrides").select("id, preview_id, company_id, income_year, filing, field_target, old_value, new_value, reason, risk_level, owner_confirmed_by, owner_confirmed_at, created_by, created_at").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any[]>(input.databaseClient.from("period_locks").select("id, company_id, income_year, reason, locked_by, locked_at").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any>(input.databaseClient.from("annual_data").select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at").eq("company_id", companyId).eq("income_year", incomeYear).maybeSingle()),
    loadQuery<any>(input.databaseClient.from("billing_accounts").select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref").eq("company_id", companyId).maybeSingle()),
    loadQuery<any[]>(input.databaseClient.from("authority_permissions").select("company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled").eq("company_id", companyId)),
    loadQuery<any[]>(input.databaseClient.from("filing_previews").select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any[]>(input.databaseClient.from("filing_submissions").select("id, preview_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by").eq("company_id", companyId).eq("income_year", incomeYear)),
    loadQuery<any[]>(input.databaseClient.from("authority_test_runs").select("company_id, obligation, status, receipt_reference, archive_reference, recorded_at").eq("company_id", companyId).eq("obligation", "aksjonaerregisteroppgaven")),
    loadQuery<any>(input.databaseClient.from("step_up_events").select("actor_id, mfa_verified_at").eq("actor_id", input.actorId).order("mfa_verified_at", { ascending: false }).limit(1).maybeSingle()),
    loadQuery<any>(input.databaseClient.from("production_security_grants").select("actor_id, security_review_approved, production_credentials_enabled, expires_at, revoked_at").eq("actor_id", input.actorId).maybeSingle()),
    loadQuery<any[]>(input.databaseClient.from("launch_signoffs").select("key, status, reviewer, reviewed_at, evidence_link, decision, recorded_by, updated_at").eq("key", "rf1086_authority")),
    loadQuery<any[]>(input.databaseClient.from("filing_review_comments").select("preview_id, severity").eq("preview_id", preview.id).eq("severity", "hard_block")),
  ]);
  if (!company) throw stateLoadFailed();

  return deriveRf1086ProductionState({
    actorId: input.actorId,
    preview,
    company,
    membership,
    incomeYear,
    setups,
    ledgerEntries,
    holdingActions,
    bankTransactions,
    documents,
    overrides,
    locks,
    annualData,
    billingAccount,
    authorityPermissions,
    filingPreviews,
    filingSubmissions,
    authorityTestRuns,
    stepUpContext: stepUpContextFromRecords(input.actorId, stepUpEvent, securityGrant, input.now),
    launchSignoffRows,
    reviewComments,
    confirmations: input.confirmations,
    ...(input.now ? { now: input.now } : {}),
  });
}
