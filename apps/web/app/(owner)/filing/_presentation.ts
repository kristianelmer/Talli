import type { AuthorityObligation } from "../../lib/authority-permission";
import type { FilingSubmissionRow } from "../../lib/supabase/server";

export const COMPANY_TAX_PENDING_FEEDBACK_COPY = {
  title: "TT02-tilbakemelding mottatt",
  badgeLabel: "Test – ikke produksjonsinnsending",
  body: "Myndighetsutfallet venter på klassifisering. Kvitteringen dokumenterer mottatt testtilbakemelding, ikke et endelig utfall.",
} as const;

export function obligationFilingString(obligation: AuthorityObligation): string {
  if (obligation === "aksjonaerregisteroppgaven") return "aksjonærregisteroppgaven";
  if (obligation === "skattemelding") return "skattemelding for AS";
  return "årsregnskap";
}

function archiveReference(submission: FilingSubmissionRow): string | null {
  if (submission.receipt_metadata && "archiveReference" in submission.receipt_metadata) {
    return typeof submission.receipt_metadata.archiveReference === "string" ? submission.receipt_metadata.archiveReference : null;
  }
  if (submission.submitted_payload_ref && "archiveReference" in submission.submitted_payload_ref) {
    return typeof submission.submitted_payload_ref.archiveReference === "string" ? submission.submitted_payload_ref.archiveReference : null;
  }
  return null;
}

export function buildOwnerFilingPresentation(input: {
  obligation: AuthorityObligation;
  incomeYear: number;
  submissions: readonly FilingSubmissionRow[];
  posted?: boolean;
  error?: string;
}) {
  const filing = obligationFilingString(input.obligation);
  const matchingSubmissions = input.submissions.filter(
    (submission) => submission.filing === filing && submission.income_year === input.incomeYear,
  );
  const pendingCompanyTaxSubmission = input.obligation === "skattemelding"
    ? matchingSubmissions.find(
      (submission) => submission.mode === "test_authority" && submission.status === "feedback_ready",
    ) ?? null
    : null;
  const receiptSubmission = matchingSubmissions.find((submission) => Boolean(submission.receipt_id)) ?? null;
  const submitted = !pendingCompanyTaxSubmission && Boolean(receiptSubmission);

  return {
    filing,
    primarySubmission: pendingCompanyTaxSubmission ?? receiptSubmission ?? matchingSubmissions[0] ?? null,
    pendingCompanyTaxSubmission,
    pendingFeedback: pendingCompanyTaxSubmission ? {
      ...COMPANY_TAX_PENDING_FEEDBACK_COPY,
      receiptId: pendingCompanyTaxSubmission.receipt_id,
      archiveReference: archiveReference(pendingCompanyTaxSubmission),
    } : null,
    submitted,
    showPostedSuccessBanner: Boolean(input.posted) && !pendingCompanyTaxSubmission,
    showProductionSubmitControl: input.obligation === "aksjonaerregisteroppgaven",
    errorMessage: input.error || null,
  };
}
