import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveInvitationSideEffectId,
  persistInvitationAudit,
  persistInvitationOutbox,
} from "../app/lib/invitation-side-effects.ts";

const ACTOR_A = "00000000-0000-4000-8000-000000000001";
const ACTOR_B = "00000000-0000-4000-8000-000000000002";
const COMPANY_A = "10000000-0000-4000-8000-000000000001";
const COMPANY_B = "10000000-0000-4000-8000-000000000002";
const OPERATION_ID = "20000000-0000-4000-8000-000000000001";

function fakeDatabase() {
  const outbox = new Map();
  const audits = new Map();
  const failNextAuditFor = new Set();

  return {
    outbox,
    audits,
    failNextAuditFor,
    forActor(actorId) {
      return {
        async insertOutbox(row) {
          if (outbox.has(row.id)) return { error: new Error("duplicate") };
          outbox.set(row.id, structuredClone(row));
          return { error: null };
        },
        async findOutbox(id) {
          const row = outbox.get(id);
          return {
            data: row?.created_by === actorId ? structuredClone(row) : null,
            error: null,
          };
        },
        async insertAudit(row) {
          if (failNextAuditFor.delete(actorId)) return { error: new Error("temporary") };
          if (audits.has(row.id)) return { error: new Error("duplicate") };
          audits.set(row.id, structuredClone(row));
          return { error: null };
        },
        async findAudit(id) {
          const row = audits.get(id);
          return {
            data: row?.actor_id === actorId ? structuredClone(row) : null,
            error: null,
          };
        },
      };
    },
  };
}

function createDelivery(actorId, companyId, command) {
  return {
    actorId,
    operationId: OPERATION_ID,
    purpose: `${command}:outbox`,
    companyId,
    recipientEmail: `${actorId === ACTOR_A ? "a" : "b"}@example.test`,
    template: "workspace_invitation",
    payload: { operationId: OPERATION_ID, invitationId: `${command}-${actorId}` },
  };
}

function audit(actorId, companyId, command) {
  return {
    actorId,
    operationId: OPERATION_ID,
    purpose: `${command}:audit`,
    companyId,
    category: "review",
    action: `reviewer_invitation_${command}`,
    message: `${command} completed.`,
  };
}

test("side-effect identity is deterministic, actor-scoped, and purpose-scoped", () => {
  const input = { actorId: ACTOR_A, operationId: OPERATION_ID, purpose: "create:outbox" };
  const first = deriveInvitationSideEffectId(input);

  assert.equal(first, deriveInvitationSideEffectId(input));
  assert.notEqual(first, deriveInvitationSideEffectId({ ...input, actorId: ACTOR_B }));
  assert.notEqual(first, deriveInvitationSideEffectId({ ...input, purpose: "create:audit" }));
  assert.match(first, /^[0-9a-f]{8}-[0-9a-f]{4}-8[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u);
});

test("two actors can reuse one operation id for create and resend without losing delivery or audit", async () => {
  const database = fakeDatabase();

  for (const command of ["created", "resent"]) {
    await persistInvitationOutbox(database.forActor(ACTOR_A), createDelivery(ACTOR_A, COMPANY_A, command));
    await persistInvitationAudit(database.forActor(ACTOR_A), audit(ACTOR_A, COMPANY_A, command));
    await persistInvitationOutbox(database.forActor(ACTOR_B), createDelivery(ACTOR_B, COMPANY_B, command));
    await persistInvitationAudit(database.forActor(ACTOR_B), audit(ACTOR_B, COMPANY_B, command));
  }

  assert.equal(database.outbox.size, 4);
  assert.equal(database.audits.size, 4);
  assert.deepEqual(new Set([...database.outbox.values()].map((row) => row.created_by)), new Set([ACTOR_A, ACTOR_B]));
  assert.deepEqual(new Set([...database.audits.values()].map((row) => row.actor_id)), new Set([ACTOR_A, ACTOR_B]));
  assert.ok([...database.outbox.values()].every((row) => row.payload.operationId === OPERATION_ID));
  assert.ok([...database.audits.values()].every((row) => row.message.includes(OPERATION_ID)));
});

test("same-actor retry reconciles exact rows and recovers an audit failure", async () => {
  const database = fakeDatabase();
  const store = database.forActor(ACTOR_A);
  const delivery = createDelivery(ACTOR_A, COMPANY_A, "created");
  const evidence = audit(ACTOR_A, COMPANY_A, "created");

  database.failNextAuditFor.add(ACTOR_A);
  await persistInvitationOutbox(store, delivery);
  await assert.rejects(persistInvitationAudit(store, evidence), /audit evidence/u);

  await persistInvitationOutbox(store, delivery);
  await persistInvitationAudit(store, evidence);
  await persistInvitationAudit(store, evidence);

  assert.equal(database.outbox.size, 1);
  assert.equal(database.audits.size, 1);
});

test("foreign rows are not an oracle because actor-derived ids never trigger their lookup", async () => {
  const database = fakeDatabase();
  await persistInvitationOutbox(database.forActor(ACTOR_B), createDelivery(ACTOR_B, COMPANY_B, "created"));
  await persistInvitationAudit(database.forActor(ACTOR_B), audit(ACTOR_B, COMPANY_B, "created"));

  await persistInvitationOutbox(database.forActor(ACTOR_A), createDelivery(ACTOR_A, COMPANY_A, "created"));
  await persistInvitationAudit(database.forActor(ACTOR_A), audit(ACTOR_A, COMPANY_A, "created"));

  assert.equal(database.outbox.size, 2);
  assert.equal(database.audits.size, 2);
});
