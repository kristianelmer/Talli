import assert from "node:assert/strict";
import test from "node:test";

import {
  Rf1086AuthorityError,
  createRf1086AuthorityClient,
} from "../app/lib/rf1086-authority-client.ts";
import {
  Rf1086AuthorityOrchestrationError,
  runNextRf1086AuthorityStep,
} from "../app/lib/rf1086-authority-orchestration.ts";

const hovedskjemaId = "0193de1a-d956-739e-980e-ab57ae7de73c";
const dialogId = "0193d51a-ec30-7d58-b727-6ce65964d3d4";
const forsendelseId = "0193de1b-0483-740a-9e0b-f60a2d519638";

const preview = {
  id: "12345678-1234-4234-9234-123456789abc",
  company_id: "company-id",
  setup_id: "setup-id",
  income_year: 2025,
  filing: "aksjonærregisteroppgaven",
  status: "ready",
  issues: [],
  preview: "RF-1086 preview",
  hovedskjema_xml: "<Hovedskjema />",
  underskjema_xml: {
    shareholder_b: "<Underskjema id=\"b\" />",
    shareholder_a: "<Underskjema id=\"a\" />",
  },
  source: "python_rf1086_engine",
  created_at: "2026-01-01T00:00:00Z",
};

function jsonResponse(value, status = 200) {
  return {
    status,
    headers: { "content-type": "application/json" },
    body: new TextEncoder().encode(JSON.stringify(value)),
  };
}

function clone(value) {
  return value === null ? null : structuredClone(value);
}

function memoryJournal(events, options = {}) {
  let checkpoint = null;
  let acceptedWriteFailures = options.acceptedWriteFailures ?? 0;
  return {
    async load(previewId) {
      assert.equal(previewId, preview.id);
      return clone(checkpoint);
    },
    async save(next, expectedRevision) {
      const call = next.calls.at(-1);
      events.push(`save:${call?.operation ?? "none"}:${call?.status ?? next.status}`);
      assert.equal(expectedRevision, checkpoint?.revision ?? null);
      if (
        call?.status === "accepted" &&
        acceptedWriteFailures > 0 &&
        (!options.failAcceptedOperation || options.failAcceptedOperation === call.operation)
      ) {
        acceptedWriteFailures -= 1;
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

test("journals every prepared call before transport and every accepted response before advancing", async () => {
  const events = [];
  const responses = [
    jsonResponse({ hovedskjemaId }),
    { status: 200, headers: {}, body: new Uint8Array() },
    { status: 200, headers: {}, body: new Uint8Array() },
    jsonResponse({ oppgavegiversLeveranseReferanse: hovedskjemaId, dialogId, forsendelseId }),
  ];
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async (request) => {
      events.push(`transport:${request.url.split("/").at(-1)?.split("?")[0]}`);
      return responses.shift();
    },
  });
  const journal = memoryJournal(events);

  await runNextRf1086AuthorityStep({ preview, client, journal });
  await runNextRf1086AuthorityStep({ preview, client, journal });
  await runNextRf1086AuthorityStep({ preview, client, journal });
  const result = await runNextRf1086AuthorityStep({ preview, client, journal });

  assert.equal(result.complete, true);
  assert.equal(result.checkpoint.status, "confirmed");
  assert.equal(result.checkpoint.hovedskjemaId, hovedskjemaId);
  assert.deepEqual(result.checkpoint.confirmation, {
    oppgavegiversLeveranseReferanse: hovedskjemaId,
    dialogId,
    forsendelseId,
  });
  assert.deepEqual(
    result.checkpoint.calls.map(({ operation, status }) => ({ operation, status })),
    [
      { operation: "hovedskjema", status: "accepted" },
      { operation: "underskjema:shareholder_a", status: "accepted" },
      { operation: "underskjema:shareholder_b", status: "accepted" },
      { operation: "bekreft", status: "accepted" },
    ],
  );
  assert.deepEqual(events, [
    "save:hovedskjema:prepared",
    "save:hovedskjema:sent",
    "transport:1086H",
    "save:hovedskjema:accepted",
    "save:underskjema:shareholder_a:prepared",
    "save:underskjema:shareholder_a:sent",
    "transport:1086U",
    "save:underskjema:shareholder_a:accepted",
    "save:underskjema:shareholder_b:prepared",
    "save:underskjema:shareholder_b:sent",
    "transport:1086U",
    "save:underskjema:shareholder_b:accepted",
    "save:bekreft:prepared",
    "save:bekreft:sent",
    "transport:bekreft",
    "save:bekreft:accepted",
  ]);
  const idempotencyKeys = result.checkpoint.calls.flatMap((call) =>
    call.idempotencyKey ? [call.idempotencyKey] : [],
  );
  assert.equal(idempotencyKeys.length, 3);
  assert.equal(new Set(idempotencyKeys).size, 3);
  assert.ok(idempotencyKeys.every((value) => /^[0-9a-f-]{36}$/u.test(value)));
  assert.doesNotMatch(JSON.stringify(result.checkpoint), /short-lived-system-user-token/u);
});

test("retries a prepared XML call with the same idempotency key after accepted-state persistence fails", async () => {
  const events = [];
  const seenKeys = [];
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async (request) => {
      seenKeys.push(request.headers.idempotencyKey);
      return jsonResponse({ hovedskjemaId });
    },
  });
  const journal = memoryJournal(events, { acceptedWriteFailures: 1 });

  await assert.rejects(runNextRf1086AuthorityStep({ preview, client, journal }), /checkpoint write failed/);
  assert.equal(journal.current().calls[0].status, "sent");
  const retry = await runNextRf1086AuthorityStep({ preview, client, journal });

  assert.equal(retry.checkpoint.calls[0].status, "accepted");
  assert.deepEqual(seenKeys, [seenKeys[0], seenKeys[0]]);
});

test("does not repeat confirmation when its accepted response could not be persisted", async () => {
  const responses = [
    jsonResponse({ hovedskjemaId }),
    { status: 200, headers: {}, body: new Uint8Array() },
    { status: 200, headers: {}, body: new Uint8Array() },
    jsonResponse({ oppgavegiversLeveranseReferanse: hovedskjemaId, dialogId, forsendelseId }),
  ];
  let confirmationCalls = 0;
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async (request) => {
      if (request.url.includes("/bekreft?")) confirmationCalls += 1;
      return responses.shift();
    },
  });
  const journal = memoryJournal([], { acceptedWriteFailures: 1, failAcceptedOperation: "bekreft" });
  await runNextRf1086AuthorityStep({ preview, client, journal });
  await runNextRf1086AuthorityStep({ preview, client, journal });
  await runNextRf1086AuthorityStep({ preview, client, journal });

  await assert.rejects(runNextRf1086AuthorityStep({ preview, client, journal }), /checkpoint write failed/);
  assert.equal(journal.current().calls.at(-1).status, "sent");
  const blocked = await runNextRf1086AuthorityStep({ preview, client, journal });

  assert.equal(blocked.checkpoint.status, "failed_blocked");
  assert.equal(blocked.checkpoint.failureCode, "rf1086_confirm_outcome_unknown");
  assert.equal(confirmationCalls, 1);
});

test("blocks automatic confirmation retry when the non-idempotent outcome is unknown", async () => {
  const events = [];
  const responses = [
    jsonResponse({ hovedskjemaId }),
    { status: 200, headers: {}, body: new Uint8Array() },
    { status: 200, headers: {}, body: new Uint8Array() },
  ];
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async () => {
      const response = responses.shift();
      if (!response) {
        throw new Rf1086AuthorityError("rf1086_transport_timeout", "timed out", { retryable: true });
      }
      return response;
    },
  });
  const journal = memoryJournal(events);

  await runNextRf1086AuthorityStep({ preview, client, journal });
  await runNextRf1086AuthorityStep({ preview, client, journal });
  await runNextRf1086AuthorityStep({ preview, client, journal });
  const blocked = await runNextRf1086AuthorityStep({ preview, client, journal });

  assert.equal(blocked.complete, false);
  assert.equal(blocked.checkpoint.status, "failed_blocked");
  assert.equal(blocked.checkpoint.failureCode, "rf1086_confirm_outcome_unknown");
  await assert.rejects(
    runNextRf1086AuthorityStep({ preview, client, journal }),
    (error) =>
      error instanceof Rf1086AuthorityOrchestrationError && error.code === "rf1086_checkpoint_blocked",
  );
});

test("rejects environment and preview drift before making another authority call", async () => {
  let transports = 0;
  const testClient = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async () => {
      transports += 1;
      return jsonResponse({ hovedskjemaId });
    },
  });
  const journal = memoryJournal([]);
  await runNextRf1086AuthorityStep({ preview, client: testClient, journal });

  const productionClient = createRf1086AuthorityClient({
    environment: "production",
    accessToken: "short-lived-system-user-token",
    transport: async () => {
      transports += 1;
      return jsonResponse({ hovedskjemaId });
    },
  });
  await assert.rejects(
    runNextRf1086AuthorityStep({ preview, client: productionClient, journal }),
    (error) =>
      error instanceof Rf1086AuthorityOrchestrationError && error.code === "rf1086_environment_changed",
  );
  await assert.rejects(
    runNextRf1086AuthorityStep({
      preview: { ...preview, hovedskjema_xml: "<Changed />" },
      client: testClient,
      journal,
    }),
    (error) =>
      error instanceof Rf1086AuthorityOrchestrationError && error.code === "rf1086_preview_changed",
  );
  assert.equal(transports, 1);
});

test("rejects a tampered persisted operation before transport", async () => {
  let transports = 0;
  const client = createRf1086AuthorityClient({
    environment: "test",
    accessToken: "short-lived-system-user-token",
    transport: async () => {
      transports += 1;
      return jsonResponse({ hovedskjemaId });
    },
  });
  const journal = memoryJournal([]);
  await runNextRf1086AuthorityStep({ preview, client, journal });
  journal.tamper((checkpoint) => {
    checkpoint.calls[0].operation = "underskjema:missing";
    checkpoint.calls[0].url = "https://attacker.invalid/collect";
    return checkpoint;
  });

  await assert.rejects(
    runNextRf1086AuthorityStep({ preview, client, journal }),
    (error) =>
      error instanceof Rf1086AuthorityOrchestrationError && error.code === "rf1086_checkpoint_invalid",
  );
  assert.equal(transports, 1);
});
