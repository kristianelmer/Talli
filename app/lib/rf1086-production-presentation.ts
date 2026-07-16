type Rf1086ProductionScope = {
  companyId: string;
  userId: string;
  incomeYear: number;
  obligation: string;
  caseProfile: string;
  environment: string;
};

type ScopedProductionSubmission = {
  id: string;
  company_id: string;
  user_id: string;
  income_year: number;
  obligation: string;
  case_profile: string;
  environment: string;
  created_at: string;
  updated_at: string;
};

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

export function selectLatestRf1086ProductionSubmission<T extends ScopedProductionSubmission>(
  submissions: readonly T[],
  scope: Rf1086ProductionScope,
): T | null {
  const exact = submissions.filter(
    (submission) => submission.company_id === scope.companyId
      && submission.user_id === scope.userId
      && submission.income_year === scope.incomeYear
      && submission.obligation === scope.obligation
      && submission.case_profile === scope.caseProfile
      && submission.environment === scope.environment,
  );

  exact.sort((left, right) =>
    timestamp(right.updated_at) - timestamp(left.updated_at)
      || timestamp(right.created_at) - timestamp(left.created_at)
      || right.id.localeCompare(left.id),
  );
  return exact[0] ?? null;
}

const OWNER_FEEDBACK_STATES: ReadonlySet<string> = new Set([
  "sent",
  "processing",
  "accepted",
  "rejected",
  "action_required",
  "unknown",
]);
const OWNER_ARTIFACT_CLASSIFICATIONS: ReadonlySet<string> = new Set([
  "accepted",
  "rejected",
  "action_required",
]);

export const RF1086_OWNER_ACTION_ERROR_CODES = [
  "invalid_request",
  "authentication_required",
  "configuration_unavailable",
  "approval_expired",
  "basis_unavailable",
  "connection_unavailable",
  "payload_changed",
  "send_unavailable",
  "status_unavailable",
  "status_busy",
  "unavailable",
] as const;

export type Rf1086OwnerActionErrorCode = typeof RF1086_OWNER_ACTION_ERROR_CODES[number];

type OwnerProductionCopy = {
  states: Record<string, {
    label: string;
    body: string;
    variant: "success" | "warning" | "danger" | "info";
  }>;
  artifacts: Record<string, string> & { unknown: string };
};

export function buildRf1086OwnerProductionPresentation(
  input: {
    feedbackState: string | null | undefined;
    submissionStatus: string | null | undefined;
    approved: boolean;
    artifacts: readonly {
      id: string;
      document_id: string;
      classification: string;
    }[];
  },
  copy: OwnerProductionCopy,
) {
  const feedbackState = typeof input.feedbackState === "string"
    && OWNER_FEEDBACK_STATES.has(input.feedbackState)
    ? input.feedbackState as "sent" | "processing" | "accepted" | "rejected" | "action_required" | "unknown"
    : null;
  const statusKey = input.submissionStatus === "sending"
    ? "sending"
    : feedbackState ?? (input.approved ? "approved" : "ready");
  const status = copy.states[statusKey] ?? copy.states.ready;

  return {
    status: {
      label: status.label,
      body: status.body,
      variant: status.variant,
    },
    artifacts: input.artifacts.map((artifact) => {
      const classification = OWNER_ARTIFACT_CLASSIFICATIONS.has(artifact.classification)
        ? artifact.classification
        : "unknown";
      return {
        id: artifact.id,
        documentId: artifact.document_id,
        label: copy.artifacts[classification] ?? copy.artifacts.unknown,
      };
    }),
  };
}

export function isRf1086OwnerActionErrorCode(
  value: unknown,
): value is Rf1086OwnerActionErrorCode {
  return typeof value === "string"
    && (RF1086_OWNER_ACTION_ERROR_CODES as readonly string[]).includes(value);
}

export function rf1086OwnerActionErrorMessage(
  value: unknown,
  copy: Record<Rf1086OwnerActionErrorCode, string>,
) {
  return copy[isRf1086OwnerActionErrorCode(value) ? value : "unavailable"];
}
