import assert from "node:assert/strict";
import test from "node:test";

import {
  AnnualAccountsCompletionError,
  verifyAnnualAccountsSignedInstance,
} from "../app/lib/annual-accounts-completion.ts";
import { runNextAnnualAccountsStep } from "../app/lib/annual-accounts-orchestration.ts";

const operationId = "12345678-1234-4234-9234-123456789abc";
const instanceGuid = "232c5390-9479-4506-a266-9890d7287bfb";
const mainFormId = "ce8665c1-01c3-49f7-960f-196b250a2266";
const accountsFormId = "0445d618-28b8-4af5-95e0-c8c989487e7a";
const signatureId = "7b8b2632-5b85-4d31-86cc-0c8766e4e079";
const completedAt = "2026-07-13T12:42:31.123Z";
const documents = {
  operationId,
  organizationNumber: "310279617",
  incomeYear: 2025,
  mainFormXml: "<?xml version=\"1.0\"?><melding><main /></melding>",
  accountsFormXml: "<?xml version=\"1.0\"?><melding><accounts /></melding>",
};

function clone(value) {
  return value === null ? null : structuredClone(value);
}

function memoryJournal() {
  let checkpoint = null;
  return {
    async load() {
      return clone(checkpoint);
    },
    async save(next, expectedRevision) {
      assert.equal(expectedRevision, checkpoint?.revision ?? null);
      checkpoint = clone(next);
    },
  };
}

function mutationClient() {
  return {
    environment: "test",
    async createDraft() {
      return {
        instance: { ownerPartyId: "500700", instanceGuid },
        organizationNumber: "310279617",
        currentTask: { elementId: "Task_1", altinnTaskType: "data" },
        dataElements: [
          { id: mainFormId, instanceGuid, dataType: "Hovedskjema", contentType: "application/xml", filename: null },
          { id: accountsFormId, instanceGuid, dataType: "Underskjema", contentType: "application/xml", filename: null },
        ],
      };
    },
    async replaceXmlDataElement({ dataElementId }) {
      return {
        id: dataElementId,
        instanceGuid,
        dataType: dataElementId === mainFormId ? "Hovedskjema" : "Underskjema",
        contentType: "application/xml",
        filename: null,
      };
    },
    async validateDraft() {
      return { valid: true, issues: [] };
    },
    async lockForPersonalSignature() {
      return {
        state: "awaiting-person-signature",
        currentTask: { elementId: "Task_2", altinnTaskType: "signing" },
      };
    },
  };
}

async function completedJournal() {
  const journal = memoryJournal();
  const client = mutationClient();
  for (let step = 0; step < 5; step += 1) {
    await runNextAnnualAccountsStep({ documents, client, journal });
  }
  return journal;
}

function signedSnapshot(overrides = {}) {
  return {
    instance: { ownerPartyId: "500700", instanceGuid },
    organizationNumber: "310279617",
    process: { endedAt: completedAt, currentTask: null },
    dataElements: [
      { id: mainFormId, instanceGuid, dataType: "Hovedskjema", contentType: "application/xml", filename: null },
      { id: accountsFormId, instanceGuid, dataType: "Underskjema", contentType: "application/xml", filename: null },
      { id: signatureId, instanceGuid, dataType: "signature", contentType: "application/json", filename: "signature.json" },
    ],
    ...overrides,
  };
}

test("proves that the exact locked annual-accounts instance ended with one signature artifact", async () => {
  const journal = await completedJournal();
  let inspected;
  const evidence = await verifyAnnualAccountsSignedInstance({
    documents,
    journal,
    client: {
      environment: "test",
      async inspectInstance(input) {
        inspected = input;
        return signedSnapshot();
      },
    },
  });

  assert.deepEqual(inspected, {
    instance: { ownerPartyId: "500700", instanceGuid },
    organizationNumber: "310279617",
  });
  const { mainFormHash, accountsFormHash, ...boundedEvidence } = evidence;
  assert.deepEqual(boundedEvidence, {
    schemaVersion: 1,
    environment: "test",
    operationId,
    organizationNumber: "310279617",
    incomeYear: 2025,
    instance: { ownerPartyId: "500700", instanceGuid },
    completedAt,
    mainFormId,
    accountsFormId,
    signatureDataElementId: signatureId,
  });
  assert.match(mainFormHash, /^[0-9a-f]{64}$/u);
  assert.match(accountsFormHash, /^[0-9a-f]{64}$/u);
  assert.doesNotMatch(JSON.stringify(evidence), /<melding>|filename|provider/iu);
});

test("refuses completion evidence before lock or while personal signing is unfinished", async () => {
  const emptyJournal = memoryJournal();
  let calls = 0;
  await assert.rejects(
    verifyAnnualAccountsSignedInstance({
      documents,
      journal: emptyJournal,
      client: { environment: "test", async inspectInstance() { calls += 1; return signedSnapshot(); } },
    }),
    (error) => error instanceof AnnualAccountsCompletionError && error.code === "annual_accounts_completion_not_ready",
  );
  assert.equal(calls, 0);

  const journal = await completedJournal();
  await assert.rejects(
    verifyAnnualAccountsSignedInstance({
      documents,
      journal,
      client: {
        environment: "test",
        async inspectInstance() {
          return signedSnapshot({
            process: {
              endedAt: null,
              currentTask: { elementId: "Task_2", altinnTaskType: "signing" },
            },
          });
        },
      },
    }),
    (error) => error instanceof AnnualAccountsCompletionError && error.code === "annual_accounts_signature_incomplete",
  );
});

test("rejects wrong instance identity and missing, duplicate, or mismatched signature evidence", async () => {
  const variants = [
    signedSnapshot({ instance: { ownerPartyId: "500701", instanceGuid } }),
    signedSnapshot({ organizationNumber: "930835978" }),
    signedSnapshot({ dataElements: signedSnapshot().dataElements.slice(0, 2) }),
    signedSnapshot({ dataElements: [...signedSnapshot().dataElements, signedSnapshot().dataElements[2]] }),
    signedSnapshot({
      dataElements: signedSnapshot().dataElements.map((element) =>
        element.id === signatureId ? { ...element, contentType: "text/plain" } : element),
    }),
    signedSnapshot({
      dataElements: signedSnapshot().dataElements.map((element) =>
        element.id === mainFormId ? { ...element, dataType: "Underskjema" } : element),
    }),
  ];

  for (const snapshot of variants) {
    const journal = await completedJournal();
    await assert.rejects(
      verifyAnnualAccountsSignedInstance({
        documents,
        journal,
        client: { environment: "test", async inspectInstance() { return snapshot; } },
      }),
      (error) => error instanceof AnnualAccountsCompletionError && error.code === "annual_accounts_completion_evidence_invalid",
    );
  }
});
