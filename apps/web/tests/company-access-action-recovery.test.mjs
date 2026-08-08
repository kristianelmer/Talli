import assert from "node:assert/strict";
import test from "node:test";

import { createCompanyAccessActionWorkflow } from "../app/lib/company-access-action-workflow.ts";

const ACTOR_ID = "00000000-0000-4000-8000-000000000001";
const COMPANY_ID = "10000000-0000-4000-8000-000000000001";
const OPERATION_ID = "20000000-0000-4000-8000-000000000001";

function invitation(updatedAt = "2026-08-08T08:00:00Z") {
  return {
    id: "30000000-0000-4000-8000-000000000001",
    companyId: COMPANY_ID,
    invitedEmail: "reviewer@example.test",
    role: "reviewer",
    status: "pending",
    expiresAt: "2026-08-22T08:00:00Z",
    createdAt: "2026-08-08T08:00:00Z",
    updatedAt,
  };
}

function fakeRuntime(failurePoint) {
  const pending = new Map();
  const outbox = new Map();
  const audits = new Map();
  const commandCalls = [];
  let mutations = 0;
  let failed = false;

  const failOnce = (point) => {
    if (!failed && failurePoint === point) {
      failed = true;
      throw new Error(`injected ${point}`);
    }
  };
  const execute = async (command, result) => {
    commandCalls.push(structuredClone(command));
    if (!pending.has(command.operationId)) {
      mutations += 1;
      pending.set(command.operationId, structuredClone(result));
    }
    return structuredClone(pending.get(command.operationId));
  };
  const dependencies = {
    async create(command) {
      return execute(command, {
        operationId: command.operationId,
        commandName: "create_invitation",
        companyId: command.companyId,
        invitation: invitation(),
        deliveryToken: "create-token",
        deliverySubject: "Invite",
        deliveryBody: "Create body",
      });
    },
    async accept(command) {
      return execute(command, {
        operationId: command.operationId,
        commandName: "accept_invitation",
        companyId: COMPANY_ID,
        membership: { companyId: COMPANY_ID, userId: ACTOR_ID, role: "reviewer", state: "active", acceptedAt: "2026-08-08T08:00:00Z" },
      });
    },
    async revoke(command) {
      return execute(command, {
        operationId: command.operationId,
        commandName: "revoke_invitation",
        companyId: command.companyId,
        invitation: { ...invitation(), status: "revoked" },
      });
    },
    async resend(command) {
      return execute(command, {
        operationId: command.operationId,
        commandName: "resend_invitation",
        companyId: command.companyId,
        invitation: invitation("2026-08-08T09:00:00Z"),
        deliveryToken: "resend-token",
        deliverySubject: "Invite again",
        deliveryBody: "Resend body",
      });
    },
    async listPending(actorId) {
      if (actorId !== ACTOR_ID) throw new Error("continuation actor mismatch");
      return [...pending.values()].map((value) => structuredClone(value));
    },
    async persistAudit(row) {
      failOnce(`${row.commandName}:audit`);
      audits.set(`${row.actorId}:${row.operationId}:${row.commandName}`, structuredClone(row));
    },
    async complete(operationId) {
      const continuation = pending.get(operationId);
      if (continuation?.commandName === "create_invitation" || continuation?.commandName === "resend_invitation") {
        failOnce(`${continuation.commandName}:outbox`);
        outbox.set(`${ACTOR_ID}:${operationId}:${continuation.commandName}`, structuredClone(continuation));
      }
      pending.delete(operationId);
    },
  };
  return {
    workflow: createCompanyAccessActionWorkflow(dependencies),
    pending,
    outbox,
    audits,
    commandCalls,
    get mutations() { return mutations; },
  };
}

const commands = {
  create_invitation: { operationId: OPERATION_ID, companyId: COMPANY_ID, invitedEmail: "reviewer@example.test", role: "reviewer" },
  accept_invitation: { operationId: OPERATION_ID, token: "accept-token" },
  revoke_invitation: { operationId: OPERATION_ID, companyId: COMPANY_ID, invitationId: invitation().id, expectedUpdatedAt: invitation().updatedAt },
  resend_invitation: { operationId: OPERATION_ID, companyId: COMPANY_ID, invitationId: invitation().id, expectedUpdatedAt: invitation().updatedAt },
};

for (const failurePoint of [
  "create_invitation:outbox",
  "create_invitation:audit",
  "accept_invitation:audit",
  "revoke_invitation:audit",
  "resend_invitation:outbox",
  "resend_invitation:audit",
]) {
  test(`${failurePoint} remains reachable and recovery finishes without another command`, async () => {
    const runtime = fakeRuntime(failurePoint);
    const commandName = failurePoint.split(":")[0];

    await assert.rejects(
      runtime.workflow.execute(ACTOR_ID, commandName, commands[commandName]),
      /continuation pending/u,
    );
    assert.equal(runtime.mutations, 1);
    assert.equal(runtime.pending.size, 1);

    await runtime.workflow.recover(ACTOR_ID);

    assert.equal(runtime.mutations, 1, "recovery must not issue another business command");
    assert.equal(runtime.commandCalls.length, 1, "recovery must use the durable receipt continuation");
    assert.equal(runtime.commandCalls[0].operationId, OPERATION_ID);
    assert.equal(runtime.pending.size, 0);
    assert.equal(runtime.audits.size, 1);
    assert.equal(runtime.outbox.size, commandName === "create_invitation" || commandName === "resend_invitation" ? 1 : 0);
  });
}

test("recovery actor comes from the server context and cannot claim another actor's continuation", async () => {
  const runtime = fakeRuntime("accept_invitation:audit");
  await assert.rejects(
    runtime.workflow.execute(ACTOR_ID, "accept_invitation", commands.accept_invitation),
    /continuation pending/u,
  );

  await assert.rejects(
    runtime.workflow.recover("00000000-0000-4000-8000-000000000099"),
    /continuation actor mismatch/u,
  );
  assert.equal(runtime.pending.size, 1);
  assert.equal(runtime.audits.size, 0);
});

test("delivery persistence is owned by atomic completion, never by a browser outbox insert", async () => {
  let completed = false;
  const workflow = createCompanyAccessActionWorkflow({
    async create(command) {
      return {
        operationId: command.operationId,
        commandName: "create_invitation",
        companyId: command.companyId,
        invitation: invitation(),
        deliveryToken: "committed-token",
        deliverySubject: "Invite",
        deliveryBody: "Body",
      };
    },
    async accept() { throw new Error("unused"); },
    async revoke() { throw new Error("unused"); },
    async resend() { throw new Error("unused"); },
    async listPending() { return []; },
    async persistAudit() {},
    async complete() { completed = true; },
  });

  await workflow.execute(ACTOR_ID, "create_invitation", commands.create_invitation);
  assert.equal(completed, true);
});
