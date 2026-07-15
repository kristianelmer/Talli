import assert from "node:assert/strict";
import test from "node:test";

import { Rf1086AuthorityError } from "../app/lib/rf1086-authority-client.ts";
import { executeJournaledRf1086Production } from "../app/lib/rf1086-production.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

const input = {
  submissionId: "submission-id",
  incomeYear: 2025,
  hovedskjemaXml: "<H />",
  underskjemaXml: { owner: "<U />" },
};

function createJournal() {
  const operations = [];
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

test("resumes succeeded mutations without sending them twice", async () => {
  const journal = createJournal();
  const firstClient = createAuthorityClient();
  await executeJournaledRf1086Production(input, { journal, authorityClient: firstClient });

  const resumedClient = createAuthorityClient();
  const result = await executeJournaledRf1086Production(input, { journal, authorityClient: resumedClient });
  assert.equal(resumedClient.calls.length, 0);
  assert.equal(result.status, "processing");
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
