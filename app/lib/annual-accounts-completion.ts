import type {
  AnnualAccountsAltinnTestClient,
  AnnualAccountsDataElement,
  AnnualAccountsInstanceRef,
} from "./annual-accounts-altinn-client.ts";
import {
  inspectAnnualAccountsProgress,
  type AnnualAccountsDocuments,
  type AnnualAccountsJournal,
} from "./annual-accounts-orchestration.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const PARTY_ID_PATTERN = /^\d{1,20}$/u;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/u;

export type AnnualAccountsCompletionEvidence = {
  schemaVersion: 1;
  environment: "test";
  operationId: string;
  organizationNumber: string;
  incomeYear: number;
  instance: AnnualAccountsInstanceRef;
  completedAt: string;
  mainFormId: string;
  accountsFormId: string;
  signatureDataElementId: string;
  mainFormHash: string;
  accountsFormHash: string;
};

export class AnnualAccountsCompletionError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AnnualAccountsCompletionError";
    this.code = code;
  }
}

function completionError(code: string, message: string) {
  return new AnnualAccountsCompletionError(code, message);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function sameInstance(value: unknown, expected: AnnualAccountsInstanceRef): boolean {
  return (
    isRecord(value) &&
    typeof value.ownerPartyId === "string" &&
    PARTY_ID_PATTERN.test(value.ownerPartyId) &&
    typeof value.instanceGuid === "string" &&
    UUID_PATTERN.test(value.instanceGuid) &&
    value.ownerPartyId === expected.ownerPartyId &&
    value.instanceGuid === expected.instanceGuid
  );
}

function validElement(value: unknown, instanceGuid: string): value is AnnualAccountsDataElement {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    UUID_PATTERN.test(value.id) &&
    value.instanceGuid === instanceGuid &&
    typeof value.dataType === "string" &&
    typeof value.contentType === "string"
  );
}

function completionEvidenceInvalid(): never {
  throw completionError(
    "annual_accounts_completion_evidence_invalid",
    "Annual-accounts post-signature evidence does not match the locked instance.",
  );
}

export async function verifyAnnualAccountsSignedInstance(input: {
  documents: AnnualAccountsDocuments;
  journal: AnnualAccountsJournal;
  client: Pick<AnnualAccountsAltinnTestClient, "environment" | "inspectInstance">;
}): Promise<AnnualAccountsCompletionEvidence> {
  const progress = await inspectAnnualAccountsProgress({
    documents: input.documents,
    journal: input.journal,
  });
  const checkpoint = progress.checkpoint;
  if (
    !progress.complete ||
    progress.blocked ||
    checkpoint?.status !== "awaiting-person-signature" ||
    !checkpoint.instance ||
    !checkpoint.dataElements ||
    !checkpoint.signingTask
  ) {
    throw completionError(
      "annual_accounts_completion_not_ready",
      "Annual-accounts completion cannot be checked before the exact draft is locked for personal signing.",
    );
  }
  if (input.client.environment !== "test") completionEvidenceInvalid();
  const instance = checkpoint.instance;
  const checkpointDataElements = checkpoint.dataElements;

  const snapshot = await input.client.inspectInstance({
    instance,
    organizationNumber: checkpoint.organizationNumber,
  });
  if (
    !sameInstance(snapshot?.instance, instance) ||
    typeof snapshot?.organizationNumber !== "string" ||
    !ORG_NUMBER_PATTERN.test(snapshot.organizationNumber) ||
    snapshot.organizationNumber !== checkpoint.organizationNumber ||
    !isRecord(snapshot.process)
  ) {
    completionEvidenceInvalid();
  }
  if (snapshot.process.endedAt === null && isRecord(snapshot.process.currentTask)) {
    throw completionError(
      "annual_accounts_signature_incomplete",
      "Annual-accounts instance is still awaiting personal completion.",
    );
  }
  if (
    typeof snapshot.process.endedAt !== "string" ||
    snapshot.process.endedAt.length > 40 ||
    !TIMESTAMP_PATTERN.test(snapshot.process.endedAt) ||
    !Number.isFinite(Date.parse(snapshot.process.endedAt)) ||
    snapshot.process.currentTask !== null ||
    !Array.isArray(snapshot.dataElements) ||
    snapshot.dataElements.length < 3 ||
    snapshot.dataElements.length > 64 ||
    snapshot.dataElements.some((element) => !validElement(element, instance.instanceGuid))
  ) {
    completionEvidenceInvalid();
  }

  const elements = snapshot.dataElements as AnnualAccountsDataElement[];
  if (new Set(elements.map((element) => element.id)).size !== elements.length) completionEvidenceInvalid();
  const main = elements.filter((element) => element.id === checkpointDataElements.mainFormId);
  const accounts = elements.filter((element) => element.id === checkpointDataElements.accountsFormId);
  const signatures = elements.filter((element) => element.dataType === "signature");
  if (
    main.length !== 1 ||
    main[0].dataType !== "Hovedskjema" ||
    main[0].contentType !== "application/xml" ||
    accounts.length !== 1 ||
    accounts[0].dataType !== "Underskjema" ||
    accounts[0].contentType !== "application/xml" ||
    signatures.length !== 1 ||
    signatures[0].contentType !== "application/json" ||
    !SHA256_PATTERN.test(checkpoint.mainFormHash) ||
    !SHA256_PATTERN.test(checkpoint.accountsFormHash)
  ) {
    completionEvidenceInvalid();
  }

  return {
    schemaVersion: 1,
    environment: "test",
    operationId: checkpoint.operationId,
    organizationNumber: checkpoint.organizationNumber,
    incomeYear: checkpoint.incomeYear,
    instance,
    completedAt: snapshot.process.endedAt,
    mainFormId: main[0].id,
    accountsFormId: accounts[0].id,
    signatureDataElementId: signatures[0].id,
    mainFormHash: checkpoint.mainFormHash,
    accountsFormHash: checkpoint.accountsFormHash,
  };
}
