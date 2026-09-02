import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { Rf1086AuthorityError } from "../apps/web/app/lib/rf1086-authority-client.ts";
import { createRf1086FeedbackArtifactRecorder } from "../apps/web/app/lib/rf1086-feedback-persistence.ts";
import {
  Rf1086FeedbackArtifactPersistenceError,
  createRf1086FeedbackArtifactPersistenceError,
  executeJournaledRf1086Production,
  reconcileJournaledRf1086Production,
} from "../apps/web/app/lib/rf1086-production.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

const input = {
  submissionId: "submission-id",
  incomeYear: 2025,
  hovedskjemaXml: "<H />",
  underskjemaXml: { owner: "<U />" },
};

function createJournal(seed = []) {
  const operations = seed.map((operation) => ({ ...operation }));
  return {
    operations,
    async prepare(candidate) {
      const existing = operations.find((operation) => operation.name === candidate.name);
      if (existing) return { ...existing };
      const operation = {
        id: `operation-${operations.length + 1}`,
        name: candidate.name,
        state: "prepared",
        attempt: 1,
        bodyHash: candidate.bodyHash,
        idempotencyKey: candidate.idempotencyKey,
        authorityReference: null,
        failureClassification: null,
      };
      operations.push(operation);
      return { ...operation };
    },
    async succeed(operationId, authorityReference) {
      const operation = operations.find((item) => item.id === operationId);
      operation.state = "succeeded";
      operation.authorityReference = authorityReference;
    },
    async fail(operationId, failure) {
      const operation = operations.find((item) => item.id === operationId);
      operation.state = failure.classification === "unknown" ? "unknown" : "failed";
      operation.failureClassification = failure.classification;
    },
  };
}

function createAuthorityClient() {
  const calls = [];
  return {
    calls,
    async postHovedskjema(options) {
      calls.push(["hoved", options]);
      return { hovedskjemaId: "10000000-0000-4000-8000-000000000001", call: {} };
    },
    async postUnderskjema(options) {
      calls.push(["under", options]);
      return { call: {} };
    },
    async confirm(options) {
      calls.push(["confirm", options]);
      return {
        oppgavegiversLeveranseReferanse: "delivery",
        dialogId: "20000000-0000-4000-8000-000000000002",
        forsendelseId: "30000000-0000-4000-8000-000000000003",
        call: {},
      };
    },
    async listDocuments(options) {
      calls.push(["documents", options]);
      return { totalItems: 2, totalPages: 1, currentPage: 0, documents: ["<H />", "<U />"], call: {} };
    },
  };
}

test("persists stable prepared keys before each authority mutation and reports processing", async () => {
  const journal = createJournal();
  const authorityClient = createAuthorityClient();
  const result = await executeJournaledRf1086Production(input, { journal, authorityClient });

  assert.deepEqual(journal.operations.map((operation) => [operation.name, operation.state]), [
    ["post_hovedskjema", "succeeded"],
    ["post_underskjema:owner", "succeeded"],
    ["confirm", "succeeded"],
    ["list_documents", "succeeded"],
  ]);
  assert.ok(journal.operations.slice(0, 3).every((operation) => UUID_PATTERN.test(operation.idempotencyKey)));
  assert.equal(journal.operations[3].idempotencyKey, null);
  assert.equal(result.status, "processing");
  assert.equal(result.forsendelseId, "30000000-0000-4000-8000-000000000003");
  assert.equal(result.finalAuthorityDecision, null);
});

test("confirmation remains journaled when the first archive read is still pending", async () => {
  const journal = createJournal();
  const authorityClient = createAuthorityClient();
  authorityClient.listDocuments = async () => {
    throw pendingError();
  };

  const result = await executeJournaledRf1086Production(input, { journal, authorityClient });

  assert.equal(result.status, "received");
  assert.equal(result.documentCount, 0);
  assert.deepEqual(journal.operations.map((operation) => [operation.name, operation.state]).slice(-2), [
    ["confirm", "succeeded"],
    ["list_documents", "succeeded"],
  ]);
});

test("resumes succeeded mutations without sending them twice", async () => {
  const journal = createJournal();
  const firstClient = createAuthorityClient();
  await executeJournaledRf1086Production(input, { journal, authorityClient: firstClient });

  const resumedClient = createAuthorityClient();
  const result = await executeJournaledRf1086Production(input, { journal, authorityClient: resumedClient });
  assert.equal(resumedClient.calls.length, 0);
  assert.equal(result.status, "processing");
});

test("resumes a retryable mutation with its persisted idempotency key", async () => {
  const journal = createJournal([{
    id: "operation-1",
    name: "post_hovedskjema",
    state: "failed",
    attempt: 1,
    bodyHash: "persisted-hash",
    idempotencyKey: "persisted-idempotency-key",
    authorityReference: null,
    failureClassification: "retryable",
  }]);
  const authorityClient = createAuthorityClient();
  const result = await executeJournaledRf1086Production(input, { journal, authorityClient });

  assert.equal(authorityClient.calls[0][1].idempotencyKey, "persisted-idempotency-key");
  assert.equal(result.status, "processing");
});

test("does not retry a mutation that authority already blocked", async () => {
  const journal = createJournal([{
    id: "operation-1",
    name: "post_hovedskjema",
    state: "failed",
    attempt: 1,
    bodyHash: "persisted-hash",
    idempotencyKey: "persisted-idempotency-key",
    authorityReference: null,
    failureClassification: "blocked",
  }]);
  const authorityClient = createAuthorityClient();

  await assert.rejects(
    executeJournaledRf1086Production(input, { journal, authorityClient }),
    /blocked and requires a new reviewed filing/u,
  );
  assert.equal(authorityClient.calls.length, 0);
});

test("quarantines a mutation timeout instead of retrying", async () => {
  const journal = createJournal();
  let postCount = 0;
  const authorityClient = createAuthorityClient();
  authorityClient.postHovedskjema = async () => {
    postCount += 1;
    throw new Rf1086AuthorityError("network timeout", {
      code: "RF1086_NETWORK_ERROR",
      status: null,
      retryable: true,
    });
  };

  await assert.rejects(
    executeJournaledRf1086Production(input, { journal, authorityClient }),
    /unknown outcome/i,
  );
  assert.equal(journal.operations.at(-1).state, "unknown");
  assert.equal(postCount, 1);
  await assert.rejects(
    executeJournaledRf1086Production(input, { journal, authorityClient }),
    /unknown outcome/i,
  );
  assert.equal(postCount, 1);
});

test("records an explicit authority rejection as blocked without leaking XML", async () => {
  const journal = createJournal();
  const authorityClient = createAuthorityClient();
  authorityClient.postHovedskjema = async () => {
    throw new Rf1086AuthorityError("validation rejected", {
      code: "GLD_010",
      status: 400,
      retryable: false,
    });
  };
  await assert.rejects(executeJournaledRf1086Production(input, { journal, authorityClient }), /validation rejected/u);
  assert.equal(journal.operations[0].failureClassification, "blocked");
  assert.doesNotMatch(JSON.stringify(journal.operations), /<H|<U/u);
});

const FEEDBACK_NS = "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:innsendingstilbakemelding:v2";
const forsendelseId = "30000000-0000-4000-8000-000000000003";
const acceptedFeedback = `
  <tilbakemelding xmlns="${FEEDBACK_NS}">
    <innsending><forsendelseid>${forsendelseId}</forsendelseid></innsending>
    <leveranse><leveransestatus>godkjent</leveransestatus><inntektsaar>2025</inntektsaar></leveranse>
  </tilbakemelding>`;

function createReconciliationJournal(state = "sent") {
  const artifacts = new Map();
  const events = [];
  let snapshot = { state, artifactHashes: [], safeErrorCode: null, correlationId: null };
  return {
    artifacts,
    events,
    async readReconciliationState() {
      return { ...snapshot, artifactHashes: [...snapshot.artifactHashes] };
    },
    async recordArtifact(artifact) {
      artifacts.set(artifact.sha256, { ...artifact, bytes: new Uint8Array(artifact.bytes) });
      return artifact.sha256;
    },
    async appendReconciliation(event) {
      const artifactHashes = [...event.artifactHashes].sort();
      if (
        snapshot.state === event.state
        && JSON.stringify(snapshot.artifactHashes) === JSON.stringify(artifactHashes)
        && snapshot.safeErrorCode === event.safeErrorCode
        && snapshot.correlationId === event.correlationId
      ) return false;
      snapshot = { ...event, artifactHashes };
      events.push({ kind: "reconciliation", ...event, artifactHashes });
      return true;
    },
  };
}

function pendingError(specificationCodes = ["GLD_1017"]) {
  return new Rf1086AuthorityError("pending", {
    status: 404,
    code: "GLD_021",
    specificationCodes,
    retryable: false,
  });
}

test("initial reconciliation polls five times without another POST", async () => {
  const journal = createReconciliationJournal("sent");
  const sequence = [
    pendingError(),
    { totalItems: 0, totalPages: 0, currentPage: 0, documents: [], documentShapeValid: true },
    pendingError(),
    { totalItems: 0, totalPages: 0, currentPage: 0, documents: [], documentShapeValid: true },
    { totalItems: 1, totalPages: 1, currentPage: 0, documents: [acceptedFeedback], documentShapeValid: true },
  ];
  const authority = {
    postCalls: 0,
    async listDocuments() {
      const next = sequence.shift();
      if (next instanceof Error) throw next;
      return next;
    },
    async getDocument() {
      throw new Error("not expected");
    },
  };

  const result = await reconcileJournaledRf1086Production(journal, authority, {
    submissionId: "submission-id",
    companyId: "company-id",
    incomeYear: 2025,
    forsendelseId,
    hovedskjemaXml: "<H />",
    underskjemaXml: { owner: "<U />" },
  }, { initialPoll: true, sleep: async () => {} });

  assert.equal(result.state, "accepted");
  assert.equal(result.archiveReads, 5);
  assert.equal(authority.postCalls, 0);
  assert.equal(journal.events.length, 1);
  assert.equal(journal.artifacts.size, 1);
  assert.doesNotMatch(JSON.stringify(journal.events), /tilbakemelding|<H|<U/u);
});

test("later reconciliation reads once and appends only state or artifact changes", async () => {
  const journal = createReconciliationJournal("sent");
  let archiveReads = 0;
  const authority = {
    async listDocuments() {
      archiveReads += 1;
      return { totalItems: 0, totalPages: 0, currentPage: 0, documents: [], documentShapeValid: true };
    },
    async getDocument() {
      throw new Error("not expected");
    },
  };
  const reconciliationInput = {
    submissionId: "submission-id",
    companyId: "company-id",
    incomeYear: 2025,
    forsendelseId,
    hovedskjemaXml: "<H />",
    underskjemaXml: { owner: "<U />" },
  };

  await reconcileJournaledRf1086Production(journal, authority, reconciliationInput, { initialPoll: false });
  await reconcileJournaledRf1086Production(journal, authority, reconciliationInput, { initialPoll: false });

  assert.equal(archiveReads, 2);
  assert.equal(journal.events.filter((event) => event.kind === "reconciliation").length, 1);
  assert.equal(journal.events[0].state, "processing");
});

test("submitted XML hashes are ignored while strict references are downloaded and classified", async () => {
  const journal = createReconciliationJournal("processing");
  let documentReads = 0;
  const authority = {
    async listDocuments() {
      return {
        totalItems: 3,
        totalPages: 1,
        currentPage: 0,
        documents: ["<H />", "<U />", { reference: "40000000-0000-4000-8000-000000000004" }],
        documentShapeValid: true,
      };
    },
    async getDocument({ documentId }) {
      documentReads += 1;
      return {
        reference: documentId,
        contentType: "application/xml",
        bytes: new TextEncoder().encode(acceptedFeedback),
      };
    },
  };
  const result = await reconcileJournaledRf1086Production(journal, authority, {
    submissionId: "submission-id",
    companyId: "company-id",
    incomeYear: 2025,
    forsendelseId,
    hovedskjemaXml: "<H />",
    underskjemaXml: { owner: "<U />" },
  }, { initialPoll: false });

  assert.equal(result.state, "accepted");
  assert.equal(documentReads, 1);
  assert.equal(journal.artifacts.size, 1);
});

test("unknown archive shapes and malformed or mismatched feedback require action", async () => {
  for (const response of [
    { totalItems: 1, totalPages: 1, currentPage: 0, documents: [], documentShapeValid: false },
    {
      totalItems: 1,
      totalPages: 1,
      currentPage: 0,
      documents: [acceptedFeedback.replace(forsendelseId, "40000000-0000-4000-8000-000000000004")],
      documentShapeValid: true,
    },
  ]) {
    const journal = createReconciliationJournal("processing");
    const authority = {
      async listDocuments() { return response; },
      async getDocument() { throw new Error("not expected"); },
    };
    const result = await reconcileJournaledRf1086Production(journal, authority, {
      submissionId: "submission-id",
      companyId: "company-id",
      incomeYear: 2025,
      forsendelseId,
      hovedskjemaXml: "<H />",
      underskjemaXml: { owner: "<U />" },
    }, { initialPoll: false });
    assert.equal(result.state, "action_required");
  }
});

test("transport uncertainty is durable unknown with safe codes only", async () => {
  const journal = createReconciliationJournal("processing");
  const authority = {
    async listDocuments() {
      throw new Rf1086AuthorityError("raw transport details", {
        status: null,
        code: "RF1086_NETWORK_ERROR",
        correlationId: "safe-correlation-1",
        retryable: true,
      });
    },
    async getDocument() { throw new Error("not expected"); },
  };
  const result = await reconcileJournaledRf1086Production(journal, authority, {
    submissionId: "submission-id",
    companyId: "company-id",
    incomeYear: 2025,
    forsendelseId,
    hovedskjemaXml: "<H />",
    underskjemaXml: { owner: "<U />" },
  }, { initialPoll: false });

  assert.equal(result.state, "unknown");
  assert.equal(journal.events[0].safeErrorCode, "RF1086_NETWORK_ERROR");
  assert.equal(journal.events[0].correlationId, "safe-correlation-1");
  assert.doesNotMatch(JSON.stringify(journal.events), /raw transport details/u);
});

test("bare GLD_021 and bare GLD_1017 archive responses remain processing", async () => {
  for (const code of ["GLD_021", "GLD_1017"]) {
    const journal = createReconciliationJournal("processing");
    const authority = {
      async listDocuments() {
        throw new Rf1086AuthorityError("archive pending", {
          status: 404,
          code,
          specificationCodes: [],
          retryable: false,
        });
      },
      async getDocument() { throw new Error("not expected"); },
    };
    const result = await reconcileJournaledRf1086Production(journal, authority, {
      submissionId: "submission-id",
      companyId: "company-id",
      incomeYear: 2025,
      forsendelseId,
      hovedskjemaXml: "<H />",
      underskjemaXml: { owner: "<U />" },
    }, { initialPoll: false });

    assert.equal(result.state, "processing", code);
    assert.equal(result.safeErrorCode, null, code);
  }
});

test("a transient artifact persistence failure remains reclaimable and retries read-only", async () => {
  const journal = createReconciliationJournal("processing");
  const persist = journal.recordArtifact.bind(journal);
  let persistenceAttempts = 0;
  journal.recordArtifact = async (artifact) => {
    persistenceAttempts += 1;
    if (persistenceAttempts === 1) {
      throw new Rf1086FeedbackArtifactPersistenceError(
        "temporary private storage outage",
        { retryable: true },
      );
    }
    return persist(artifact);
  };
  const authority = {
    postCalls: 0,
    archiveReads: 0,
    async listDocuments() {
      this.archiveReads += 1;
      return {
        totalItems: 1,
        totalPages: 1,
        currentPage: 0,
        documents: [acceptedFeedback],
        documentShapeValid: true,
      };
    },
    async getDocument() { throw new Error("not expected"); },
  };
  const reconciliationInput = {
    submissionId: "submission-id",
    companyId: "company-id",
    incomeYear: 2025,
    forsendelseId,
    hovedskjemaXml: "<H />",
    underskjemaXml: { owner: "<U />" },
  };

  const failedPersistence = await reconcileJournaledRf1086Production(
    journal,
    authority,
    reconciliationInput,
    { initialPoll: false },
  );
  assert.equal(failedPersistence.state, "unknown");
  assert.equal(failedPersistence.safeErrorCode, "RF1086_FEEDBACK_ARTIFACT_PERSIST_RETRY");
  assert.equal(journal.artifacts.size, 0);

  const recovered = await reconcileJournaledRf1086Production(
    journal,
    authority,
    reconciliationInput,
    { initialPoll: false },
  );
  assert.equal(recovered.state, "accepted");
  assert.equal(recovered.artifactCount, 1);
  assert.equal(authority.archiveReads, 2);
  assert.equal(authority.postCalls, 0);
  assert.equal(persistenceAttempts, 2);
});

test("Supabase connection and pool failures remain retryable through the real persistence mapping", async () => {
  for (const code of ["PGRST000", "PGRST003"]) {
    const journal = createReconciliationJournal("processing");
    const persist = journal.recordArtifact.bind(journal);
    let persistenceAttempts = 0;
    journal.recordArtifact = async (artifact) => {
      persistenceAttempts += 1;
      if (persistenceAttempts === 1) {
        throw createRf1086FeedbackArtifactPersistenceError(
          "private feedback persistence failed",
          {
            code,
            details: "connection unavailable",
            hint: null,
            message: "raw Supabase infrastructure detail",
          },
        );
      }
      return persist(artifact);
    };
    const authority = {
      postCalls: 0,
      archiveReads: 0,
      async listDocuments() {
        this.archiveReads += 1;
        return {
          totalItems: 1,
          totalPages: 1,
          currentPage: 0,
          documents: [acceptedFeedback],
          documentShapeValid: true,
        };
      },
      async getDocument() { throw new Error("not expected"); },
    };

    const result = await reconcileJournaledRf1086Production(
      journal,
      authority,
      {
        submissionId: "submission-id",
        companyId: "company-id",
        incomeYear: 2025,
        forsendelseId,
        hovedskjemaXml: "<H />",
        underskjemaXml: { owner: "<U />" },
      },
      { initialPoll: false },
    );

    assert.equal(result.state, "unknown", code);
    assert.equal(result.safeErrorCode, "RF1086_FEEDBACK_ARTIFACT_PERSIST_RETRY", code);

    const recovered = await reconcileJournaledRf1086Production(
      journal,
      authority,
      {
        submissionId: "submission-id",
        companyId: "company-id",
        incomeYear: 2025,
        forsendelseId,
        hovedskjemaXml: "<H />",
        underskjemaXml: { owner: "<U />" },
      },
      { initialPoll: false },
    );
    assert.equal(recovered.state, "accepted", code);
    assert.equal(authority.archiveReads, 2, code);
    assert.equal(authority.postCalls, 0, code);
    assert.equal(persistenceAttempts, 2, code);
  }
});

test("Supabase constraint and schema failures remain terminal through the real persistence mapping", async () => {
  for (const code of ["23505", "42P01", "PGRST202"]) {
    const journal = createReconciliationJournal("processing");
    journal.recordArtifact = async () => {
      throw createRf1086FeedbackArtifactPersistenceError(
        "private feedback persistence failed",
        {
          code,
          details: "database contract mismatch",
          hint: null,
          message: "raw Supabase constraint or schema detail",
        },
      );
    };
    const authority = {
      async listDocuments() {
        return {
          totalItems: 1,
          totalPages: 1,
          currentPage: 0,
          documents: [acceptedFeedback],
          documentShapeValid: true,
        };
      },
      async getDocument() { throw new Error("not expected"); },
    };

    const result = await reconcileJournaledRf1086Production(
      journal,
      authority,
      {
        submissionId: "submission-id",
        companyId: "company-id",
        incomeYear: 2025,
        forsendelseId,
        hovedskjemaXml: "<H />",
        underskjemaXml: { owner: "<U />" },
      },
      { initialPoll: false },
    );

    assert.equal(result.state, "action_required", code);
    assert.equal(result.safeErrorCode, "RF1086_FEEDBACK_ARTIFACT_PERSIST_FAILED", code);
  }
});

function feedbackPersistenceFixture(options = {}) {
  const state = {
    metadata: options.metadata ?? null,
    objects: new Map(options.objects ?? []),
    documents: new Map(),
    metadataReads: 0,
    rpcCalls: 0,
    documentDeletes: 0,
    objectRemovals: 0,
  };
  const service = {
    from(table) {
      if (table === "production_feedback_artifacts") {
        const query = {
          select() { return query; },
          eq() { return query; },
          async maybeSingle() {
            state.metadataReads += 1;
            const error = options.metadataReadErrors?.get(state.metadataReads) ?? null;
            return error ? { data: null, error } : { data: state.metadata, error: null };
          },
        };
        return query;
      }
      throw new Error(`unexpected table ${table}`);
    },
    async rpc(name, payload) {
      assert.equal(name, "record_production_feedback_artifact");
      state.rpcCalls += 1;
      if (options.commitThenLoseResponse) {
        state.metadata = {
          document_id: payload.p_document_id,
          sha256: payload.p_sha256,
        };
      }
      return options.rpcResult ?? {
        data: null,
        error: { code: "PGRST000", message: "response lost" },
      };
    },
  };
  const documents = {
    async store({ documentId, artifact }) {
      state.documents.set(documentId, artifact);
      state.objects.set(documentId, new Uint8Array(artifact.bytes));
      return { contentSha256: artifact.sha256, byteLength: artifact.byteLength };
    },
    async remove(documentId) {
      state.documentDeletes += 1;
      state.objectRemovals += 1;
      state.documents.delete(documentId);
      state.objects.delete(documentId);
    },
  };
  return { service, state, documents };
}

function persistenceArtifact() {
  const bytes = new TextEncoder().encode(acceptedFeedback);
  return {
    submissionId: "submission-id",
    companyId: "company-id",
    authorityReference: "authority-document-id",
    contentType: "application/xml",
    bytes,
    byteLength: bytes.byteLength,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    classification: "accepted",
  };
}

test("ambiguous metadata commit preserves the receipt and the next read-only attempt verifies it", async () => {
  const artifact = persistenceArtifact();
  const { service, state, documents } = feedbackPersistenceFixture({
    commitThenLoseResponse: true,
    metadataReadErrors: new Map([[2, {
      code: "PGRST003",
      details: "pool unavailable",
      hint: null,
      message: "connection pool timeout",
    }]]),
  });
  const recordArtifact = createRf1086FeedbackArtifactRecorder(service, {
    submissionId: "submission-id",
    companyId: "company-id",
    incomeYear: 2025,
    userId: "user-id",
  }, documents);

  await assert.rejects(
    recordArtifact(artifact),
    (error) => error instanceof Rf1086FeedbackArtifactPersistenceError && error.retryable,
  );
  assert.equal(state.objectRemovals, 0);
  assert.equal(state.documentDeletes, 0);
  assert.equal(state.documents.size, 1);
  assert.equal(state.rpcCalls, 1);

  assert.equal(await recordArtifact(artifact), artifact.sha256);
  assert.equal(state.rpcCalls, 1, "existing metadata recovery must not repeat the RPC or filing POST");
  assert.equal(state.objectRemovals, 0);
});

test("authoritative metadata absence permits cleanup of resources owned by the failed attempt", async () => {
  const artifact = persistenceArtifact();
  const { service, state, documents } = feedbackPersistenceFixture();
  const recordArtifact = createRf1086FeedbackArtifactRecorder(service, {
    submissionId: "submission-id",
    companyId: "company-id",
    incomeYear: 2025,
    userId: "user-id",
  }, documents);

  await assert.rejects(recordArtifact(artifact), Rf1086FeedbackArtifactPersistenceError);
  assert.equal(state.documentDeletes, 1);
  assert.equal(state.objectRemovals, 1);
  assert.equal(state.documents.size, 0);
});

test("existing metadata retains only the canonical DocumentId relationship", async () => {
  const artifact = persistenceArtifact();
  const { service, state, documents } = feedbackPersistenceFixture({
    metadata: { document_id: "document-id", sha256: artifact.sha256 },
  });
  const recordArtifact = createRf1086FeedbackArtifactRecorder(service, {
    submissionId: "submission-id",
    companyId: "company-id",
    incomeYear: 2025,
    userId: "user-id",
  }, documents);
  assert.equal(await recordArtifact(artifact), artifact.sha256);
  assert.equal(state.documents.size, 0, "the producer must not inspect or recreate document objects");
});
