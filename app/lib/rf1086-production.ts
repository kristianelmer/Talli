import { createHash, randomUUID } from "node:crypto";
import {
  Rf1086AuthorityError,
  type Rf1086AuthorityClient,
} from "./rf1086-authority-client.ts";
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

function sha256(value: string) {
  return createHash("sha256").update(value, "utf8").digest("hex");
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
      const result = await dependencies.authorityClient.listDocuments({
        incomeYear: input.incomeYear,
        referenceId: confirmation.forsendelseId,
      });
      return safeJsonReference({ documentCount: result.documents.length });
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
