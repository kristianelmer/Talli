import type { AnnualReadinessIssue } from "./annual-readiness.ts";
import type { AuthorityObligation } from "./authority-permission.ts";
import { authorityObligationLabel } from "./authority-permission.ts";
import type { FilingDeadline } from "./deadlines.ts";
import type {
  CompanyWorkspaceRow,
  DocumentRow,
  FilingReadinessSnapshotRow,
  FilingReviewCommentRow,
  FilingSubmissionRow,
} from "./supabase/server.ts";

export type AnnualWorkspaceContext = { companyId: string; incomeYear: number };
export type AnnualWorkspaceRole = "owner" | "reviewer" | "read_only";
export type AnnualWorkspaceStatus = "not_started" | "ready" | "warning" | "blocked" | "submitted";
export type AnnualWorkspaceAction = { label: string; href: string };

export type AnnualObligationViewModel = {
  obligation: AuthorityObligation;
  label: string;
  href: string;
  status: AnnualWorkspaceStatus;
  statusLabel: string;
  deadline: FilingDeadline | null;
  hardBlocks: AnnualReadinessIssue[];
  warnings: AnnualReadinessIssue[];
  acceptedWarnings: AnnualReadinessIssue[];
  unsupported: boolean;
  receiptId: string | null;
  nextAction: AnnualWorkspaceAction;
};

export type AnnualWorkspaceViewModel = {
  context: AnnualWorkspaceContext;
  company: Pick<CompanyWorkspaceRow, "id" | "name" | "org_number">;
  role: AnnualWorkspaceRole;
  obligations: AnnualObligationViewModel[];
  nextAction: AnnualWorkspaceAction;
  documents: DocumentRow[];
  comments: FilingReviewCommentRow[];
};

type SnapshotInput = Pick<
  FilingReadinessSnapshotRow,
  "obligation" | "income_year" | "status" | "ready" | "hard_blocks" | "warnings" | "accepted_warnings" | "evaluated_at"
>;

type SubmissionInput = Pick<
  FilingSubmissionRow,
  "filing" | "income_year" | "status" | "receipt_id" | "updated_at"
>;

const obligationOrder: AuthorityObligation[] = [
  "aksjonaerregisteroppgaven",
  "aarsregnskap",
  "skattemelding",
];

const filingByObligation: Record<AuthorityObligation, FilingDeadline["filing"]> = {
  aksjonaerregisteroppgaven: "aksjonærregisteroppgaven",
  aarsregnskap: "årsregnskap",
  skattemelding: "skattemelding for AS",
};

const unsupportedCodes = new Set([
  "unsupported_entity",
  "tax_return_unclear_fritaksmetoden",
  "tax_return_three_percent_treatment_missing",
  "tax_return_three_percent_treatment_unresolved",
  "tax_return_shareholder_loan_review_required",
]);

const actionLabelByIssue: Record<string, string> = {
  notes_missing: "Fullfør noter",
  annual_data_missing: "Svar på årsavslutningen",
  opening_balance_missing: "Legg inn åpningsbalanse",
  documents_missing: "Last opp dokumentasjon",
  authority_permission_missing: "Bekreft innsendingsrett",
  filing_package_not_paid: "Fullfør betaling",
};

const statusLabel: Record<AnnualWorkspaceStatus, string> = {
  not_started: "Ikke startet",
  ready: "Klar",
  warning: "Må kontrolleres",
  blocked: "Må løses",
  submitted: "Sendt inn",
};

export function annualOverviewHref(context: AnnualWorkspaceContext) {
  return `/companies/${encodeURIComponent(context.companyId)}/annual-reporting/${context.incomeYear}`;
}

export function annualObligationHref(context: AnnualWorkspaceContext, obligation: AuthorityObligation) {
  return `${annualOverviewHref(context)}/${obligation}`;
}

export function annualReviewHref(context: AnnualWorkspaceContext) {
  return `${annualOverviewHref(context)}/review`;
}

export function buildAnnualWorkspaceViewModel(input: {
  context: AnnualWorkspaceContext;
  company: AnnualWorkspaceViewModel["company"];
  role: AnnualWorkspaceRole;
  snapshots: SnapshotInput[];
  deadlines: FilingDeadline[];
  documents: DocumentRow[];
  comments: FilingReviewCommentRow[];
  submissions: SubmissionInput[];
}): AnnualWorkspaceViewModel {
  const obligations = obligationOrder.map((obligation) => buildObligation(input, obligation));
  const next = obligations.find((item) => item.status === "blocked")
    ?? obligations.find((item) => item.status === "warning")
    ?? obligations.find((item) => item.status !== "submitted")
    ?? null;

  return {
    context: input.context,
    company: input.company,
    role: input.role,
    obligations,
    nextAction: next?.nextAction ?? { label: "Se kvitteringer", href: annualReviewHref(input.context) },
    documents: input.documents,
    comments: input.comments,
  };
}

function buildObligation(
  input: Parameters<typeof buildAnnualWorkspaceViewModel>[0],
  obligation: AuthorityObligation,
): AnnualObligationViewModel {
  const snapshot = input.snapshots.find(
    (item) => item.obligation === obligation && item.income_year === input.context.incomeYear,
  );
  const filing = filingByObligation[obligation];
  const submission = input.submissions
    .filter((item) => item.income_year === input.context.incomeYear && item.filing === filing && item.receipt_id)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0];
  const status: AnnualWorkspaceStatus = submission?.receipt_id
    ? "submitted"
    : snapshot?.status ?? "not_started";
  const firstIssue = snapshot?.hard_blocks[0] ?? snapshot?.warnings[0] ?? null;
  const href = annualObligationHref(input.context, obligation);
  const nextAction = status === "submitted"
    ? { label: "Se kvittering", href: annualReviewHref(input.context) }
    : firstIssue
      ? { label: actionLabelByIssue[firstIssue.code] ?? "Løs åpent punkt", href: `${href}#issue-${firstIssue.code}` }
      : status === "ready"
        ? { label: "Gå til gjennomgang", href: annualReviewHref(input.context) }
        : { label: "Start", href };

  return {
    obligation,
    label: authorityObligationLabel(obligation),
    href,
    status,
    statusLabel: statusLabel[status],
    deadline: input.deadlines.find((item) => item.filing === filing) ?? null,
    hardBlocks: snapshot?.hard_blocks ?? [],
    warnings: snapshot?.warnings ?? [],
    acceptedWarnings: snapshot?.accepted_warnings ?? [],
    unsupported: Boolean(snapshot?.hard_blocks.some((issue) => unsupportedCodes.has(issue.code))),
    receiptId: submission?.receipt_id ?? null,
    nextAction,
  };
}
