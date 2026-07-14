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
const INSTANCE_ID_PATTERN = /^\d+\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const DATA_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const RFC3339_INSTANT_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/u;
const MAX_EVIDENCE_URL_LENGTH = 2048;

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

function evidenceIsoDate(value: unknown, label: string): string {
  const timestamp = evidenceString(value, label);
  const match = RFC3339_INSTANT_PATTERN.exec(timestamp);
  if (!match) {
    throw new Error(`${label} er ugyldig i TT02-evidensen.`);
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const timezone = match[7];
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const offsetHour = timezone === "Z" ? 0 : Number(timezone.slice(1, 3));
  const offsetMinute = timezone === "Z" ? 0 : Number(timezone.slice(4, 6));
  if (month < 1
    || month > 12
    || day < 1
    || day > (daysInMonth[month - 1] ?? 0)
    || hour > 23
    || minute > 59
    || second > 59
    || offsetHour > 23
    || offsetMinute > 59
    || !Number.isFinite(Date.parse(timestamp))) {
    throw new Error(`${label} er ugyldig i TT02-evidensen.`);
  }
  return timestamp;
}

function safeCompanyTaxEvidenceUrl(value?: string | null): string | null {
  const normalized = optional(value);
  if (!normalized) return null;
  if (normalized.length > MAX_EVIDENCE_URL_LENGTH
    || normalized.includes("?")
    || normalized.includes("#")
    || /current_document_reference_sentinel/iu.test(normalized)) {
    throw new Error("TT02-evidenslenken må være en avgrenset HTTPS-lenke uten query eller fragment.");
  }
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error("TT02-evidenslenken må være en absolutt HTTPS-lenke.");
  }
  if (parsed.protocol !== "https:"
    || !parsed.hostname
    || parsed.username
    || parsed.password
    || parsed.search
    || parsed.hash) {
    throw new Error("TT02-evidenslenken må være en absolutt HTTPS-lenke uten credentials, query eller fragment.");
  }
  return parsed.href;
}

function rfc3339InstantParts(value: string) {
  const fraction = /\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/u.exec(value)?.[1] ?? "";
  const wholeSecond = value.replace(/\.\d+(?=Z|[+-]\d{2}:\d{2}$)/u, "");
  return {
    epochSecond: Date.parse(wholeSecond) / 1000,
    fraction,
  };
}

function rfc3339InstantIsAfter(left: string, right: string) {
  const leftParts = rfc3339InstantParts(left);
  const rightParts = rfc3339InstantParts(right);
  if (leftParts.epochSecond !== rightParts.epochSecond) {
    return leftParts.epochSecond > rightParts.epochSecond;
  }
  const fractionLength = Math.max(leftParts.fraction.length, rightParts.fraction.length);
  return leftParts.fraction.padEnd(fractionLength, "0")
    > rightParts.fraction.padEnd(fractionLength, "0");
}

function requireChronologicalEvidenceTimestamps(
  timestamps: Array<{ label: string; value: string }>,
) {
  for (let index = 1; index < timestamps.length; index += 1) {
    const previous = timestamps[index - 1];
    const current = timestamps[index];
    if (previous && current && rfc3339InstantIsAfter(previous.value, current.value)) {
      throw new Error(
        `TT02-evidensens tidskronologi er ugyldig: ${previous.label} kan ikke være etter ${current.label}.`,
      );
    }
  }
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

/** @internal Shared strict snapshot for company-tax evidence projections. */
export type ValidatedCompanyTaxReturnEvidence = {
  authorityRun: AuthorityTestRun;
  incomeYear: number;
  instanceId: string;
  envelopeDataId: string;
  archiveReference: string;
  payloadHash: string;
  payloadHashes: {
    skattemelding: string;
    naeringsspesifikasjon: string;
    validationEnvelope: string;
    submissionEnvelope: string;
  };
  currentDocumentReferenceHash: string;
  validatedAt: string;
  confirmationPreparedAt: string;
  processEndedAt: string;
  archivedAt: string;
  receiptRetrievedAt: string;
  receipt: {
    dataId: string;
    dataType: "tilbakemelding";
    contentType: "application/xml" | "text/xml";
    byteLength: number;
    contentSha256: string;
    reference: string;
  };
};

/** @internal Validate once, then map the same snapshot to every persistence shape. */
export function validatedCompanyTaxReturnEvidence(
  input: CompanyTaxReturnAuthorityTestRunImportInput,
): ValidatedCompanyTaxReturnEvidence {
  const evidence = objectValue(input.evidence);
  const evidenceUrl = safeCompanyTaxEvidenceUrl(input.evidenceUrl);
  const expectedOrgNumber = required(
    input.expectedCompanyOrgNumber,
    "Forventet organisasjonsnummer",
  );
  if (!/^\d{9}$/u.test(expectedOrgNumber)
    || evidenceString(evidence.companyOrgNumber, "Organisasjonsnummer") !== expectedOrgNumber) {
    throw new Error("TT02-evidensens organisasjonsnummer matcher ikke selskapet.");
  }
  if (input.expectedIncomeYear !== 2025
    || evidence.incomeYear !== 2025
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
  const validatedAt = evidenceIsoDate(evidence.validatedAt, "Valideringstidspunkt");

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
  const confirmationPreparedAt = evidenceIsoDate(
    evidence.confirmationPreparedAt,
    "Personbekreftelse-handoff-tidspunkt",
  );
  const expectedConfirmationUrl = "https://skatt-test.sits.no/web/skattemelding-visning/altinn"
    + `?appId=skd/formueinntekt-skattemelding-v2&instansId=${instanceId}`;
  if (evidenceString(evidence.confirmationUrl, "Bekreftelseslenke") !== expectedConfirmationUrl) {
    throw new Error("TT02-evidensens personbekreftelseslenke er ugyldig.");
  }

  const archiveReference = `https://platform.tt02.altinn.no/storage/api/v1/instances/${instanceId}`;
  const receipt = objectValue(evidence.receipt);
  const receiptDataId = evidenceString(receipt.dataId, "Kvitteringsdata-id");
  const receiptHash = evidenceString(receipt.contentSha256, "Kvitteringshash");
  const receiptContentType = receipt.contentType;
  if (!DATA_ID_PATTERN.test(receiptDataId)
    || receipt.dataType !== "tilbakemelding"
    || (receiptContentType !== "application/xml" && receiptContentType !== "text/xml")
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
  const processEndedAt = evidenceIsoDate(submission.processEndedAt, "Prosesslutt");
  const archivedAt = evidenceIsoDate(submission.archivedAt, "Arkiveringstidspunkt");
  if (submission.submitted !== true
    || submission.archived !== true
    || evidenceString(submission.archiveReference, "Arkivreferanse") !== archiveReference) {
    throw new Error("TT02-evidensens innsending eller arkiv er ufullstendig.");
  }
  const receiptRetrievedAt = evidenceIsoDate(
    evidence.receiptRetrievedAt,
    "Tilbakemeldingshentetidspunkt",
  );
  const recordedAt = input.recordedAt ?? receiptRetrievedAt;
  requireChronologicalEvidenceTimestamps([
    { label: "validering", value: validatedAt },
    { label: "personbekreftelse-handoff", value: confirmationPreparedAt },
    { label: "prosesslutt", value: processEndedAt },
    { label: "arkivering", value: archivedAt },
    { label: "tilbakemeldingshenting", value: receiptRetrievedAt },
  ]);

  const payloadHash = createHash("sha256")
    .update([
      `skattemelding:${skattemeldingHash}`,
      `naeringsspesifikasjon:${naeringsspesifikasjonHash}`,
      `validationEnvelope:${validationEnvelopeHash}`,
      `submissionEnvelope:${submissionEnvelopeHash}`,
    ].join("\n"))
    .digest("hex");

  const authorityRun = buildAuthorityTestRun({
    companyId: input.companyId,
    obligation: "skattemelding",
    environment: "test",
    status: "pending",
    testReference: `tt02:${instanceId}`,
    feedbackSummary: "validertOK; personbekreftelse fullført; offisiell tilbakemelding mottatt; myndighetsutfall venter på klassifisering.",
    receiptReference,
    archiveReference,
    evidenceUrl,
    payloadHash: `sha256:${payloadHash}`,
    recordedBy: input.recordedBy,
    recordedAt,
  });

  return {
    authorityRun,
    incomeYear: input.expectedIncomeYear,
    instanceId,
    envelopeDataId,
    archiveReference,
    payloadHash,
    payloadHashes: {
      skattemelding: skattemeldingHash,
      naeringsspesifikasjon: naeringsspesifikasjonHash,
      validationEnvelope: validationEnvelopeHash,
      submissionEnvelope: submissionEnvelopeHash,
    },
    currentDocumentReferenceHash: currentReferenceHash,
    validatedAt,
    confirmationPreparedAt,
    processEndedAt,
    archivedAt,
    receiptRetrievedAt,
    receipt: {
      dataId: receiptDataId,
      dataType: "tilbakemelding",
      contentType: receiptContentType,
      byteLength: Number(receipt.byteLength),
      contentSha256: receiptHash,
      reference: receiptReference,
    },
  };
}

export function buildCompanyTaxReturnAuthorityTestRunFromEvidence(
  input: CompanyTaxReturnAuthorityTestRunImportInput,
): AuthorityTestRun {
  return validatedCompanyTaxReturnEvidence(input).authorityRun;
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
