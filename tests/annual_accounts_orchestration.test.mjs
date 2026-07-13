import assert from "node:assert/strict";
import test from "node:test";

import { AnnualAccountsAltinnError } from "../app/lib/annual-accounts-altinn-client.ts";
import {
  AnnualAccountsOrchestrationError,
  inspectAnnualAccountsProgress,
  runNextAnnualAccountsStep,
} from "../app/lib/annual-accounts-orchestration.ts";

const operationId = "12345678-1234-4234-9234-123456789abc";
const instanceGuid = "232c5390-9479-4506-a266-9890d7287bfb";
const mainFormId = "ce8665c1-01c3-49f7-960f-196b250a2266";
const accountsFormId = "0445d618-28b8-4af5-95e0-c8c989487e7a";
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

function memoryJournal(events, options = {}) {
  let checkpoint = null;
  let acceptedFailures = options.acceptedFailures ?? 0;
  return {
    async load(id) {
      assert.equal(id, operationId);
      return clone(checkpoint);
    },
    async save(next, expectedRevision) {
      const call = next.calls.at(-1);
      events.push(`save:${call?.operation ?? "none"}:${call?.status ?? next.status}`);
      assert.equal(expectedRevision, checkpoint?.revision ?? null);
      if (
        acceptedFailures > 0 &&
        call?.status === "accepted" &&
        (!options.failOperation || call.operation === options.failOperation)
      ) {
        acceptedFailures -= 1;
        throw new Error("checkpoint write failed");
      }
      checkpoint = clone(next);
    },
    current() {
      return clone(checkpoint);
    },
    tamper(update) {
      checkpoint = update(clone(checkpoint));
    },
  };
}

function fakeClient(events, options = {}) {
  let validationCalls = 0;
  return {
    environment: "test",
    async createDraft({ organizationNumber }) {
      events.push(`transport:create:${organizationNumber}`);
      return {
        instance: { ownerPartyId: "500700", instanceGuid },
        organizationNumber,
        currentTask: { elementId: "Task_1", altinnTaskType: "data" },
        dataElements: [
          { id: mainFormId, instanceGuid, dataType: "Hovedskjema", contentType: "application/xml", filename: null },
          { id: accountsFormId, instanceGuid, dataType: "Underskjema", contentType: "application/xml", filename: null },
        ],
      };
    },
    async replaceXmlDataElement({ dataElementId, xml }) {
      events.push(`transport:upload:${dataElementId}:${xml.includes("accounts") ? "accounts" : "main"}`);
      return {
        id: dataElementId,
        instanceGuid,
        dataType: dataElementId === mainFormId ? "Hovedskjema" : "Underskjema",
        contentType: "application/xml",
        filename: null,
      };
    },
    async validateDraft() {
      validationCalls += 1;
      events.push(`transport:validate:${validationCalls}`);
      if (options.validationErrorAt === validationCalls) {
        throw new AnnualAccountsAltinnError(
          "annual_accounts_altinn_transport_timeout",
          "Annual-accounts validation timed out.",
          { retryable: true },
        );
      }
      return options.validation ?? { valid: true, issues: [] };
    },
    async lockForPersonalSignature() {
      events.push("transport:lock");
      return {
        state: "awaiting-person-signature",
        currentTask: { elementId: "Task_2", altinnTaskType: "signing" },
      };
    },
  };
}

test("journals create, both XML replacements, validation, and lock before and after transport", async () => {
  const events = [];
  const journal = memoryJournal(events);
  const client = fakeClient(events);

  for (let step = 0; step < 4; step += 1) {
    const result = await runNextAnnualAccountsStep({ documents, client, journal });
    assert.equal(result.complete, false);
  }
  const result = await runNextAnnualAccountsStep({ documents, client, journal });

  assert.equal(result.complete, true);
  assert.equal(result.blocked, false);
  assert.equal(result.nextOperation, null);
  assert.equal(result.checkpoint.status, "awaiting-person-signature");
  assert.deepEqual(result.checkpoint.instance, { ownerPartyId: "500700", instanceGuid });
  assert.deepEqual(result.checkpoint.dataElements, { mainFormId, accountsFormId });
  assert.deepEqual(
    result.checkpoint.calls.map(({ operation, status }) => ({ operation, status })),
    [
      { operation: "create-draft", status: "accepted" },
      { operation: "upload-main-form", status: "accepted" },
      { operation: "upload-accounts-form", status: "accepted" },
      { operation: "validate", status: "accepted" },
      { operation: "lock-for-signature", status: "accepted" },
    ],
  );
  assert.deepEqual(result.checkpoint.validation, {
    valid: true,
    errorCodes: [],
    warningCodes: [],
  });
  assert.equal(events.filter((event) => event === "transport:lock").length, 1);
  assert.equal(events.filter((event) => event.startsWith("transport:validate")).length, 2);
  assert.ok(events.indexOf("save:create-draft:sent") < events.indexOf("transport:create:310279617"));
  assert.ok(events.indexOf("save:lock-for-signature:sent") < events.indexOf("transport:lock"));
  assert.doesNotMatch(JSON.stringify(result.checkpoint), /<melding>|token|assertion/iu);
});

test("inspection is read-only and reports the next operation", async () => {
  const events = [];
  const journal = memoryJournal(events);
  const client = fakeClient(events);

  assert.deepEqual(await inspectAnnualAccountsProgress({ documents, journal }), {
    checkpoint: null,
    nextOperation: "create-draft",
    complete: false,
    blocked: false,
  });
  await runNextAnnualAccountsStep({ documents, client, journal });
  const eventCount = events.length;
  const progress = await inspectAnnualAccountsProgress({ documents, journal });

  assert.equal(progress.nextOperation, "upload-main-form");
  assert.equal(progress.complete, false);
  assert.equal(progress.blocked, false);
  assert.equal(events.length, eventCount);
});

test("blocks an uncertain create outcome instead of creating a second Altinn instance", async () => {
  const events = [];
  const journal = memoryJournal(events, { acceptedFailures: 1, failOperation: "create-draft" });
  const client = fakeClient(events);

  await assert.rejects(runNextAnnualAccountsStep({ documents, client, journal }), /checkpoint write failed/u);
  assert.equal(journal.current().calls[0].status, "sent");
  const result = await runNextAnnualAccountsStep({ documents, client, journal });

  assert.equal(result.blocked, true);
  assert.equal(result.nextOperation, null);
  assert.equal(result.checkpoint.failureCode, "annual_accounts_create_outcome_unknown");
  assert.equal(events.filter((event) => event.startsWith("transport:create")).length, 1);
});

test("retries an uncertain fixed-ID XML replacement but preserves document identity", async () => {
  const events = [];
  const journal = memoryJournal(events, { acceptedFailures: 1, failOperation: "upload-main-form" });
  const client = fakeClient(events);

  await runNextAnnualAccountsStep({ documents, client, journal });
  await assert.rejects(runNextAnnualAccountsStep({ documents, client, journal }), /checkpoint write failed/u);
  assert.equal(journal.current().calls.at(-1).status, "sent");
  const result = await runNextAnnualAccountsStep({ documents, client, journal });

  assert.equal(result.checkpoint.calls.at(-1).status, "accepted");
  const uploads = events.filter((event) => event.startsWith("transport:upload"));
  assert.deepEqual(uploads, [
    `transport:upload:${mainFormId}:main`,
    `transport:upload:${mainFormId}:main`,
  ]);
});

test("blocks invalid provider validation and never reaches the signing transition", async () => {
  const events = [];
  const journal = memoryJournal(events);
  const client = fakeClient(events, {
    validation: {
      valid: false,
      issues: [
        { severity: "Error", code: "Required", field: "sensitive.provider.path" },
        { severity: "Warning", code: "Review" },
      ],
    },
  });

  for (let step = 0; step < 4; step += 1) {
    await runNextAnnualAccountsStep({ documents, client, journal });
  }
  const checkpoint = journal.current();

  assert.equal(checkpoint.status, "failed-blocked");
  assert.equal(checkpoint.failureCode, "annual_accounts_validation_failed");
  assert.deepEqual(checkpoint.validation, {
    valid: false,
    errorCodes: ["Required"],
    warningCodes: ["Review"],
  });
  assert.doesNotMatch(JSON.stringify(checkpoint), /sensitive\.provider\.path/u);
  assert.equal(events.includes("transport:lock"), false);
});

test("journals and safely retries a lock preflight validation timeout before the lock is sent", async () => {
  const events = [];
  const journal = memoryJournal(events);
  const client = fakeClient(events, { validationErrorAt: 2 });

  for (let step = 0; step < 4; step += 1) {
    await runNextAnnualAccountsStep({ documents, client, journal });
  }
  const timedOut = await runNextAnnualAccountsStep({ documents, client, journal });
  assert.equal(timedOut.complete, false);
  assert.equal(timedOut.blocked, false);
  assert.equal(timedOut.checkpoint.status, "failed-retryable");
  assert.equal(timedOut.checkpoint.calls.at(-1).status, "failed-retryable");
  assert.equal(events.includes("transport:lock"), false);

  const recovered = await runNextAnnualAccountsStep({ documents, client, journal });
  assert.equal(recovered.complete, true);
  assert.equal(events.filter((event) => event === "transport:lock").length, 1);
});

test("blocks uncertain lock outcomes, document drift, and tampered checkpoints", async () => {
  const events = [];
  const journal = memoryJournal(events, { acceptedFailures: 1, failOperation: "lock-for-signature" });
  const client = fakeClient(events);

  for (let step = 0; step < 4; step += 1) {
    await runNextAnnualAccountsStep({ documents, client, journal });
  }
  await assert.rejects(runNextAnnualAccountsStep({ documents, client, journal }), /checkpoint write failed/u);
  const blocked = await runNextAnnualAccountsStep({ documents, client, journal });
  assert.equal(blocked.blocked, true);
  assert.equal(blocked.nextOperation, null);
  assert.equal(blocked.checkpoint.failureCode, "annual_accounts_lock_outcome_unknown");
  assert.equal(events.filter((event) => event === "transport:lock").length, 1);

  await assert.rejects(
    inspectAnnualAccountsProgress({
      documents: { ...documents, accountsFormXml: "<melding><changed /></melding>" },
      journal,
    }),
    (error) => error instanceof AnnualAccountsOrchestrationError && error.code === "annual_accounts_payload_changed",
  );

  journal.tamper((checkpoint) => ({ ...checkpoint, organizationNumber: "930835978" }));
  await assert.rejects(
    inspectAnnualAccountsProgress({ documents, journal }),
    (error) => error instanceof AnnualAccountsOrchestrationError && error.code === "annual_accounts_checkpoint_invalid",
  );
});
