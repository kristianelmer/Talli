import { createHash, randomUUID } from "node:crypto";
import {
  Rf1086AuthorityError,
  type Rf1086ArchiveDocument,
  type Rf1086AuthorityClient,
} from "./rf1086-authority-client.ts";
import {
  classifyRf1086Feedback,
  type Rf1086FeedbackClassification,
} from "./rf1086-feedback.ts";
import {
  classifyRf1086TransportOutcome,
  type ProductionSubmissionStatus,
} from "./production-submission.ts";

export type ProductionOperationState = "prepared" | "succeeded" | "failed" | "unknown";
export type ProductionOperation = {
  id: string;
  name: string;
  state: ProductionOperationState;
  attempt: number;
  bodyHash: string | null;
  idempotencyKey: string | null;
  authorityReference: string | null;
  failureClassification: "retryable" | "blocked" | "unknown" | null;
};

export interface ProductionOperationJournal {
  prepare(input: {
    submissionId: string;
    name: string;
    bodyHash: string | null;
    idempotencyKey: string | null;
  }): Promise<ProductionOperation>;
  succeed(operationId: string, authorityReference: string | null): Promise<void>;
  fail(operationId: string, failure: {
    classification: "retryable" | "blocked" | "unknown";
    code: string;
    correlationId: string | null;
  }): Promise<void>;
}

export type JournaledRf1086ProductionInput = {
  submissionId: string;
  incomeYear: number;
  hovedskjemaXml: string;
  underskjemaXml: Record<string, string>;
};

export type JournaledRf1086ProductionResult = {
  status: ProductionSubmissionStatus;
  hovedskjemaId: string;
  dialogId: string;
  forsendelseId: string;
  documentCount: number;
  finalAuthorityDecision: null;
};

export type Rf1086ProductionReleaseDependencies<Token, Submission> = {
  acquireDelegatedToken(): Promise<Token>;
  beginProductionFiling(): Promise<Submission>;
  executeExternalSubmission(input: {
    token: Token;
    submission: Submission;
  }): Promise<void>;
  discardToken(token: Token): void;
};

export async function executeRf1086ProductionRelease<Token, Submission>(
  dependencies: Rf1086ProductionReleaseDependencies<Token, Submission>,
): Promise<Submission> {
  const token = await dependencies.acquireDelegatedToken();
  try {
    const submission = await dependencies.beginProductionFiling();
    await dependencies.executeExternalSubmission({ token, submission });
    return submission;
  } finally {
    dependencies.discardToken(token);
  }
}

function sha256(value: string) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function sha256Bytes(value: Uint8Array) {
  return createHash("sha256").update(value).digest("hex");
}

function safeJsonReference(value: Record<string, unknown>) {
  return JSON.stringify(value);
}

function parseReference(value: string | null, label: string) {
  if (!value) throw new Error(`RF-1086 journal is missing ${label}.`);
  return value;
}

export class Rf1086UnknownProductionOutcomeError extends Error {
  readonly code = "rf1086_unknown_production_outcome";

  constructor(operationName: string) {
    super(`RF-1086 authority operation ${operationName} has an unknown outcome and requires read-only reconciliation.`);
    this.name = "Rf1086UnknownProductionOutcomeError";
  }
}

export class Rf1086BlockedProductionOperationError extends Error {
  readonly code = "rf1086_blocked_production_operation";

  constructor(operationName: string) {
    super(`RF-1086 authority operation ${operationName} is blocked and requires a new reviewed filing.`);
    this.name = "Rf1086BlockedProductionOperationError";
  }
}

function failureClassification(error: unknown) {
  if (error instanceof Rf1086AuthorityError) {
    if (error.status === null) return "unknown" as const;
    return error.retryable ? "retryable" as const : "blocked" as const;
  }
  return "blocked" as const;
}

async function mutation(input: {
  journal: ProductionOperationJournal;
  submissionId: string;
  name: string;
  bodyHash: string;
  execute: (idempotencyKey: string) => Promise<string>;
}) {
  const operation = await input.journal.prepare({
    submissionId: input.submissionId,
    name: input.name,
    bodyHash: input.bodyHash,
    idempotencyKey: randomUUID(),
  });
  if (operation.state === "succeeded") return parseReference(operation.authorityReference, input.name);
  if (operation.state === "unknown") throw new Rf1086UnknownProductionOutcomeError(input.name);
  if (operation.state === "failed" && operation.failureClassification === "blocked") {
    throw new Rf1086BlockedProductionOperationError(input.name);
  }
  if (!operation.idempotencyKey) throw new Error(`RF-1086 ${input.name} is missing its persisted idempotency key.`);

  try {
    const authorityReference = await input.execute(operation.idempotencyKey);
    await input.journal.succeed(operation.id, authorityReference);
    return authorityReference;
  } catch (error) {
    const classification = failureClassification(error);
    await input.journal.fail(operation.id, {
      classification,
      code: error instanceof Rf1086AuthorityError ? error.code : "RF1086_OPERATION_ERROR",
      correlationId: error instanceof Rf1086AuthorityError ? error.correlationId : null,
    });
    if (classification === "unknown") throw new Rf1086UnknownProductionOutcomeError(input.name);
    throw error;
  }
}

async function readOperation(input: {
  journal: ProductionOperationJournal;
  submissionId: string;
  name: string;
  execute: () => Promise<string>;
}) {
  const operation = await input.journal.prepare({
    submissionId: input.submissionId,
    name: input.name,
    bodyHash: null,
    idempotencyKey: null,
  });
  if (operation.state === "succeeded") return parseReference(operation.authorityReference, input.name);
  try {
    const reference = await input.execute();
    await input.journal.succeed(operation.id, reference);
    return reference;
  } catch (error) {
    await input.journal.fail(operation.id, {
      classification: error instanceof Rf1086AuthorityError && error.retryable ? "retryable" : "blocked",
      code: error instanceof Rf1086AuthorityError ? error.code : "RF1086_READ_ERROR",
      correlationId: error instanceof Rf1086AuthorityError ? error.correlationId : null,
    });
    throw error;
  }
}

export async function executeJournaledRf1086Production(
  input: JournaledRf1086ProductionInput,
  dependencies: {
    journal: ProductionOperationJournal;
    authorityClient: Pick<
      Rf1086AuthorityClient,
      "postHovedskjema" | "postUnderskjema" | "confirm" | "listDocuments"
    >;
  },
): Promise<JournaledRf1086ProductionResult> {
  const entries = Object.entries(input.underskjemaXml).sort(([left], [right]) => left.localeCompare(right));
  if (!input.hovedskjemaXml.trim() || !entries.length) {
    throw new Error("RF-1086 production submission requires one hovedskjema and at least one underskjema.");
  }

  const hovedskjemaId = await mutation({
    journal: dependencies.journal,
    submissionId: input.submissionId,
    name: "post_hovedskjema",
    bodyHash: sha256(input.hovedskjemaXml),
    execute: async (idempotencyKey) => {
      const result = await dependencies.authorityClient.postHovedskjema({
        incomeYear: input.incomeYear,
        xml: input.hovedskjemaXml,
        idempotencyKey,
      });
      return result.hovedskjemaId;
    },
  });

  for (const [documentName, xml] of entries) {
    await mutation({
      journal: dependencies.journal,
      submissionId: input.submissionId,
      name: `post_underskjema:${documentName}`,
      bodyHash: sha256(xml),
      execute: async (idempotencyKey) => {
        await dependencies.authorityClient.postUnderskjema({
          incomeYear: input.incomeYear,
          hovedskjemaId,
          xml,
          idempotencyKey,
        });
        return "posted";
      },
    });
  }

  const confirmationReference = await mutation({
    journal: dependencies.journal,
    submissionId: input.submissionId,
    name: "confirm",
    bodyHash: sha256(`${hovedskjemaId}:${entries.length}`),
    execute: async (idempotencyKey) => {
      const result = await dependencies.authorityClient.confirm({
        incomeYear: input.incomeYear,
        hovedskjemaId,
        underskjemaCount: entries.length,
        idempotencyKey,
      });
      return safeJsonReference({
        dialogId: result.dialogId,
        forsendelseId: result.forsendelseId,
      });
    },
  });
  const confirmation = JSON.parse(confirmationReference) as {
    dialogId: string;
    forsendelseId: string;
  };

  const documentsReference = await readOperation({
    journal: dependencies.journal,
    submissionId: input.submissionId,
    name: "list_documents",
    execute: async () => {
      try {
        const result = await dependencies.authorityClient.listDocuments({
          incomeYear: input.incomeYear,
          referenceId: confirmation.forsendelseId,
        });
        return safeJsonReference({ documentCount: result.documents.length });
      } catch (error) {
        if (pendingArchiveError(error)) {
          return safeJsonReference({ documentCount: 0 });
        }
        throw error;
      }
    },
  });
  const { documentCount } = JSON.parse(documentsReference) as { documentCount: number };
  const status = classifyRf1086TransportOutcome({
    forsendelseId: confirmation.forsendelseId,
    documents: Array.from({ length: documentCount }, () => "archived-document"),
    finalAuthorityDecision: null,
  });

  return {
    status,
    hovedskjemaId,
    dialogId: confirmation.dialogId,
    forsendelseId: confirmation.forsendelseId,
    documentCount,
    finalAuthorityDecision: null,
  };
}

export type Rf1086ReconciliationState =
  | "sent"
  | "processing"
  | "accepted"
  | "rejected"
  | "action_required"
  | "unknown";

export type Rf1086ReconciliationSnapshot = {
  state: Rf1086ReconciliationState;
  artifactHashes: string[];
  safeErrorCode: string | null;
  correlationId: string | null;
};

export type Rf1086ReconciliationArtifact = {
  submissionId: string;
  companyId: string;
  authorityReference: string;
  contentType: string;
  bytes: Uint8Array;
  byteLength: number;
  sha256: string;
  classification: Rf1086FeedbackClassification;
};

export class Rf1086FeedbackArtifactPersistenceError extends Error {
  readonly retryable: boolean;

  constructor(message: string, options: { retryable: boolean; cause?: unknown }) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "Rf1086FeedbackArtifactPersistenceError";
    this.retryable = options.retryable;
  }
}

export interface Rf1086ProductionJournal {
  readReconciliationState(): Promise<Rf1086ReconciliationSnapshot>;
  recordArtifact(artifact: Rf1086ReconciliationArtifact): Promise<string>;
  appendReconciliation(event: {
    state: Rf1086ReconciliationState;
    artifactHashes: string[];
    safeErrorCode: string | null;
    correlationId: string | null;
  }): Promise<boolean>;
}

export type Rf1086ReconciliationInput = {
  submissionId: string;
  companyId: string;
  incomeYear: number;
  forsendelseId: string;
  hovedskjemaXml: string;
  underskjemaXml: Record<string, string>;
};

export type Rf1086ReconciliationResult = {
  state: Rf1086ReconciliationState;
  archiveReads: number;
  artifactCount: number;
  artifactHashes: string[];
  safeErrorCode: string | null;
  correlationId: string | null;
  changed: boolean;
};

type ReadOnlyRf1086Authority = Pick<Rf1086AuthorityClient, "listDocuments" | "getDocument">;

function pendingArchiveError(error: unknown) {
  return error instanceof Rf1086AuthorityError
    && (error.code === "GLD_021" || error.code === "GLD_1017");
}

function safeReconciliationFailure(error: unknown) {
  if (pendingArchiveError(error)) {
    return { state: "processing" as const, safeErrorCode: null, correlationId: null };
  }
  if (error instanceof Rf1086AuthorityError) {
    return {
      state: error.status === null || error.retryable ? "unknown" as const : "action_required" as const,
      safeErrorCode: error.code,
      correlationId: error.correlationId,
    };
  }
  return {
    state: "unknown" as const,
    safeErrorCode: "RF1086_RECONCILIATION_READ_ERROR",
    correlationId: null,
  };
}

function classifyCombinedFeedback(classifications: Rf1086FeedbackClassification[]) {
  if (classifications.length === 0) {
    return { state: "processing" as const, safeErrorCode: null };
  }
  if (classifications.includes("action_required")) {
    return { state: "action_required" as const, safeErrorCode: "RF1086_FEEDBACK_ACTION_REQUIRED" };
  }
  const unique = new Set(classifications);
  if (unique.size !== 1) {
    return { state: "action_required" as const, safeErrorCode: "RF1086_FEEDBACK_CONFLICT" };
  }
  return {
    state: classifications[0] as "accepted" | "rejected",
    safeErrorCode: classifications[0] === "accepted" ? "RF1086_FEEDBACK_ACCEPTED" : "RF1086_FEEDBACK_REJECTED",
  };
}

async function readRf1086FeedbackOnce(
  journal: Rf1086ProductionJournal,
  authority: ReadOnlyRf1086Authority,
  input: Rf1086ReconciliationInput,
  submittedHashes: Set<string>,
  artifactHashes: Set<string>,
) {
  let page;
  try {
    page = await authority.listDocuments({
      incomeYear: input.incomeYear,
      referenceId: input.forsendelseId,
      page: 0,
      size: 50,
    });
  } catch (error) {
    return safeReconciliationFailure(error);
  }

  if (
    !page.documentShapeValid
    || page.currentPage !== 0
    || page.totalPages > 1
    || page.totalItems !== page.documents.length
  ) {
    return {
      state: "action_required" as const,
      safeErrorCode: "RF1086_ARCHIVE_SHAPE_INVALID",
      correlationId: null,
    };
  }
  if (page.documents.length === 0) {
    return { state: "processing" as const, safeErrorCode: null, correlationId: null };
  }

  const classifications: Rf1086FeedbackClassification[] = [];
  for (const archiveDocument of page.documents as Rf1086ArchiveDocument[]) {
    let authorityReference: string;
    let contentType: string;
    let bytes: Uint8Array;
    if (typeof archiveDocument === "string") {
      bytes = new TextEncoder().encode(archiveDocument);
      contentType = "application/xml";
      authorityReference = `inline:${sha256Bytes(bytes)}`;
    } else {
      try {
        const document = await authority.getDocument({
          incomeYear: input.incomeYear,
          forsendelseId: input.forsendelseId,
          documentId: archiveDocument.reference,
        });
        authorityReference = document.reference;
        contentType = document.contentType;
        bytes = document.bytes;
      } catch (error) {
        return safeReconciliationFailure(error);
      }
    }

    const hash = sha256Bytes(bytes);
    if (submittedHashes.has(hash)) continue;

    const feedback = contentType === "application/xml" || contentType === "text/xml"
      ? classifyRf1086Feedback(bytes, {
        forsendelseId: input.forsendelseId,
        incomeYear: input.incomeYear,
      })
      : {
        classification: "action_required" as const,
        schema: "unknown" as const,
        transmissionId: null,
      };
    classifications.push(feedback.classification);
    try {
      const persistedHash = await journal.recordArtifact({
        submissionId: input.submissionId,
        companyId: input.companyId,
        authorityReference,
        contentType,
        bytes,
        byteLength: bytes.byteLength,
        sha256: hash,
        classification: feedback.classification,
      });
      artifactHashes.add(persistedHash);
    } catch (error) {
      if (
        error instanceof Rf1086FeedbackArtifactPersistenceError
        && error.retryable
      ) {
        return {
          state: "unknown" as const,
          safeErrorCode: "RF1086_FEEDBACK_ARTIFACT_PERSIST_RETRY",
          correlationId: null,
        };
      }
      return {
        state: "action_required" as const,
        safeErrorCode: "RF1086_FEEDBACK_ARTIFACT_PERSIST_FAILED",
        correlationId: null,
      };
    }
  }

  const combined = classifyCombinedFeedback(classifications);
  return { ...combined, correlationId: null };
}

export async function reconcileJournaledRf1086Production(
  journal: Rf1086ProductionJournal,
  authority: ReadOnlyRf1086Authority,
  input: Rf1086ReconciliationInput,
  options: {
    initialPoll?: boolean;
    sleep?: (milliseconds: number) => Promise<void>;
  } = {},
): Promise<Rf1086ReconciliationResult> {
  if (
    !input.submissionId
    || !input.companyId
    || !input.forsendelseId
    || !Number.isInteger(input.incomeYear)
    || !input.hovedskjemaXml.trim()
    || Object.keys(input.underskjemaXml).length < 1
  ) {
    throw new Error("RF-1086 reconciliation requires the exact journaled submission relationship.");
  }
  const snapshot = await journal.readReconciliationState();
  const artifactHashes = new Set(snapshot.artifactHashes);
  const submittedHashes = new Set([
    sha256(input.hovedskjemaXml),
    ...Object.values(input.underskjemaXml).map((xml) => sha256(xml)),
  ]);
  const initialPoll = options.initialPoll ?? snapshot.state === "sent";
  const maximumReads = initialPoll ? 5 : 1;
  const sleep = options.sleep ?? (async (milliseconds: number) => {
    await new Promise((resolve) => setTimeout(resolve, milliseconds));
  });
  let archiveReads = 0;
  let outcome = {
    state: "processing" as Rf1086ReconciliationState,
    safeErrorCode: null as string | null,
    correlationId: null as string | null,
  };

  for (let attempt = 1; attempt <= maximumReads; attempt += 1) {
    archiveReads += 1;
    outcome = await readRf1086FeedbackOnce(
      journal,
      authority,
      input,
      submittedHashes,
      artifactHashes,
    );
    if (outcome.state !== "processing" || attempt === maximumReads) break;
    await sleep(2_000);
  }

  const sortedArtifactHashes = [...artifactHashes].sort();
  const changed = await journal.appendReconciliation({
    state: outcome.state,
    artifactHashes: sortedArtifactHashes,
    safeErrorCode: outcome.safeErrorCode,
    correlationId: outcome.correlationId,
  });
  return {
    state: outcome.state,
    archiveReads,
    artifactCount: sortedArtifactHashes.length,
    artifactHashes: sortedArtifactHashes,
    safeErrorCode: outcome.safeErrorCode,
    correlationId: outcome.correlationId,
    changed,
  };
}
