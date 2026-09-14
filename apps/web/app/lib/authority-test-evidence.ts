import type { AuthorityObligation } from "./authority-permission.ts";

export type AuthorityTestRunStatus = "accepted" | "rejected" | "blocked" | "pending";
export type AuthorityTestRunEnvironment = "test" | "manual_evidence";
export type AuthorityTestEvidenceGateStatus =
  | "test_evidence_ready"
  | "test_evidence_missing"
  | "test_evidence_rejected"
  | "test_evidence_blocked"
  | "test_evidence_pending";

export type AuthorityTestRunInput = {
  companyId: string;
  obligation: AuthorityObligation;
  environment?: AuthorityTestRunEnvironment;
  status: AuthorityTestRunStatus;
  testReference: string;
  feedbackSummary?: string;
  receiptReference?: string | null;
  archiveReference?: string | null;
  evidenceUrl?: string | null;
  payloadHash?: string | null;
  recordedBy: string;
  recordedAt?: string;
};

export type AuthorityTestRun = {
  company_id: string;
  obligation: AuthorityObligation;
  environment: AuthorityTestRunEnvironment;
  status: AuthorityTestRunStatus;
  test_reference: string;
  feedback_summary: string;
  receipt_reference: string | null;
  archive_reference: string | null;
  evidence_url: string | null;
  payload_hash: string | null;
  recorded_by: string;
  recorded_at: string;
};

export type AuthorityTestEvidenceGate = {
  status: AuthorityTestEvidenceGateStatus;
  ready: boolean;
  message: string;
};

function required(value: string, label: string) {
  if (!value.trim()) {
    throw new Error(`${label} mangler.`);
  }
  return value.trim();
}

function optional(value?: string | null) {
  const trimmed = value?.trim() ?? "";
  return trimmed ? trimmed : null;
}

export function buildAuthorityTestRun(input: AuthorityTestRunInput): AuthorityTestRun {
  if (!["accepted", "rejected", "blocked", "pending"].includes(input.status)) {
    throw new Error("Ugyldig teststatus.");
  }
  const recordedAt = input.recordedAt ?? new Date().toISOString();
  return {
    company_id: required(input.companyId, "Company id"),
    obligation: input.obligation,
    environment: input.environment ?? "test",
    status: input.status,
    test_reference: required(input.testReference, "Testreferanse"),
    feedback_summary: input.feedbackSummary?.trim() ?? "",
    receipt_reference: optional(input.receiptReference),
    archive_reference: optional(input.archiveReference),
    evidence_url: optional(input.evidenceUrl),
    payload_hash: optional(input.payloadHash),
    recorded_by: required(input.recordedBy, "Recorded by"),
    recorded_at: recordedAt,
  };
}

export function authorityTestRunStatusLabel(status: AuthorityTestRunStatus): string {
  if (status === "accepted") return "Akseptert test-evidens";
  if (status === "rejected") return "Avvist test-evidens";
  if (status === "blocked") return "Blokkert test-evidens";
  return "Venter på klassifisering";
}

export function authorityTestEvidenceGateStatusLabel(status: AuthorityTestEvidenceGateStatus): string {
  if (status === "test_evidence_ready") return "Test-evidens klar";
  if (status === "test_evidence_rejected") return "Test-evidens avvist";
  if (status === "test_evidence_blocked") return "Test-evidens blokkert";
  if (status === "test_evidence_pending") return "Venter på klassifisering";
  return "Test-evidens mangler";
}

export function authorityTestEvidenceGate(
  runs: Pick<AuthorityTestRun, "obligation" | "status" | "receipt_reference" | "archive_reference" | "recorded_at">[],
  obligation: AuthorityObligation,
): AuthorityTestEvidenceGate {
  const latest = runs
    .filter((run) => run.obligation === obligation)
    .sort((a, b) => b.recorded_at.localeCompare(a.recorded_at))[0];

  if (!latest) {
    return {
      status: "test_evidence_missing",
      ready: false,
      message: "Testmiljoe- eller manuell evidens mangler for denne plikten.",
    };
  }
  if (latest.status === "rejected") {
    return {
      status: "test_evidence_rejected",
      ready: false,
      message: "Siste test-evidens er avvist. Rett payload/filingflyt foer produksjon.",
    };
  }
  if (latest.status === "blocked") {
    return {
      status: "test_evidence_blocked",
      ready: false,
      message: "Siste test-evidens er blokkert av myndighet/API-tilgang.",
    };
  }
  if (latest.status === "pending") {
    return {
      status: "test_evidence_pending",
      ready: false,
      message: "Test-evidens er registrert, men ikke akseptert.",
    };
  }
  if (!latest.receipt_reference || !latest.archive_reference) {
    return {
      status: "test_evidence_missing",
      ready: false,
      message: "Akseptert test-evidens maa ha kvitteringsref og arkivref.",
    };
  }
  return {
    status: "test_evidence_ready",
    ready: true,
    message: "Akseptert test-evidens med kvittering og arkivref er lagret.",
  };
}
