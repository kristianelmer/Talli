import { createHash } from "node:crypto";

import type { FilingPreviewRow } from "./supabase/server";
import {
  RF1086_AUTHORITY_BASE_URLS,
  Rf1086AuthorityError,
  type Rf1086AuthorityClient,
  type Rf1086AuthorityEnvironment,
  type Rf1086Leveransebekreftelse,
} from "./rf1086-authority-client.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export type Rf1086AuthorityCallStatus = "prepared" | "sent" | "accepted" | "failed_retryable" | "failed_blocked";
export type Rf1086AuthorityCheckpointStatus = "submitting" | "confirmed" | "failed_retryable" | "failed_blocked";

export type Rf1086AuthorityCall = {
  operation: "hovedskjema" | `underskjema:${string}` | "bekreft";
  method: "POST";
  url: string;
  bodyHash: string;
  idempotencyKey: string | null;
  documentKey: string | null;
  status: Rf1086AuthorityCallStatus;
  preparedAt: string;
  acceptedAt: string | null;
  failureCode: string | null;
  failureMessage: string | null;
};

export type Rf1086AuthorityCheckpoint = {
  schemaVersion: 1;
  revision: number;
  previewId: string;
  companyId: string;
  incomeYear: number;
  environment: Rf1086AuthorityEnvironment;
  payloadHash: string;
  status: Rf1086AuthorityCheckpointStatus;
  hovedskjemaId: string | null;
  confirmation: Rf1086Leveransebekreftelse | null;
  calls: Rf1086AuthorityCall[];
  failureCode: string | null;
  failureMessage: string | null;
};

export type Rf1086AuthorityJournal = {
  load(previewId: string): Promise<Rf1086AuthorityCheckpoint | null>;
  save(checkpoint: Rf1086AuthorityCheckpoint, expectedRevision: number | null): Promise<void>;
};

export class Rf1086AuthorityOrchestrationError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "Rf1086AuthorityOrchestrationError";
    this.code = code;
  }
}

function orchestrationError(code: string, message: string) {
  return new Rf1086AuthorityOrchestrationError(code, message);
}

function sha256(value: string) {
  return createHash("sha256").update(value).digest("hex");
}

function compareKeys(left: string, right: string) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function canonicalPayloadHash(preview: FilingPreviewRow) {
  return sha256(
    JSON.stringify({
      filing: preview.filing,
      companyId: preview.company_id,
      incomeYear: preview.income_year,
      hovedskjemaXml: preview.hovedskjema_xml,
      underskjemaXml: Object.fromEntries(Object.entries(preview.underskjema_xml).sort(([left], [right]) => compareKeys(left, right))),
    }),
  );
}

function deterministicUuid(value: string) {
  const bytes = createHash("sha256").update(value).digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function assertPreview(preview: FilingPreviewRow) {
  if (preview.filing !== "aksjonærregisteroppgaven" || preview.status !== "ready") {
    throw orchestrationError("rf1086_preview_not_ready", "RF-1086 preview must be ready for authority orchestration.");
  }
  if (!preview.hovedskjema_xml || !preview.hovedskjema_xml.trim()) {
    throw orchestrationError("rf1086_hovedskjema_missing", "RF-1086 preview is missing hovedskjema XML.");
  }
  const underskjema = Object.entries(preview.underskjema_xml);
  if (!underskjema.length || underskjema.some(([key, xml]) => !key.trim() || !xml.trim())) {
    throw orchestrationError("rf1086_underskjema_missing", "RF-1086 preview requires at least one named underskjema.");
  }
}

function checkpointInvalid(): never {
  throw orchestrationError("rf1086_checkpoint_invalid", "Stored RF-1086 authority checkpoint is invalid.");
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

function isFailureCode(value: unknown): value is string {
  return typeof value === "string" && /^[a-z0-9_]{1,100}$/u.test(value);
}

function isFailureMessage(value: unknown): value is string {
  return typeof value === "string" && value.length >= 1 && value.length <= 500 && !/[\r\n]/u.test(value);
}

export function assertRf1086AuthorityCheckpoint(
  value: Rf1086AuthorityCheckpoint,
  preview: FilingPreviewRow,
) {
  const checkpointStatuses: readonly Rf1086AuthorityCheckpointStatus[] = [
    "submitting",
    "confirmed",
    "failed_retryable",
    "failed_blocked",
  ];
  if (
    !value ||
    typeof value !== "object" ||
    !exactKeys(value as unknown as Record<string, unknown>, [
      "schemaVersion",
      "revision",
      "previewId",
      "companyId",
      "incomeYear",
      "environment",
      "payloadHash",
      "status",
      "hovedskjemaId",
      "confirmation",
      "calls",
      "failureCode",
      "failureMessage",
    ]) ||
    value.schemaVersion !== 1 ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 1 ||
    value.previewId !== preview.id ||
    value.companyId !== preview.company_id ||
    value.incomeYear !== preview.income_year ||
    (value.environment !== "test" && value.environment !== "production") ||
    !/^[0-9a-f]{64}$/u.test(value.payloadHash) ||
    !checkpointStatuses.includes(value.status) ||
    !Array.isArray(value.calls) ||
    value.calls.length > 100_002 ||
    (value.failureCode !== null && !isFailureCode(value.failureCode)) ||
    (value.failureMessage !== null && !isFailureMessage(value.failureMessage))
  ) {
    checkpointInvalid();
  }
  if (value.hovedskjemaId !== null && !UUID_PATTERN.test(value.hovedskjemaId)) checkpointInvalid();
  if (
    value.confirmation !== null &&
    (!exactKeys(value.confirmation as unknown as Record<string, unknown>, [
      "oppgavegiversLeveranseReferanse",
      "dialogId",
      "forsendelseId",
    ]) ||
      !value.confirmation.oppgavegiversLeveranseReferanse ||
      value.confirmation.oppgavegiversLeveranseReferanse.length > 100 ||
      !UUID_PATTERN.test(value.confirmation.dialogId) ||
      !UUID_PATTERN.test(value.confirmation.forsendelseId))
  ) {
    checkpointInvalid();
  }

  const documentKeys = Object.keys(preview.underskjema_xml).sort(compareKeys);
  const expectedOperations: Rf1086AuthorityCall["operation"][] = [
    "hovedskjema",
    ...documentKeys.map((key) => `underskjema:${key}` as const),
    "bekreft",
  ];
  if (value.calls.length > expectedOperations.length) checkpointInvalid();
  const baseUrl = RF1086_AUTHORITY_BASE_URLS[value.environment];
  const allowedCallStatuses: readonly Rf1086AuthorityCallStatus[] = [
    "prepared",
    "sent",
    "accepted",
    "failed_retryable",
    "failed_blocked",
  ];

  value.calls.forEach((call, index) => {
    if (
      !call ||
      typeof call !== "object" ||
      !exactKeys(call as unknown as Record<string, unknown>, [
        "operation",
        "method",
        "url",
        "bodyHash",
        "idempotencyKey",
        "documentKey",
        "status",
        "preparedAt",
        "acceptedAt",
        "failureCode",
        "failureMessage",
      ]) ||
      call.operation !== expectedOperations[index] ||
      call.method !== "POST" ||
      !/^[0-9a-f]{64}$/u.test(call.bodyHash) ||
      !allowedCallStatuses.includes(call.status) ||
      typeof call.preparedAt !== "string" ||
      !Number.isFinite(Date.parse(call.preparedAt)) ||
      (call.acceptedAt !== null && !Number.isFinite(Date.parse(call.acceptedAt))) ||
      (call.acceptedAt !== null && Date.parse(call.acceptedAt) < Date.parse(call.preparedAt)) ||
      (call.failureCode !== null && !isFailureCode(call.failureCode)) ||
      (call.failureMessage !== null && !isFailureMessage(call.failureMessage)) ||
      (call.status === "accepted" && (call.acceptedAt === null || call.failureCode !== null || call.failureMessage !== null)) ||
      (call.status !== "accepted" && call.acceptedAt !== null) ||
      (["failed_retryable", "failed_blocked"].includes(call.status) &&
        (call.failureCode === null || call.failureMessage === null)) ||
      (!["failed_retryable", "failed_blocked"].includes(call.status) &&
        (call.failureCode !== null || call.failureMessage !== null)) ||
      (index < value.calls.length - 1 && call.status !== "accepted")
    ) {
      checkpointInvalid();
    }

    if (call.operation === "hovedskjema") {
      if (
        call.url !== `${baseUrl}/${preview.income_year}/1086H` ||
        call.bodyHash !== sha256(preview.hovedskjema_xml as string) ||
        !call.idempotencyKey ||
        !UUID_PATTERN.test(call.idempotencyKey) ||
        call.documentKey !== null
      ) {
        checkpointInvalid();
      }
      return;
    }

    if (call.operation.startsWith("underskjema:")) {
      const documentKey = call.operation.slice("underskjema:".length);
      const xml = preview.underskjema_xml[documentKey];
      if (
        !value.hovedskjemaId ||
        !xml ||
        call.documentKey !== documentKey ||
        call.url !== `${baseUrl}/${preview.income_year}/${value.hovedskjemaId}/1086U` ||
        call.bodyHash !== sha256(xml) ||
        !call.idempotencyKey ||
        !UUID_PATTERN.test(call.idempotencyKey)
      ) {
        checkpointInvalid();
      }
      return;
    }

    const count = documentKeys.length;
    if (
      !value.hovedskjemaId ||
      call.url !== `${baseUrl}/${preview.income_year}/${value.hovedskjemaId}/bekreft?antall_underskjema=${count}` ||
      call.bodyHash !== sha256(JSON.stringify({ antall_underskjema: count })) ||
      call.idempotencyKey !== null ||
      call.documentKey !== null
    ) {
      checkpointInvalid();
    }
  });

  if (
    (value.calls[0]?.status === "accepted" && value.hovedskjemaId === null) ||
    (value.calls[0]?.status !== "accepted" && value.hovedskjemaId !== null) ||
    (value.status === "confirmed" &&
      (value.calls.length !== expectedOperations.length ||
        value.calls.some((call) => call.status !== "accepted") ||
        !value.confirmation ||
        value.failureCode !== null ||
        value.failureMessage !== null)) ||
    (value.confirmation !== null && value.status !== "confirmed") ||
    (["failed_retryable", "failed_blocked"].includes(value.status) &&
      (value.failureCode === null ||
        value.failureMessage === null ||
        value.calls.at(-1)?.status !== value.status ||
        value.calls.at(-1)?.failureCode !== value.failureCode ||
        value.calls.at(-1)?.failureMessage !== value.failureMessage)) ||
    (!["failed_retryable", "failed_blocked"].includes(value.status) &&
      (value.failureCode !== null || value.failureMessage !== null))
  ) {
    checkpointInvalid();
  }
}

function newCheckpoint(preview: FilingPreviewRow, environment: Rf1086AuthorityEnvironment): Rf1086AuthorityCheckpoint {
  return {
    schemaVersion: 1,
    revision: 0,
    previewId: preview.id,
    companyId: preview.company_id,
    incomeYear: preview.income_year,
    environment,
    payloadHash: canonicalPayloadHash(preview),
    status: "submitting",
    hovedskjemaId: null,
    confirmation: null,
    calls: [],
    failureCode: null,
    failureMessage: null,
  };
}

function replaceLastCall(checkpoint: Rf1086AuthorityCheckpoint, call: Rf1086AuthorityCall) {
  return [...checkpoint.calls.slice(0, -1), call];
}

function prepareRetry(checkpoint: Rf1086AuthorityCheckpoint): Rf1086AuthorityCheckpoint {
  const last = checkpoint.calls.at(-1);
  if (!last || (last.status !== "failed_retryable" && last.status !== "sent")) {
    throw orchestrationError("rf1086_checkpoint_invalid", "RF-1086 retry checkpoint has no retryable call.");
  }
  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    status: "submitting",
    calls: replaceLastCall(checkpoint, {
      ...last,
      status: "prepared",
      preparedAt: new Date().toISOString(),
      failureCode: null,
      failureMessage: null,
    }),
    failureCode: null,
    failureMessage: null,
  };
}

function markSent(checkpoint: Rf1086AuthorityCheckpoint): Rf1086AuthorityCheckpoint {
  const last = checkpoint.calls.at(-1);
  if (!last || last.status !== "prepared") {
    throw orchestrationError("rf1086_checkpoint_invalid", "RF-1086 checkpoint has no prepared call to mark sent.");
  }
  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    calls: replaceLastCall(checkpoint, { ...last, status: "sent" }),
  };
}

function blockUnknownConfirmation(checkpoint: Rf1086AuthorityCheckpoint): Rf1086AuthorityCheckpoint {
  const last = checkpoint.calls.at(-1);
  if (!last || last.status !== "sent" || last.operation !== "bekreft") {
    throw orchestrationError("rf1086_checkpoint_invalid", "RF-1086 checkpoint has no uncertain confirmation.");
  }
  const code = "rf1086_confirm_outcome_unknown";
  const message = "RF-1086 confirmation outcome is unknown and requires operator reconciliation before another call.";
  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    status: "failed_blocked",
    calls: replaceLastCall(checkpoint, {
      ...last,
      status: "failed_blocked",
      failureCode: code,
      failureMessage: message,
    }),
    failureCode: code,
    failureMessage: message,
  };
}

function nextPreparedCheckpoint(
  checkpoint: Rf1086AuthorityCheckpoint,
  preview: FilingPreviewRow,
): Rf1086AuthorityCheckpoint {
  const baseUrl = RF1086_AUTHORITY_BASE_URLS[checkpoint.environment];
  const accepted = new Set(checkpoint.calls.filter((call) => call.status === "accepted").map((call) => call.operation));
  const timestamp = new Date().toISOString();

  let operation: Rf1086AuthorityCall["operation"];
  let url: string;
  let bodyHash: string;
  let documentKey: string | null = null;
  let idempotencyKey: string | null;

  if (!accepted.has("hovedskjema")) {
    operation = "hovedskjema";
    url = `${baseUrl}/${preview.income_year}/1086H`;
    bodyHash = sha256(preview.hovedskjema_xml as string);
    idempotencyKey = deterministicUuid(`${checkpoint.payloadHash}:${operation}:${url}:${bodyHash}`);
  } else {
    if (!checkpoint.hovedskjemaId) {
      throw orchestrationError("rf1086_checkpoint_invalid", "Accepted hovedskjema is missing its authority ID.");
    }
    const nextDocument = Object.entries(preview.underskjema_xml)
      .sort(([left], [right]) => compareKeys(left, right))
      .find(([key]) => !accepted.has(`underskjema:${key}`));
    if (nextDocument) {
      documentKey = nextDocument[0];
      operation = `underskjema:${documentKey}`;
      url = `${baseUrl}/${preview.income_year}/${checkpoint.hovedskjemaId}/1086U`;
      bodyHash = sha256(nextDocument[1]);
      idempotencyKey = deterministicUuid(`${checkpoint.payloadHash}:${operation}:${url}:${bodyHash}`);
    } else {
      operation = "bekreft";
      const count = Object.keys(preview.underskjema_xml).length;
      url = `${baseUrl}/${preview.income_year}/${checkpoint.hovedskjemaId}/bekreft?antall_underskjema=${count}`;
      bodyHash = sha256(JSON.stringify({ antall_underskjema: count }));
      idempotencyKey = null;
    }
  }

  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    status: "submitting",
    calls: [
      ...checkpoint.calls,
      {
        operation,
        method: "POST",
        url,
        bodyHash,
        idempotencyKey,
        documentKey,
        status: "prepared",
        preparedAt: timestamp,
        acceptedAt: null,
        failureCode: null,
        failureMessage: null,
      },
    ],
    failureCode: null,
    failureMessage: null,
  };
}

function nextOperationForCheckpoint(
  checkpoint: Rf1086AuthorityCheckpoint,
  preview: FilingPreviewRow,
): Rf1086AuthorityCall["operation"] {
  const last = checkpoint.calls.at(-1);
  if (last && ["prepared", "sent", "failed_retryable"].includes(last.status)) return last.operation;
  const accepted = new Set(checkpoint.calls.filter((call) => call.status === "accepted").map((call) => call.operation));
  if (!accepted.has("hovedskjema")) return "hovedskjema";
  const nextDocumentKey = Object.keys(preview.underskjema_xml)
    .sort(compareKeys)
    .find((key) => !accepted.has(`underskjema:${key}`));
  return nextDocumentKey ? `underskjema:${nextDocumentKey}` : "bekreft";
}

export async function inspectRf1086AuthorityProgress(input: {
  preview: FilingPreviewRow;
  environment: Rf1086AuthorityEnvironment;
  journal: Rf1086AuthorityJournal;
}): Promise<{
  checkpoint: Rf1086AuthorityCheckpoint | null;
  nextOperation: Rf1086AuthorityCall["operation"] | "reconcile" | null;
  complete: boolean;
  blocked: boolean;
}> {
  assertPreview(input.preview);
  const checkpoint = await input.journal.load(input.preview.id);
  if (!checkpoint) {
    return { checkpoint: null, nextOperation: "hovedskjema", complete: false, blocked: false };
  }
  if (checkpoint.environment !== input.environment) {
    throw orchestrationError("rf1086_environment_changed", "RF-1086 authority environment cannot change during a submission.");
  }
  if (checkpoint.payloadHash !== canonicalPayloadHash(input.preview)) {
    throw orchestrationError("rf1086_preview_changed", "RF-1086 preview cannot change during a submission.");
  }
  assertRf1086AuthorityCheckpoint(checkpoint, input.preview);
  if (checkpoint.status === "confirmed") {
    return { checkpoint, nextOperation: null, complete: true, blocked: false };
  }
  if (checkpoint.status === "failed_blocked") {
    return { checkpoint, nextOperation: null, complete: false, blocked: true };
  }
  const last = checkpoint.calls.at(-1);
  if (last?.operation === "bekreft" && last.status === "sent") {
    return { checkpoint, nextOperation: "reconcile", complete: false, blocked: true };
  }
  return {
    checkpoint,
    nextOperation: nextOperationForCheckpoint(checkpoint, input.preview),
    complete: false,
    blocked: false,
  };
}

async function executePreparedCall(
  checkpoint: Rf1086AuthorityCheckpoint,
  preview: FilingPreviewRow,
  client: Rf1086AuthorityClient,
): Promise<Rf1086AuthorityCheckpoint> {
  const call = checkpoint.calls.at(-1);
  if (!call || call.status !== "sent") {
    throw orchestrationError("rf1086_checkpoint_invalid", "RF-1086 checkpoint has no sent call.");
  }

  let hovedskjemaId = checkpoint.hovedskjemaId;
  let confirmation = checkpoint.confirmation;
  if (call.operation === "hovedskjema") {
    if (!call.idempotencyKey) throw orchestrationError("rf1086_checkpoint_invalid", "Hovedskjema call has no idempotency key.");
    const response = await client.submitHovedskjema({
      incomeYear: preview.income_year,
      xml: preview.hovedskjema_xml as string,
      idempotencyKey: call.idempotencyKey,
    });
    hovedskjemaId = response.hovedskjemaId;
  } else if (call.operation.startsWith("underskjema:")) {
    if (!hovedskjemaId || !call.idempotencyKey || !call.documentKey) {
      throw orchestrationError("rf1086_checkpoint_invalid", "Underskjema call is missing persisted references.");
    }
    const xml = preview.underskjema_xml[call.documentKey];
    if (!xml || sha256(xml) !== call.bodyHash) {
      throw orchestrationError("rf1086_preview_changed", "RF-1086 underskjema changed after call preparation.");
    }
    await client.submitUnderskjema({
      incomeYear: preview.income_year,
      hovedskjemaId,
      xml,
      idempotencyKey: call.idempotencyKey,
    });
  } else {
    if (!hovedskjemaId) throw orchestrationError("rf1086_checkpoint_invalid", "Bekreft call has no hovedskjema ID.");
    confirmation = await client.confirmSubmission({
      incomeYear: preview.income_year,
      hovedskjemaId,
      underskjemaCount: Object.keys(preview.underskjema_xml).length,
    });
  }

  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    status: call.operation === "bekreft" ? "confirmed" : "submitting",
    hovedskjemaId,
    confirmation,
    calls: replaceLastCall(checkpoint, {
      ...call,
      status: "accepted",
      acceptedAt: new Date().toISOString(),
      failureCode: null,
      failureMessage: null,
    }),
    failureCode: null,
    failureMessage: null,
  };
}

function failedCheckpoint(
  checkpoint: Rf1086AuthorityCheckpoint,
  error: unknown,
): Rf1086AuthorityCheckpoint {
  const call = checkpoint.calls.at(-1);
  if (!call || call.status !== "sent") {
    throw orchestrationError("rf1086_checkpoint_invalid", "RF-1086 failure has no sent call.");
  }
  const authorityError = error instanceof Rf1086AuthorityError ? error : null;
  const confirmationUnknown = call.operation === "bekreft" && Boolean(authorityError?.retryable);
  const retryable = Boolean(authorityError?.retryable) && !confirmationUnknown;
  const status = retryable ? "failed_retryable" : "failed_blocked";
  const code = confirmationUnknown
    ? "rf1086_confirm_outcome_unknown"
    : (authorityError?.code ?? "rf1086_authority_failure_unclassified");
  const message = confirmationUnknown
    ? "RF-1086 confirmation outcome is unknown and requires operator reconciliation before another call."
    : `RF-1086 authority call failed (${code}).`;
  return {
    ...checkpoint,
    revision: checkpoint.revision + 1,
    status,
    calls: replaceLastCall(checkpoint, {
      ...call,
      status,
      failureCode: code,
      failureMessage: message,
    }),
    failureCode: code,
    failureMessage: message,
  };
}

export async function runNextRf1086AuthorityStep(input: {
  preview: FilingPreviewRow;
  client: Rf1086AuthorityClient;
  journal: Rf1086AuthorityJournal;
}): Promise<{ checkpoint: Rf1086AuthorityCheckpoint; complete: boolean }> {
  assertPreview(input.preview);
  const loaded = await input.journal.load(input.preview.id);
  let checkpoint = loaded ?? newCheckpoint(input.preview, input.client.environment);
  const expectedRevision = loaded?.revision ?? null;
  if (loaded) {
    if (loaded.environment !== input.client.environment) {
      throw orchestrationError("rf1086_environment_changed", "RF-1086 authority environment cannot change during a submission.");
    }
    if (loaded.payloadHash !== canonicalPayloadHash(input.preview)) {
      throw orchestrationError("rf1086_preview_changed", "RF-1086 preview cannot change during a submission.");
    }
    assertRf1086AuthorityCheckpoint(loaded, input.preview);
    if (loaded.status === "confirmed") return { checkpoint: loaded, complete: true };
    if (loaded.status === "failed_blocked") {
      throw orchestrationError("rf1086_checkpoint_blocked", "RF-1086 authority checkpoint requires operator resolution.");
    }
    const last = loaded.calls.at(-1);
    if (last?.status === "sent" && last.operation === "bekreft") {
      const blocked = blockUnknownConfirmation(loaded);
      await input.journal.save(blocked, loaded.revision);
      return { checkpoint: blocked, complete: false };
    }
  }

  if (checkpoint.status === "failed_retryable" || checkpoint.calls.at(-1)?.status === "sent") {
    checkpoint = prepareRetry(checkpoint);
    await input.journal.save(checkpoint, expectedRevision);
  } else if (checkpoint.calls.at(-1)?.status !== "prepared") {
    checkpoint = nextPreparedCheckpoint(checkpoint, input.preview);
    await input.journal.save(checkpoint, expectedRevision);
  }

  const sent = markSent(checkpoint);
  await input.journal.save(sent, checkpoint.revision);
  checkpoint = sent;

  let accepted: Rf1086AuthorityCheckpoint;
  try {
    accepted = await executePreparedCall(checkpoint, input.preview, input.client);
  } catch (error) {
    if (error instanceof Rf1086AuthorityOrchestrationError) throw error;
    const failed = failedCheckpoint(checkpoint, error);
    await input.journal.save(failed, checkpoint.revision);
    return { checkpoint: failed, complete: false };
  }
  await input.journal.save(accepted, checkpoint.revision);
  return { checkpoint: accepted, complete: accepted.status === "confirmed" };
}
