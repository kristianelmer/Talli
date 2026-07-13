import { createHash } from "node:crypto";

import {
  AnnualAccountsCompletionError,
  assertAnnualAccountsCompletionEvidence,
  type AnnualAccountsCompletionEvidence,
} from "./annual-accounts-completion.ts";
import type { DialogportenClient, DialogportenDialog } from "./dialogporten-client.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const PARTY_ID_PATTERN = /^\d{1,20}$/u;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const MAX_TRANSMISSIONS = 10_000;
const MAX_ATTACHMENTS = 10_000;
const MAX_URLS = 20;

export const ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID = "app_brg_aarsregnskap";
export const ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_URN =
  `urn:altinn:resource:${ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID}`;

export type AnnualAccountsDialogEvidence = {
  schemaVersion: 1;
  environment: "test";
  operationId: string;
  organizationNumber: string;
  incomeYear: number;
  instance: { ownerPartyId: string; instanceGuid: string };
  completionEvidenceSha256: string;
  dialogId: string;
  dialogRevision: string;
  dialogStatus: "Completed";
  dialogCreatedAt: string;
  dialogUpdatedAt: string;
  serviceResourceId: typeof ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID;
  serviceOwnerCode: "brg";
  transmissionCount: number;
  authorizedTransmissionCount: number;
  authorizedAttachmentCount: number;
  authorizedApiAttachmentCount: number;
};

export class AnnualAccountsDialogEvidenceError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AnnualAccountsDialogEvidenceError";
    this.code = code;
  }
}

function dialogEvidenceError(code: string, message: string) {
  return new AnnualAccountsDialogEvidenceError(code, message);
}

function dialogEvidenceInvalid(): never {
  throw dialogEvidenceError(
    "annual_accounts_dialog_evidence_invalid",
    "Annual-accounts Dialogporten evidence does not match the signed Altinn instance.",
  );
}

function canonicalCompletionEvidence(value: AnnualAccountsCompletionEvidence) {
  return {
    schemaVersion: 1,
    environment: "test",
    operationId: value.operationId,
    organizationNumber: value.organizationNumber,
    incomeYear: value.incomeYear,
    instance: {
      ownerPartyId: value.instance.ownerPartyId,
      instanceGuid: value.instance.instanceGuid,
    },
    completedAt: value.completedAt,
    mainFormId: value.mainFormId,
    accountsFormId: value.accountsFormId,
    signatureDataElementId: value.signatureDataElementId,
    mainFormHash: value.mainFormHash,
    accountsFormHash: value.accountsFormHash,
  };
}

function sha256(value: unknown) {
  return createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex");
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64 && Number.isFinite(Date.parse(value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return actual.length === sortedExpected.length && actual.every((key, index) => key === sortedExpected[index]);
}

function hasValidOrganizationNumberChecksum(value: string) {
  const weights = [3, 2, 7, 6, 5, 4, 3, 2];
  const sum = weights.reduce((total, weight, index) => total + weight * Number(value[index]), 0);
  const remainder = 11 - (sum % 11);
  const checksum = remainder === 11 ? 0 : remainder;
  return checksum !== 10 && checksum === Number(value[8]);
}

export function assertAnnualAccountsDialogEvidence(
  value: unknown,
): asserts value is AnnualAccountsDialogEvidence {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "schemaVersion",
      "environment",
      "operationId",
      "organizationNumber",
      "incomeYear",
      "instance",
      "completionEvidenceSha256",
      "dialogId",
      "dialogRevision",
      "dialogStatus",
      "dialogCreatedAt",
      "dialogUpdatedAt",
      "serviceResourceId",
      "serviceOwnerCode",
      "transmissionCount",
      "authorizedTransmissionCount",
      "authorizedAttachmentCount",
      "authorizedApiAttachmentCount",
    ]) ||
    value.schemaVersion !== 1 ||
    value.environment !== "test" ||
    typeof value.operationId !== "string" ||
    !UUID_PATTERN.test(value.operationId) ||
    typeof value.organizationNumber !== "string" ||
    !ORG_NUMBER_PATTERN.test(value.organizationNumber) ||
    !hasValidOrganizationNumberChecksum(value.organizationNumber) ||
    !Number.isInteger(value.incomeYear) ||
    Number(value.incomeYear) < 2000 ||
    Number(value.incomeYear) > 2100 ||
    !isRecord(value.instance) ||
    !exactKeys(value.instance, ["ownerPartyId", "instanceGuid"]) ||
    typeof value.instance.ownerPartyId !== "string" ||
    !PARTY_ID_PATTERN.test(value.instance.ownerPartyId) ||
    typeof value.instance.instanceGuid !== "string" ||
    !UUID_PATTERN.test(value.instance.instanceGuid) ||
    typeof value.completionEvidenceSha256 !== "string" ||
    !SHA256_PATTERN.test(value.completionEvidenceSha256) ||
    typeof value.dialogId !== "string" ||
    !UUID_PATTERN.test(value.dialogId) ||
    typeof value.dialogRevision !== "string" ||
    !UUID_PATTERN.test(value.dialogRevision) ||
    value.dialogStatus !== "Completed" ||
    !isTimestamp(value.dialogCreatedAt) ||
    !isTimestamp(value.dialogUpdatedAt) ||
    Date.parse(value.dialogUpdatedAt) < Date.parse(value.dialogCreatedAt) ||
    value.serviceResourceId !== ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID ||
    value.serviceOwnerCode !== "brg" ||
    !Number.isSafeInteger(value.transmissionCount) ||
    Number(value.transmissionCount) < 0 ||
    Number(value.transmissionCount) > MAX_TRANSMISSIONS ||
    !Number.isSafeInteger(value.authorizedTransmissionCount) ||
    Number(value.authorizedTransmissionCount) < 0 ||
    Number(value.authorizedTransmissionCount) > Number(value.transmissionCount) ||
    !Number.isSafeInteger(value.authorizedAttachmentCount) ||
    Number(value.authorizedAttachmentCount) < 0 ||
    Number(value.authorizedAttachmentCount) > MAX_TRANSMISSIONS * MAX_ATTACHMENTS ||
    !Number.isSafeInteger(value.authorizedApiAttachmentCount) ||
    Number(value.authorizedApiAttachmentCount) < 0 ||
    Number(value.authorizedApiAttachmentCount) > Number(value.authorizedAttachmentCount) * MAX_URLS
  ) {
    dialogEvidenceInvalid();
  }
}

function summarizeTransmissions(value: unknown) {
  if (!Array.isArray(value) || value.length > MAX_TRANSMISSIONS) dialogEvidenceInvalid();
  const transmissionIds = new Set<string>();
  const attachmentIds = new Set<string>();
  const urlIds = new Set<string>();
  let authorizedTransmissionCount = 0;
  let authorizedAttachmentCount = 0;
  let authorizedApiAttachmentCount = 0;

  for (const transmissionValue of value) {
    if (
      !isRecord(transmissionValue) ||
      typeof transmissionValue.id !== "string" ||
      !UUID_PATTERN.test(transmissionValue.id) ||
      transmissionIds.has(transmissionValue.id) ||
      typeof transmissionValue.isAuthorized !== "boolean" ||
      !Array.isArray(transmissionValue.attachments) ||
      transmissionValue.attachments.length > MAX_ATTACHMENTS
    ) {
      dialogEvidenceInvalid();
    }
    transmissionIds.add(transmissionValue.id);
    if (!transmissionValue.isAuthorized) continue;
    authorizedTransmissionCount += 1;
    authorizedAttachmentCount += transmissionValue.attachments.length;
    for (const attachmentValue of transmissionValue.attachments) {
      if (
        !isRecord(attachmentValue) ||
        typeof attachmentValue.id !== "string" ||
        !UUID_PATTERN.test(attachmentValue.id) ||
        attachmentIds.has(attachmentValue.id) ||
        !Array.isArray(attachmentValue.urls) ||
        attachmentValue.urls.length > MAX_URLS
      ) {
        dialogEvidenceInvalid();
      }
      attachmentIds.add(attachmentValue.id);
      for (const urlValue of attachmentValue.urls) {
        if (
          !isRecord(urlValue) ||
          typeof urlValue.id !== "string" ||
          !UUID_PATTERN.test(urlValue.id) ||
          urlIds.has(urlValue.id)
        ) {
          dialogEvidenceInvalid();
        }
        urlIds.add(urlValue.id);
        if (urlValue.consumerType === "Api" && urlValue.url !== "urn:dialogporten:unauthorized") {
          authorizedApiAttachmentCount += 1;
        }
      }
    }
  }
  return {
    transmissionCount: value.length,
    authorizedTransmissionCount,
    authorizedAttachmentCount,
    authorizedApiAttachmentCount,
  };
}

export async function verifyAnnualAccountsDialogEvidence(input: {
  completionEvidence: AnnualAccountsCompletionEvidence;
  client: Pick<DialogportenClient, "environment" | "lookupDialogByInstance" | "getDialog">;
}): Promise<AnnualAccountsDialogEvidence> {
  try {
    assertAnnualAccountsCompletionEvidence(input.completionEvidence);
  } catch (error) {
    if (error instanceof AnnualAccountsCompletionError) {
      throw dialogEvidenceError(
        "annual_accounts_dialog_completion_invalid",
        "Annual-accounts dialog verification requires valid immutable signed-instance evidence.",
      );
    }
    throw error;
  }
  if (input.client.environment !== "test") dialogEvidenceInvalid();
  const completion = canonicalCompletionEvidence(input.completionEvidence);
  const instanceRef = `urn:altinn:instance-id:${completion.instance.ownerPartyId}/${completion.instance.instanceGuid}`;
  const party = `urn:altinn:organization:identifier-no:${completion.organizationNumber}`;
  const lookup = await input.client.lookupDialogByInstance({
    instance: completion.instance,
    expectedPartyOrgNumber: completion.organizationNumber,
    expectedServiceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID,
  });
  if (
    !lookup ||
    !UUID_PATTERN.test(lookup.dialogId) ||
    lookup.instanceRef !== instanceRef ||
    lookup.party !== party ||
    lookup.serviceResourceId !== ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID ||
    lookup.serviceOwnerCode !== "brg"
  ) {
    dialogEvidenceInvalid();
  }

  const dialog = await input.client.getDialog({
    dialogId: lookup.dialogId,
    expectedPartyOrgNumber: completion.organizationNumber,
    expectedServiceResource: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_URN,
  });
  if (
    !dialog ||
    dialog.id !== lookup.dialogId ||
    !UUID_PATTERN.test(dialog.revision) ||
    dialog.org !== "brg" ||
    dialog.party !== party ||
    dialog.serviceResource !== ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_URN ||
    dialog.status !== "Completed" ||
    !isTimestamp(dialog.createdAt) ||
    !isTimestamp(dialog.updatedAt) ||
    Date.parse(dialog.updatedAt) < Date.parse(completion.completedAt)
  ) {
    dialogEvidenceInvalid();
  }
  const counts = summarizeTransmissions((dialog as DialogportenDialog).transmissions);

  return {
    schemaVersion: 1,
    environment: "test",
    operationId: completion.operationId,
    organizationNumber: completion.organizationNumber,
    incomeYear: completion.incomeYear,
    instance: completion.instance,
    completionEvidenceSha256: sha256(completion),
    dialogId: dialog.id,
    dialogRevision: dialog.revision,
    dialogStatus: "Completed",
    dialogCreatedAt: dialog.createdAt,
    dialogUpdatedAt: dialog.updatedAt,
    serviceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID,
    serviceOwnerCode: "brg",
    ...counts,
  };
}
