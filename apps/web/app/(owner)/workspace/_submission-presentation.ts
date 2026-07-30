import { authorityTestRunStatusLabel } from "../../lib/authority-test-evidence.ts";
import type { AuthorityTestRunRow, FilingSubmissionRow } from "../../lib/supabase/server.ts";

const TT02_ARCHIVE_REFERENCE_PATTERN =
  /^https:\/\/platform[.]tt02[.]altinn[.]no\/storage\/api\/v1\/instances\/[0-9]+\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;

type WorkspaceSubmission = Pick<
  FilingSubmissionRow,
  | "id"
  | "authority_test_run_id"
  | "company_id"
  | "income_year"
  | "mode"
  | "status"
  | "calls"
  | "receipt_id"
  | "feedback_items"
  | "submitted_payload_ref"
  | "preview_confirmed_at"
>;

type WorkspaceAuthorityTestRun = Pick<
  AuthorityTestRunRow,
  "id" | "status" | "archive_reference"
>;

function safeTt02ArchiveReference(value: string | null | undefined): string | null {
  return value && TT02_ARCHIVE_REFERENCE_PATTERN.test(value) ? value : null;
}

export function buildWorkspaceSubmissionPresentation(input: {
  submissions: readonly WorkspaceSubmission[];
  authorityTestRuns: readonly WorkspaceAuthorityTestRun[];
}) {
  const authorityRunsById = new Map(input.authorityTestRuns.map((run) => [run.id, run]));

  return {
    simulations: input.submissions
      .filter((submission) => submission.mode === "simulation")
      .map((submission) => ({ submission })),
    testAuthority: input.submissions
      .filter((submission) => submission.mode === "test_authority")
      .map((submission) => {
        const outcomeSummary = submission.authority_test_run_id
          ? authorityRunsById.get(submission.authority_test_run_id)
          : undefined;
        return {
          submission,
          statusLabel: outcomeSummary
            ? authorityTestRunStatusLabel(outcomeSummary.status)
            : "Testutfall mangler",
          archiveReference: safeTt02ArchiveReference(outcomeSummary?.archive_reference),
        };
      }),
  };
}
