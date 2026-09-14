import { createHash } from "node:crypto";

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

export type AnnualAccountsAuthorityTestRunImportInput = {
  companyId: string;
  expectedCompanyOrgNumber: string;
  evidence: unknown;
  evidenceUrl?: string | null;
  recordedBy: string;
  recordedAt?: string;
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

function objectValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function evidenceString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} mangler i TT02-evidensen.`);
  }
  return value.trim();
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

export function buildAnnualAccountsAuthorityTestRunFromEvidence(
  input: AnnualAccountsAuthorityTestRunImportInput,
): AuthorityTestRun {
  const evidence = objectValue(input.evidence);
  const expectedOrgNumber = required(
    input.expectedCompanyOrgNumber,
    "Forventet organisasjonsnummer",
  );
  if (!/^\d{9}$/u.test(expectedOrgNumber)
    || evidenceString(evidence.companyOrgNumber, "Organisasjonsnummer") !== expectedOrgNumber) {
    throw new Error("TT02-evidensens organisasjonsnummer matcher ikke selskapet.");
  }
  if (evidence.environment !== "test") {
    throw new Error("Bare TT02 test-evidens kan importeres.");
  }
  if (evidence.productionEnabled !== false) {
    throw new Error("TT02-evidens med produksjon aktivert kan ikke importeres.");
  }
  if (evidence.systemUserResource !== "app_brg_aarsregnskap-vanlig-202406") {
    throw new Error("TT02-evidensen bruker feil årsregnskapsressurs.");
  }
  if (evidence.status !== "submitted_and_archived"
    || evidence.signed !== true
    || evidence.submitted !== true) {
    throw new Error("TT02-evidensen må være signert og sendt før import.");
  }

  const validation = objectValue(evidence.validation);
  if (validation.hasErrors !== false) {
    throw new Error("TT02-evidensen har valideringsfeil.");
  }
  const instance = objectValue(evidence.instance);
  const instanceId = evidenceString(instance.id, "Instans-id");
  if (!/^\d+\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(instanceId)) {
    throw new Error("TT02-evidensens instans-id er ugyldig.");
  }

  const submission = objectValue(evidence.submission);
  if (submission.processCompleted !== true
    || submission.signed !== true
    || submission.submitted !== true
    || submission.archived !== true
    || !Number.isFinite(Date.parse(evidenceString(submission.processEndedAt, "Prosesslutt")))) {
    throw new Error("TT02-evidensens signerings- og innsendingstilstand er ufullstendig.");
  }
  const expectedArchiveReference = `https://platform.tt02.altinn.no/storage/api/v1/instances/${instanceId}`;
  const archiveReference = evidenceString(submission.archiveReference, "Arkivreferanse");
  if (archiveReference !== expectedArchiveReference) {
    throw new Error("TT02-evidensens arkivreferanse er ugyldig.");
  }

  const receipt = objectValue(submission.receipt);
  const receiptDataId = evidenceString(receipt.dataId, "Kvitteringsdata-id");
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(receiptDataId)
    || receipt.dataType !== "ref-data-as-pdf"
    || receipt.contentType !== "application/pdf") {
    throw new Error("TT02-evidensens kvittering er ugyldig.");
  }
  const receiptReference = evidenceString(receipt.reference, "Kvitteringsreferanse");
  if (receiptReference !== `${expectedArchiveReference}/data/${receiptDataId}`) {
    throw new Error("TT02-evidensens kvitteringsreferanse er ugyldig.");
  }

  const payloadHashes = objectValue(evidence.payloadHashes);
  const mainFormHash = evidenceString(payloadHashes.mainForm, "Hovedskjemahash");
  const companyAccountsHash = evidenceString(
    payloadHashes.companyAccounts,
    "Selskapsregnskapshash",
  );
  if (!/^[0-9a-f]{64}$/u.test(mainFormHash) || !/^[0-9a-f]{64}$/u.test(companyAccountsHash)) {
    throw new Error("TT02-evidensens payload-hasher er ugyldige.");
  }
  const payloadHash = createHash("sha256")
    .update(`mainForm:${mainFormHash}\ncompanyAccounts:${companyAccountsHash}`)
    .digest("hex");

  const inbox = objectValue(evidence.inbox);
  const inboxStatus = evidenceString(inbox.status, "Innboksstatus");
  const inboxDisplayStatus = evidenceString(inbox.displayStatus, "Innboksstatusvisning");
  const inboxConfirmation = evidenceString(inbox.confirmation, "Innboksbekreftelse");

  return buildAuthorityTestRun({
    companyId: input.companyId,
    obligation: "aarsregnskap",
    environment: "test",
    status: "pending",
    testReference: `tt02:${instanceId}`,
    feedbackSummary: `${inboxDisplayStatus} (${inboxStatus}): ${inboxConfirmation}`,
    receiptReference,
    archiveReference,
    evidenceUrl: input.evidenceUrl,
    payloadHash: `sha256:${payloadHash}`,
    recordedBy: input.recordedBy,
    recordedAt: input.recordedAt,
  });
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
