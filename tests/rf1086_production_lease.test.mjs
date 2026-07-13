import assert from "node:assert/strict";
import test from "node:test";

import {
  Rf1086ProductionLeaseError,
  withRf1086ProductionLease,
} from "../app/lib/rf1086-production-lease.ts";

const previewId = "12345678-1234-4234-9234-123456789abc";
const actorId = "22345678-1234-4234-9234-123456789abc";
const leaseId = "32345678-1234-4234-9234-123456789abc";

function memoryClient(options = {}) {
  const events = [];
  return {
    async rpc(name, parameters) {
      events.push({ name, parameters: structuredClone(parameters) });
      if (name === "acquire_rf1086_production_lease") {
        return options.acquireResult ?? { data: leaseId, error: null };
      }
      if (name === "release_rf1086_production_lease") {
        return options.releaseResult ?? { data: true, error: null };
      }
      throw new Error("unexpected RPC");
    },
    events() {
      return structuredClone(events);
    },
  };
}

test("holds one private production lease around the guarded operation", async () => {
  const client = memoryClient();
  const operationEvents = [];

  const result = await withRf1086ProductionLease({
    client,
    previewId,
    actorId,
    operation: async () => {
      operationEvents.push("authority-operation");
      assert.equal(client.events().length, 1);
      return { complete: false };
    },
  });

  assert.deepEqual(result, { complete: false });
  assert.deepEqual(operationEvents, ["authority-operation"]);
  assert.deepEqual(client.events(), [
    {
      name: "acquire_rf1086_production_lease",
      parameters: { p_preview_id: previewId, p_actor_id: actorId },
    },
    {
      name: "release_rf1086_production_lease",
      parameters: { p_preview_id: previewId, p_lease_id: leaseId },
    },
  ]);
  assert.doesNotMatch(JSON.stringify(result), new RegExp(leaseId, "u"));
});

test("fails closed on an active lease conflict before running the operation", async () => {
  const client = memoryClient({
    acquireResult: { data: null, error: { code: "PT409", message: "private database detail" } },
  });
  let operations = 0;

  await assert.rejects(
    withRf1086ProductionLease({
      client,
      previewId,
      actorId,
      operation: async () => {
        operations += 1;
      },
    }),
    (error) =>
      error instanceof Rf1086ProductionLeaseError &&
      error.code === "rf1086_production_lease_conflict" &&
      !error.message.includes("database"),
  );
  assert.equal(operations, 0);
  assert.equal(client.events().length, 1);
});

test("releases the lease after an operation failure without hiding that failure", async () => {
  const client = memoryClient();
  const operationError = new Error("guarded operation failed");

  await assert.rejects(
    withRf1086ProductionLease({
      client,
      previewId,
      actorId,
      operation: async () => {
        throw operationError;
      },
    }),
    (error) => error === operationError,
  );
  assert.deepEqual(client.events().map((event) => event.name), [
    "acquire_rf1086_production_lease",
    "release_rf1086_production_lease",
  ]);
});

test("preserves even an undefined thrown value while still releasing the lease", async () => {
  const client = memoryClient();
  let rejected = false;

  try {
    await withRf1086ProductionLease({
      client,
      previewId,
      actorId,
      operation: async () => {
        throw undefined;
      },
    });
  } catch (error) {
    rejected = true;
    assert.equal(error, undefined);
  }

  assert.equal(rejected, true);
  assert.deepEqual(client.events().map((event) => event.name), [
    "acquire_rf1086_production_lease",
    "release_rf1086_production_lease",
  ]);
});

test("reports a release failure only after a successful guarded operation", async () => {
  const client = memoryClient({
    releaseResult: { data: null, error: { code: "XX000", message: "private database detail" } },
  });

  await assert.rejects(
    withRf1086ProductionLease({
      client,
      previewId,
      actorId,
      operation: async () => "accepted",
    }),
    (error) =>
      error instanceof Rf1086ProductionLeaseError &&
      error.code === "rf1086_production_lease_release_failed" &&
      !error.message.includes("database"),
  );
});

test("rejects invalid lease input before calling the database", async () => {
  const client = memoryClient();

  await assert.rejects(
    withRf1086ProductionLease({
      client,
      previewId: "not-a-uuid",
      actorId,
      operation: async () => undefined,
    }),
    (error) =>
      error instanceof Rf1086ProductionLeaseError &&
      error.code === "rf1086_production_lease_input_invalid",
  );
  assert.equal(client.events().length, 0);
});
