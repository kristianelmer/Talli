import { createHash } from "node:crypto";

import {
  AnnualAccountsAltinnError,
  type AnnualAccountsAltinnTestClient,
  type AnnualAccountsInstanceRef,
  type AnnualAccountsValidationIssue,
} from "./annual-accounts-altinn-client.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const PARTY_ID_PATTERN = /^\d{1,20}$/u;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const SAFE_CODE_PATTERN = /^[\p{L}\p{N}._:/\-[\]]{1,128}$/u;
const XML_UNSAFE_PATTERN = /<!\s*(?:DOCTYPE|ENTITY)\b/iu;
const XML_CONTROL_PATTERN = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/u;
const MAX_XML_BYTES = 10 * 1024 * 1024;
const MAX_CODES = 100;

export type AnnualAccountsOperation =
  | "create-draft"
  | "upload-main-form"
  | "upload-accounts-form"
  | "validate"
  | "lock-for-signature";

export type AnnualAccountsCallStatus =
  | "prepared"
  | "sent"
  | "accepted"
  | "failed-retryable"
  | "failed-blocked";

export type AnnualAccountsCheckpointStatus =
  | "in-progress"
  | "awaiting-person-signature"
  | "failed-retryable"
  | "failed-blocked";

export type AnnualAccountsCall = {
  operation: AnnualAccountsOperation;
  status: AnnualAccountsCallStatus;
  requestHash: string;
  preparedAt: string;
  acceptedAt: string | null;
  failureCode: string | null;
};

export type AnnualAccountsValidationEvidence = {
  valid: boolean;
  errorCodes: string[];
  warningCodes: string[];
};

export type AnnualAccountsCheckpoint = {
  schemaVersion: 1;
  revision: number;
  operationId: string;
  environment: "test";
  organizationNumber: string;
  incomeYear: number;
  payloadHash: string;
  mainFormHash: string;
  accountsFormHash: string;
  status: AnnualAccountsCheckpointStatus;
  instance: AnnualAccountsInstanceRef | null;
  dataElements: { mainFormId: string; accountsFormId: string } | null;
  validation: AnnualAccountsValidationEvidence | null;
  signingTask: { elementId: string; altinnTaskType: "signing" } | null;
  calls: AnnualAccountsCall[];
  failureCode: string | null;
};

export type AnnualAccountsJournal = {
  load(operationId: string): Promise<AnnualAccountsCheckpoint | null>;
  save(checkpoint: AnnualAccountsCheckpoint, expectedRevision: number | null): Promise<void>;
};

export type AnnualAccountsDocuments = {
  operationId: string;
  organizationNumber: string;
  incomeYear: number;
  mainFormXml: string;
  accountsFormXml: string;
};

export class AnnualAccountsOrchestrationError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AnnualAccountsOrchestrationError";
    this.code = code;
  }
}

function orchestrationError(code: string, message: string) {
  return new AnnualAccountsOrchestrationError(code, message);
}

function sha256(value: string) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  return actual.length === expected.length && actual.every((key, index) => key === [...expected].sort()[index]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && Number.isFinite(Date.parse(value));
}

function hasValidOrganizationNumberChecksum(value: string) {
  const weights = [3, 2, 7, 6, 5, 4, 3, 2];
  const sum = weights.reduce((total, weight, index) => total + weight * Number(value[index]), 0);
  const remainder = 11 - (sum % 11);
  const checksum = remainder === 11 ? 0 : remainder;
  return checksum !== 10 && checksum === Number(value[8]);
}

function checkpointInvalid(): never {
  throw orchestrationError(
    "annual_accounts_checkpoint_invalid",
    "Stored annual-accounts checkpoint is invalid or contains forbidden fields.",
  );
}

function assertInstance(value: unknown): value is AnnualAccountsInstanceRef {
  return (
    isRecord(value) &&
    exactKeys(value, ["ownerPartyId", "instanceGuid"]) &&
    typeof value.ownerPartyId === "string" &&
    PARTY_ID_PATTERN.test(value.ownerPartyId) &&
    typeof value.instanceGuid === "string" &&
    UUID_PATTERN.test(value.instanceGuid)
  );
}

function assertDataElements(value: unknown) {
  return (
    isRecord(value) &&
    exactKeys(value, ["mainFormId", "accountsFormId"]) &&
    typeof value.mainFormId === "string" &&
    UUID_PATTERN.test(value.mainFormId) &&
    typeof value.accountsFormId === "string" &&
    UUID_PATTERN.test(value.accountsFormId) &&
    value.mainFormId !== value.accountsFormId
  );
}

function assertCodeList(value: unknown) {
  return (
    Array.isArray(value) &&
    value.length <= MAX_CODES &&
    value.every((code) => typeof code === "string" && SAFE_CODE_PATTERN.test(code)) &&
    new Set(value).size === value.length &&
    value.every((code, index) => index === 0 || String(value[index - 1]) < String(code))
  );
}

function assertValidation(value: unknown) {
  return (
    isRecord(value) &&
    exactKeys(value, ["valid", "errorCodes", "warningCodes"]) &&
    typeof value.valid === "boolean" &&
    assertCodeList(value.errorCodes) &&
    assertCodeList(value.warningCodes) &&
    value.valid === ((value.errorCodes as unknown[]).length === 0)
  );
}

function assertSigningTask(value: unknown) {
  return (
    isRecord(value) &&
    exactKeys(value, ["elementId", "altinnTaskType"]) &&
    typeof value.elementId === "string" &&
    SAFE_CODE_PATTERN.test(value.elementId) &&
    value.altinnTaskType === "signing"
  );
}

function assertCall(value: unknown): value is AnnualAccountsCall {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "operation",
      "status",
      "requestHash",
      "preparedAt",
      "acceptedAt",
      "failureCode",
    ]) ||
    !["create-draft", "upload-main-form", "upload-accounts-form", "validate", "lock-for-signature"].includes(
      String(value.operation),
    ) ||
    !["prepared", "sent", "accepted", "failed-retryable", "failed-blocked"].includes(String(value.status)) ||
    typeof value.requestHash !== "string" ||
    !SHA256_PATTERN.test(value.requestHash) ||
    !isTimestamp(value.preparedAt) ||
    (value.acceptedAt !== null && !isTimestamp(value.acceptedAt)) ||
    (value.failureCode !== null && (typeof value.failureCode !== "string" || !SAFE_CODE_PATTERN.test(value.failureCode)))
  ) {
    return false;
  }
  if (
    (value.status === "accepted" && (value.acceptedAt === null || value.failureCode !== null)) ||
    (value.status !== "accepted" && value.acceptedAt !== null) ||
    ((value.status === "failed-retryable" || value.status === "failed-blocked") !== (value.failureCode !== null))
  ) {
    return false;
  }
  return true;
}

export function assertAnnualAccountsCheckpoint(value: unknown): asserts value is AnnualAccountsCheckpoint {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "schemaVersion",
      "revision",
      "operationId",
      "environment",
      "organizationNumber",
      "incomeYear",
      "payloadHash",
      "mainFormHash",
      "accountsFormHash",
      "status",
      "instance",
      "dataElements",
      "validation",
      "signingTask",
      "calls",
      "failureCode",
    ]) ||
    value.schemaVersion !== 1 ||
    !Number.isSafeInteger(value.revision) ||
    Number(value.revision) < 1 ||
    typeof value.operationId !== "string" ||
    !UUID_PATTERN.test(value.operationId) ||
    value.environment !== "test" ||
    typeof value.organizationNumber !== "string" ||
    !ORG_NUMBER_PATTERN.test(value.organizationNumber) ||
    !hasValidOrganizationNumberChecksum(value.organizationNumber) ||
    !Number.isInteger(value.incomeYear) ||
    Number(value.incomeYear) < 2000 ||
    Number(value.incomeYear) > 2100 ||
    typeof value.payloadHash !== "string" ||
    !SHA256_PATTERN.test(value.payloadHash) ||
    typeof value.mainFormHash !== "string" ||
    !SHA256_PATTERN.test(value.mainFormHash) ||
    typeof value.accountsFormHash !== "string" ||
    !SHA256_PATTERN.test(value.accountsFormHash) ||
    !["in-progress", "awaiting-person-signature", "failed-retryable", "failed-blocked"].includes(
      String(value.status),
    ) ||
    (value.instance !== null && !assertInstance(value.instance)) ||
    (value.dataElements !== null && !assertDataElements(value.dataElements)) ||
    (value.validation !== null && !assertValidation(value.validation)) ||
    (value.signingTask !== null && !assertSigningTask(value.signingTask)) ||
    !Array.isArray(value.calls) ||
    value.calls.length > 5 ||
    value.calls.some((call) => !assertCall(call)) ||
    (value.failureCode !== null && (typeof value.failureCode !== "string" || !SAFE_CODE_PATTERN.test(value.failureCode)))
  ) {
    checkpointInvalid();
  }

  const operations: AnnualAccountsOperation[] = [
    "create-draft",
    "upload-main-form",
    "upload-accounts-form",
    "validate",
    "lock-for-signature",
  ];
  const calls = value.calls as AnnualAccountsCall[];
  calls.forEach((call, index) => {
    if (call.operation !== operations[index] || (index < calls.length - 1 && call.status !== "accepted")) {
      checkpointInvalid();
    }
  });
  if (
    (calls.length === 0 && (value.instance !== null || value.dataElements !== null)) ||
    (calls.length > 0 && calls[0].status === "accepted" && (!value.instance || !value.dataElements)) ||
    (calls.length > 0 && calls[0].status !== "accepted" && (value.instance !== null || value.dataElements !== null)) ||
    (value.validation !== null && calls.length < 4) ||
    (value.signingTask !== null && value.status !== "awaiting-person-signature") ||
    (value.status === "awaiting-person-signature" &&
      (calls.length !== 5 || calls.some((call) => call.status !== "accepted") || !value.signingTask)) ||
    (value.status === "failed-blocked" && value.failureCode === null) ||
    (value.status === "failed-retryable" && value.failureCode === null) ||
    (value.status === "in-progress" && value.failureCode !== null)
  ) {
    checkpointInvalid();
  }
}

function assertXml(value: unknown, code: string) {
  if (typeof value !== "string" || !value.trimStart().startsWith("<")) {
    throw orchestrationError(code, "Annual-accounts XML document is missing.");
  }
  if (
    XML_UNSAFE_PATTERN.test(value) ||
    XML_CONTROL_PATTERN.test(value) ||
    Buffer.byteLength(value, "utf8") > MAX_XML_BYTES
  ) {
    throw orchestrationError(code, "Annual-accounts XML document is unsafe or too large.");
  }
  return value;
}

function assertDocuments(value: AnnualAccountsDocuments) {
  if (!value || typeof value !== "object" || !UUID_PATTERN.test(value.operationId)) {
    throw orchestrationError("annual_accounts_operation_invalid", "Annual-accounts operation ID must be a UUID.");
  }
  if (
    !ORG_NUMBER_PATTERN.test(value.organizationNumber) ||
    !hasValidOrganizationNumberChecksum(value.organizationNumber)
  ) {
    throw orchestrationError("annual_accounts_org_number_invalid", "Annual-accounts organization number is invalid.");
  }
  if (!Number.isInteger(value.incomeYear) || value.incomeYear < 2000 || value.incomeYear > 2100) {
    throw orchestrationError("annual_accounts_income_year_invalid", "Annual-accounts income year is invalid.");
  }
  const mainFormXml = assertXml(value.mainFormXml, "annual_accounts_main_form_invalid");
  const accountsFormXml = assertXml(value.accountsFormXml, "annual_accounts_accounts_form_invalid");
  const mainFormHash = sha256(mainFormXml);
  const accountsFormHash = sha256(accountsFormXml);
  return {
    ...value,
    mainFormXml,
    accountsFormXml,
    mainFormHash,
    accountsFormHash,
    payloadHash: sha256(
      JSON.stringify({
        environment: "test",
        operationId: value.operationId,
        organizationNumber: value.organizationNumber,
        incomeYear: value.incomeYear,
        mainFormHash,
        accountsFormHash,
      }),
    ),
  };
}

function newCheckpoint(documents: ReturnType<typeof assertDocuments>): AnnualAccountsCheckpoint {
  return {
    schemaVersion: 1,
    revision: 0,
    operationId: documents.operationId,
    environment: "test",
    organizationNumber: documents.organizationNumber,
    incomeYear: documents.incomeYear,
    payloadHash: documents.payloadHash,
    mainFormHash: documents.mainFormHash,
    accountsFormHash: documents.accountsFormHash,
    status: "in-progress",
    instance: null,
    dataElements: null,
    validation: null,
    signingTask: null,
    calls: [],
    failureCode: null,
  };
}

function requestHash(
  operation: AnnualAccountsOperation,
  checkpoint: AnnualAccountsCheckpoint,
  documents: ReturnType<typeof assertDocuments>,
) {
  switch (operation) {
    case "create-draft":
      return sha256(JSON.stringify({ organizationNumber: documents.organizationNumber }));
    case "upload-main-form":
      return documents.mainFormHash;
    case "upload-accounts-form":
      return documents.accountsFormHash;
    case "validate":
      return sha256(JSON.stringify(checkpoint.instance));
    case "lock-for-signature":
      return sha256(JSON.stringify({ instance: checkpoint.instance, action: "confirm" }));
  }
}

function assertCheckpointMatches(
  checkpoint: AnnualAccountsCheckpoint,
  documents: ReturnType<typeof assertDocuments>,
) {
  assertAnnualAccountsCheckpoint(checkpoint);
  if (
    checkpoint.operationId !== documents.operationId ||
    checkpoint.environment !== "test" ||
    checkpoint.organizationNumber !== documents.organizationNumber ||
    checkpoint.incomeYear !== documents.incomeYear
  ) {
    checkpointInvalid();
  }
  if (
    checkpoint.payloadHash !== documents.payloadHash ||
    checkpoint.mainFormHash !== documents.mainFormHash ||
    checkpoint.accountsFormHash !== documents.accountsFormHash
  ) {
    throw orchestrationError(
      "annual_accounts_payload_changed",
      "Annual-accounts documents changed after orchestration began.",
    );
  }
  checkpoint.calls.forEach((call) => {
    if (call.requestHash !== requestHash(call.operation, checkpoint, documents)) checkpointInvalid();
  });
}

function replaceLastCall(checkpoint: AnnualAccountsCheckpoint, call: AnnualAccountsCall) {
  return [...checkpoint.calls.slice(0, -1), call];
}

function nextOperation(checkpoint: AnnualAccountsCheckpoint): AnnualAccountsOperation | null {
  const operations: AnnualAccountsOperation[] = [
    "create-draft",
    "upload-main-form",
    "upload-accounts-form",
    "validate",
    "lock-for-signature",
  ];
  return operations.find((operation) => !checkpoint.calls.some((call) => call.operation === operation && call.status === "accepted")) ?? null;
}

function prepareCall(
  checkpoint: AnnualAccountsCheckpoint,
  documents: ReturnType<typeof assertDocuments>,
): AnnualAccountsCheckpoint {
  const operation = nextOperation(checkpoint);
  if (!operation) return checkpoint;
  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    status: "in-progress",
    calls: [
      ...checkpoint.calls,
      {
        operation,
        status: "prepared",
        requestHash: requestHash(operation, checkpoint, documents),
        preparedAt: new Date().toISOString(),
        acceptedAt: null,
        failureCode: null,
      },
    ],
    failureCode: null,
  };
}

function prepareRetry(checkpoint: AnnualAccountsCheckpoint): AnnualAccountsCheckpoint {
  const call = checkpoint.calls.at(-1);
  if (!call || !["sent", "failed-retryable"].includes(call.status)) checkpointInvalid();
  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    status: "in-progress",
    calls: replaceLastCall(checkpoint, {
      ...call,
      status: "prepared",
      preparedAt: new Date().toISOString(),
      acceptedAt: null,
      failureCode: null,
    }),
    failureCode: null,
  };
}

function updateLastCall(
  checkpoint: AnnualAccountsCheckpoint,
  status: AnnualAccountsCallStatus,
  failureCode: string | null,
): AnnualAccountsCheckpoint {
  const call = checkpoint.calls.at(-1);
  if (!call) checkpointInvalid();
  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    calls: replaceLastCall(checkpoint, {
      ...call,
      status,
      acceptedAt: status === "accepted" ? new Date().toISOString() : null,
      failureCode,
    }),
  };
}

function validationEvidence(issues: AnnualAccountsValidationIssue[]): AnnualAccountsValidationEvidence {
  const codes = (severity: AnnualAccountsValidationIssue["severity"]) =>
    [...new Set(issues.filter((issue) => issue.severity === severity).map((issue) => issue.code))]
      .filter((code) => SAFE_CODE_PATTERN.test(code))
      .sort()
      .slice(0, MAX_CODES);
  const errorCodes = codes("Error");
  return { valid: errorCodes.length === 0, errorCodes, warningCodes: codes("Warning") };
}

function blockedUnknownOutcome(checkpoint: AnnualAccountsCheckpoint): AnnualAccountsCheckpoint {
  const call = checkpoint.calls.at(-1);
  if (!call || call.status !== "sent") checkpointInvalid();
  const failureCode = call.operation === "create-draft"
    ? "annual_accounts_create_outcome_unknown"
    : "annual_accounts_lock_outcome_unknown";
  const updated = updateLastCall(checkpoint, "failed-blocked", failureCode);
  return { ...updated, status: "failed-blocked", failureCode };
}

function result(checkpoint: AnnualAccountsCheckpoint) {
  const complete = checkpoint.status === "awaiting-person-signature";
  const blocked = checkpoint.status === "failed-blocked";
  return {
    checkpoint,
    nextOperation: complete || blocked ? null : nextOperation(checkpoint),
    complete,
    blocked,
  };
}

async function save(
  journal: AnnualAccountsJournal,
  checkpoint: AnnualAccountsCheckpoint,
  expectedRevision: number | null,
) {
  await journal.save(checkpoint, expectedRevision);
  return checkpoint;
}

function assertDraftData(draft: Awaited<ReturnType<AnnualAccountsAltinnTestClient["createDraft"]>>) {
  if (draft.currentTask.altinnTaskType.toLowerCase() !== "data") {
    throw orchestrationError(
      "annual_accounts_draft_task_invalid",
      "Annual-accounts draft did not enter the expected data task.",
    );
  }
  const mainForms = draft.dataElements.filter(
    (element) => element.dataType === "Hovedskjema" && element.contentType === "application/xml",
  );
  const accountsForms = draft.dataElements.filter(
    (element) => element.dataType === "Underskjema" && element.contentType === "application/xml",
  );
  if (mainForms.length !== 1 || accountsForms.length !== 1) {
    throw orchestrationError(
      "annual_accounts_data_elements_invalid",
      "Annual-accounts draft must contain exactly one main form and one accounts form.",
    );
  }
  return { mainFormId: mainForms[0].id, accountsFormId: accountsForms[0].id };
}

export async function inspectAnnualAccountsProgress(input: {
  documents: AnnualAccountsDocuments;
  journal: AnnualAccountsJournal;
}) {
  const documents = assertDocuments(input.documents);
  const checkpoint = await input.journal.load(documents.operationId);
  if (!checkpoint) {
    return { checkpoint: null, nextOperation: "create-draft" as const, complete: false, blocked: false };
  }
  assertCheckpointMatches(checkpoint, documents);
  return result(checkpoint);
}

export async function runNextAnnualAccountsStep(input: {
  documents: AnnualAccountsDocuments;
  client: AnnualAccountsAltinnTestClient;
  journal: AnnualAccountsJournal;
}) {
  const documents = assertDocuments(input.documents);
  if (input.client.environment !== "test") {
    throw orchestrationError("annual_accounts_environment_invalid", "Annual-accounts orchestration is test-only.");
  }
  let checkpoint = await input.journal.load(documents.operationId);
  if (checkpoint) assertCheckpointMatches(checkpoint, documents);
  else checkpoint = newCheckpoint(documents);

  if (checkpoint.status === "awaiting-person-signature" || checkpoint.status === "failed-blocked") {
    return result(checkpoint);
  }

  const existingCall = checkpoint.calls.at(-1);
  if (existingCall?.status === "sent") {
    if (existingCall.operation === "create-draft" || existingCall.operation === "lock-for-signature") {
      const blocked = blockedUnknownOutcome(checkpoint);
      await save(input.journal, blocked, checkpoint.revision);
      return result(blocked);
    }
    const retry = prepareRetry(checkpoint);
    checkpoint = await save(input.journal, retry, checkpoint.revision);
  } else if (existingCall?.status === "failed-retryable") {
    const retry = prepareRetry(checkpoint);
    checkpoint = await save(input.journal, retry, checkpoint.revision);
  } else if (existingCall?.status !== "prepared") {
    const prepared = prepareCall(checkpoint, documents);
    checkpoint = await save(
      input.journal,
      prepared,
      checkpoint.revision === 0 ? null : checkpoint.revision,
    );
  }

  const call = checkpoint.calls.at(-1);
  if (!call || call.status !== "prepared") checkpointInvalid();

  if (call.operation === "lock-for-signature") {
    try {
      const validation = await input.client.validateDraft({ instance: checkpoint.instance as AnnualAccountsInstanceRef });
      const evidence = validationEvidence(validation.issues);
      const refreshed: AnnualAccountsCheckpoint = {
        ...checkpoint,
        revision: checkpoint.revision + 1,
        validation: evidence,
      };
      checkpoint = await save(input.journal, refreshed, checkpoint.revision);
      if (!validation.valid || !evidence.valid) {
        const failureCode = "annual_accounts_validation_failed";
        const failedCall = updateLastCall(checkpoint, "failed-blocked", failureCode);
        const failed: AnnualAccountsCheckpoint = { ...failedCall, status: "failed-blocked", failureCode };
        await save(input.journal, failed, checkpoint.revision);
        return result(failed);
      }
    } catch (error) {
      if (!(error instanceof AnnualAccountsAltinnError)) throw error;
      const retryable = error.retryable;
      const failureCode = SAFE_CODE_PATTERN.test(error.code)
        ? error.code
        : "annual_accounts_validation_preflight_failed";
      const failedCall = updateLastCall(
        checkpoint,
        retryable ? "failed-retryable" : "failed-blocked",
        failureCode,
      );
      const failed: AnnualAccountsCheckpoint = {
        ...failedCall,
        status: retryable ? "failed-retryable" : "failed-blocked",
        failureCode,
      };
      await save(input.journal, failed, checkpoint.revision);
      return result(failed);
    }
  }

  const sent = updateLastCall(checkpoint, "sent", null);
  checkpoint = await save(input.journal, sent, checkpoint.revision);

  try {
    let next = checkpoint;
    switch (call.operation) {
      case "create-draft": {
        const draft = await input.client.createDraft({ organizationNumber: documents.organizationNumber });
        const dataElements = assertDraftData(draft);
        next = {
          ...next,
          instance: draft.instance,
          dataElements,
        };
        break;
      }
      case "upload-main-form":
        await input.client.replaceXmlDataElement({
          instance: checkpoint.instance as AnnualAccountsInstanceRef,
          dataElementId: checkpoint.dataElements?.mainFormId as string,
          xml: documents.mainFormXml,
        });
        break;
      case "upload-accounts-form":
        await input.client.replaceXmlDataElement({
          instance: checkpoint.instance as AnnualAccountsInstanceRef,
          dataElementId: checkpoint.dataElements?.accountsFormId as string,
          xml: documents.accountsFormXml,
        });
        break;
      case "validate": {
        const validation = await input.client.validateDraft({ instance: checkpoint.instance as AnnualAccountsInstanceRef });
        const evidence = validationEvidence(validation.issues);
        next = { ...next, validation: evidence };
        if (!validation.valid || !evidence.valid) {
          const failureCode = "annual_accounts_validation_failed";
          const accepted = updateLastCall(next, "accepted", null);
          const failed: AnnualAccountsCheckpoint = {
            ...accepted,
            status: "failed-blocked",
            failureCode,
          };
          await save(input.journal, failed, checkpoint.revision);
          return result(failed);
        }
        break;
      }
      case "lock-for-signature": {
        const locked = await input.client.lockForPersonalSignature({
          instance: checkpoint.instance as AnnualAccountsInstanceRef,
        });
        next = {
          ...next,
          status: "awaiting-person-signature",
          signingTask: {
            elementId: locked.currentTask.elementId,
            altinnTaskType: "signing",
          },
        };
        break;
      }
    }
    const accepted = updateLastCall(next, "accepted", null);
    await save(input.journal, accepted, checkpoint.revision);
    return result(accepted);
  } catch (error) {
    if (!(error instanceof AnnualAccountsAltinnError || error instanceof AnnualAccountsOrchestrationError)) {
      throw error;
    }
    const nonRepeatable = call.operation === "create-draft" || call.operation === "lock-for-signature";
    const retryable = error instanceof AnnualAccountsAltinnError && error.retryable && !nonRepeatable;
    const failureCode = nonRepeatable
      ? call.operation === "create-draft"
        ? "annual_accounts_create_outcome_unknown"
        : "annual_accounts_lock_outcome_unknown"
      : error instanceof AnnualAccountsAltinnError && SAFE_CODE_PATTERN.test(error.code)
        ? error.code
        : "annual_accounts_operation_failed";
    const callStatus: AnnualAccountsCallStatus = retryable ? "failed-retryable" : "failed-blocked";
    const failedCall = updateLastCall(checkpoint, callStatus, failureCode);
    const failed: AnnualAccountsCheckpoint = {
      ...failedCall,
      status: retryable ? "failed-retryable" : "failed-blocked",
      failureCode,
    };
    await save(input.journal, failed, checkpoint.revision);
    return result(failed);
  }
}
