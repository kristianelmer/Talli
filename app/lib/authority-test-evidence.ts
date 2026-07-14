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

export type CompanyTaxReturnAuthorityTestRunImportInput = {
  companyId: string;
  expectedCompanyOrgNumber: string;
  expectedIncomeYear: number;
  evidence: unknown;
  evidenceUrl?: string | null;
  recordedBy: string;
  recordedAt?: string;
};

const COMPANY_TAX_SCOPES = [
  "altinn:instances.read",
  "altinn:instances.write",
  "skatteetaten:formueinntekt/skattemelding",
];
const COMPANY_TAX_SCHEMAS = [
  "naeringsspesifikasjon_v6_ekstern.xsd",
  "skattemeldingUpersonlig_v5_ekstern.xsd",
  "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd",
];
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const INSTANCE_ID_PATTERN = /^\d+\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const DATA_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

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

export function buildCompanyTaxReturnAuthorityTestRunFromEvidence(
  input: CompanyTaxReturnAuthorityTestRunImportInput,
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
  if (!Number.isInteger(input.expectedIncomeYear)
    || input.expectedIncomeYear < 2000
    || input.expectedIncomeYear > 2100
    || evidence.incomeYear !== input.expectedIncomeYear) {
    throw new Error("TT02-evidensens inntektsår matcher ikke aktivt regnskapsår.");
  }
  if (evidence.schemaVersion !== 2 || evidence.status !== "submitted_and_receipted") {
    throw new Error("TT02-evidensen må være ferdig innsendt med offisiell tilbakemelding.");
  }
  if (evidence.environment !== "test") {
    throw new Error("Bare TT02 test-evidens kan importeres.");
  }
  if (evidence.productionEnabled !== false) {
    throw new Error("TT02-evidens med produksjon aktivert kan ikke importeres.");
  }
  if (evidence.secretsStored !== false) {
    throw new Error("TT02-evidensen kan ikke inneholde lagrede hemmeligheter.");
  }

  const scopes = evidenceString(evidence.scope, "Scope").split(/\s+/u).sort();
  if (scopes.length !== COMPANY_TAX_SCOPES.length
    || scopes.some((scope, index) => scope !== COMPANY_TAX_SCOPES[index])) {
    throw new Error("TT02-evidensen bruker feil scope-sett for skattemelding.");
  }
  if (evidence.systemUserResource !== "app_skd_formueinntekt-skattemelding-v2") {
    throw new Error("TT02-evidensen bruker feil systembrukerressurs for skattemelding.");
  }

  const localValidation = objectValue(evidence.localSchemaValidation);
  const schemas = Array.isArray(localValidation.schemas)
    ? localValidation.schemas.filter((schema): schema is string => typeof schema === "string").sort()
    : [];
  if (localValidation.status !== "passed"
    || schemas.length !== COMPANY_TAX_SCHEMAS.length
    || schemas.some((schema, index) => schema !== COMPANY_TAX_SCHEMAS[index])) {
    throw new Error("TT02-evidensen mangler komplett lokal skjemavalidering.");
  }
  const authorityValidation = objectValue(evidence.authorityValidation);
  if (authorityValidation.result !== "validertOK"
    || !Array.isArray(authorityValidation.failureReasons)
    || authorityValidation.failureReasons.length !== 0) {
    throw new Error("TT02-evidensen mangler validertOK uten blokkerende feil.");
  }

  const payloadHashes = objectValue(evidence.payloadHashes);
  const skattemeldingHash = evidenceString(payloadHashes.skattemelding, "Skattemeldingshash");
  const naeringsspesifikasjonHash = evidenceString(
    payloadHashes.naeringsspesifikasjon,
    "Næringsspesifikasjonshash",
  );
  const validationEnvelopeHash = evidenceString(
    payloadHashes.validationEnvelope,
    "Valideringskonvolutthash",
  );
  const submissionEnvelopeHash = evidenceString(
    payloadHashes.submissionEnvelope,
    "Innsendingskonvolutthash",
  );
  const currentReferenceHash = evidenceString(
    evidence.currentDocumentReferenceHash,
    "Gjeldende dokumentreferansehash",
  );
  if (![skattemeldingHash, naeringsspesifikasjonHash, validationEnvelopeHash,
    submissionEnvelopeHash, currentReferenceHash].every((hash) => SHA256_PATTERN.test(hash))) {
    throw new Error("TT02-evidensens payload-hasher er ugyldige.");
  }

  const instance = objectValue(evidence.instance);
  const instanceId = evidenceString(instance.id, "Instans-id");
  const envelopeDataId = evidenceString(instance.envelopeDataId, "Konvoluttdata-id");
  if (!INSTANCE_ID_PATTERN.test(instanceId) || !DATA_ID_PATTERN.test(envelopeDataId)) {
    throw new Error("TT02-evidensens instans- eller konvoluttdata-id er ugyldig.");
  }
  if (instance.envelopeUploaded !== true || instance.fileScanResult !== "Clean") {
    throw new Error("TT02-evidensens innsendingskonvolutt er ikke ferdig og ren.");
  }
  if (instance.confirmationPrepared !== true || instance.processTask !== "confirmation") {
    throw new Error("TT02-evidensen mangler dokumentert personbekreftelse-handoff.");
  }
  const expectedConfirmationUrl = "https://skatt-test.sits.no/web/skattemelding-visning/altinn"
    + `?appId=skd/formueinntekt-skattemelding-v2&instansId=${instanceId}`;
  if (evidenceString(evidence.confirmationUrl, "Bekreftelseslenke") !== expectedConfirmationUrl) {
    throw new Error("TT02-evidensens personbekreftelseslenke er ugyldig.");
  }

  const archiveReference = `https://platform.tt02.altinn.no/storage/api/v1/instances/${instanceId}`;
  const receipt = objectValue(evidence.receipt);
  const receiptDataId = evidenceString(receipt.dataId, "Kvitteringsdata-id");
  const receiptHash = evidenceString(receipt.contentSha256, "Kvitteringshash");
  if (!DATA_ID_PATTERN.test(receiptDataId)
    || receipt.dataType !== "tilbakemelding"
    || !["application/xml", "text/xml"].includes(String(receipt.contentType))
    || !Number.isInteger(receipt.byteLength)
    || Number(receipt.byteLength) < 1
    || !SHA256_PATTERN.test(receiptHash)) {
    throw new Error("TT02-evidensens offisielle tilbakemelding er ugyldig.");
  }
  const receiptReference = evidenceString(receipt.reference, "Kvitteringsreferanse");
  if (receiptReference !== `${archiveReference}/data/${receiptDataId}`) {
    throw new Error("TT02-evidensens kvitteringsreferanse er ugyldig.");
  }

  const submission = objectValue(evidence.submission);
  if (submission.submitted !== true
    || !Number.isFinite(Date.parse(evidenceString(submission.processEndedAt, "Prosesslutt")))
    || submission.archived !== true
    || !Number.isFinite(Date.parse(evidenceString(submission.archivedAt, "Arkiveringstidspunkt")))
    || evidenceString(submission.archiveReference, "Arkivreferanse") !== archiveReference) {
    throw new Error("TT02-evidensens innsending eller arkiv er ufullstendig.");
  }

  const payloadHash = createHash("sha256")
    .update([
      `skattemelding:${skattemeldingHash}`,
      `naeringsspesifikasjon:${naeringsspesifikasjonHash}`,
      `validationEnvelope:${validationEnvelopeHash}`,
      `submissionEnvelope:${submissionEnvelopeHash}`,
    ].join("\n"))
    .digest("hex");

  return buildAuthorityTestRun({
    companyId: input.companyId,
    obligation: "skattemelding",
    environment: "test",
    status: "pending",
    testReference: `tt02:${instanceId}`,
    feedbackSummary: "validertOK; personbekreftelse fullført; offisiell tilbakemelding mottatt; myndighetsutfall venter på klassifisering.",
    receiptReference,
    archiveReference,
    evidenceUrl: input.evidenceUrl,
    payloadHash: `sha256:${payloadHash}`,
    recordedBy: input.recordedBy,
    recordedAt: input.recordedAt,
  });
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
