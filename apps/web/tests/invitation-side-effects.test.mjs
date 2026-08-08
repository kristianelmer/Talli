import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveInvitationSideEffectId,
  persistInvitationAudit,
} from "../app/lib/invitation-side-effects.ts";

const ACTOR_A = "00000000-0000-4000-8000-000000000001";
const ACTOR_B = "00000000-0000-4000-8000-000000000002";
const COMPANY_A = "10000000-0000-4000-8000-000000000001";
const COMPANY_B = "10000000-0000-4000-8000-000000000002";
const OPERATION_ID = "20000000-0000-4000-8000-000000000001";

function fakeDatabase() {
  const audits = new Map();
  const failNextAuditFor = new Set();

  return {
    audits,
    failNextAuditFor,
    forActor(actorId) {
      return {
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

test("two actors can reuse one operation id without losing audit evidence", async () => {
  const database = fakeDatabase();

  for (const command of ["created", "resent"]) {
    await persistInvitationAudit(database.forActor(ACTOR_A), audit(ACTOR_A, COMPANY_A, command));
    await persistInvitationAudit(database.forActor(ACTOR_B), audit(ACTOR_B, COMPANY_B, command));
  }

  assert.equal(database.audits.size, 4);
  assert.deepEqual(new Set([...database.audits.values()].map((row) => row.actor_id)), new Set([ACTOR_A, ACTOR_B]));
  assert.ok([...database.audits.values()].every((row) => row.message.includes(OPERATION_ID)));
});

test("same-actor retry reconciles exact rows and recovers an audit failure", async () => {
  const database = fakeDatabase();
  const store = database.forActor(ACTOR_A);
  const evidence = audit(ACTOR_A, COMPANY_A, "created");

  database.failNextAuditFor.add(ACTOR_A);
  await assert.rejects(persistInvitationAudit(store, evidence), /audit evidence/u);

  await persistInvitationAudit(store, evidence);
  await persistInvitationAudit(store, evidence);

  assert.equal(database.audits.size, 1);
});

test("foreign rows are not an oracle because actor-derived ids never trigger their lookup", async () => {
  const database = fakeDatabase();
  await persistInvitationAudit(database.forActor(ACTOR_B), audit(ACTOR_B, COMPANY_B, "created"));

  await persistInvitationAudit(database.forActor(ACTOR_A), audit(ACTOR_A, COMPANY_A, "created"));

  assert.equal(database.audits.size, 2);
});
