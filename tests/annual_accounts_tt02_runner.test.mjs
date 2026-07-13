import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { chmod, mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  AnnualAccountsTt02RunnerError,
  loadPrivateAnnualAccountsTt02Input,
  runAnnualAccountsTt02Step,
  validateAnnualAccountsTt02Target,
  verifyAnnualAccountsTt02SignedInstance,
} from "../app/lib/annual-accounts-tt02-runner.ts";

const operationId = "12345678-1234-4234-9234-123456789abc";
const instanceGuid = "232c5390-9479-4506-a266-9890d7287bfb";
const mainFormId = "ce8665c1-01c3-49f7-960f-196b250a2266";
const accountsFormId = "0445d618-28b8-4af5-95e0-c8c989487e7a";
const signatureId = "7b8b2632-5b85-4d31-86cc-0c8766e4e079";
const annualAccounts = {
  organization: {
    number: "310279617",
    name: "LOGISK ØDE TIGER AS",
    form: "AS",
    contactEmail: "post@example.no",
  },
  incomeYear: 2025,
  adoption: { date: "2026-06-15", confirmingRepresentative: "Viktig Rosin" },
  declarations: {
    isSmallEnterprise: true,
    isParentCompany: false,
    usesIfrs: false,
    auditRequired: false,
    preparedByAuthorizedAccountant: false,
    externalAuthorizedAccountantAssistance: false,
  },
  current: {
    operatingCosts: 1_490,
    financialIncome: 100_000,
    financialCosts: 0,
    resultBeforeTax: 98_510,
    annualResult: 98_510,
    investmentSharesAndUnits: 30_000,
    bank: 128_510,
    totalAssets: 158_510,
    paidInEquity: 30_000,
    retainedEquity: 128_510,
    totalEquity: 158_510,
    shortTermDebt: 0,
    totalDebt: 0,
    totalEquityAndDebt: 158_510,
  },
  prior: {
    operatingCosts: 0,
    financialIncome: 0,
    financialCosts: 0,
    resultBeforeTax: 0,
    annualResult: 0,
    investmentSharesAndUnits: 30_000,
    bank: 0,
    totalAssets: 30_000,
    paidInEquity: 30_000,
    retainedEquity: 0,
    totalEquity: 30_000,
    shortTermDebt: 0,
    totalDebt: 0,
    totalEquityAndDebt: 30_000,
  },
  annualFullTimeEquivalents: 0,
  investmentDescription: "Aksjer og andeler",
  retainedEquityDescription: "Annen egenkapital",
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

function memoryCompletionStore() {
  let saved = null;
  return {
    async load() {
      return saved === null ? null : structuredClone(saved);
    },
    async save(evidence) {
      saved = structuredClone(evidence);
      return { evidenceSha256: "c".repeat(64), alreadyStored: false };
    },
  };
}

async function privateInputFixture(overrides = {}) {
  const parent = await mkdtemp(path.join(os.tmpdir(), "annual-accounts-tt02-input-"));
  const directory = path.join(parent, "private");
  await mkdir(directory, { mode: 0o700 });
  const filePath = path.join(directory, "input.json");
  await writeFile(
    filePath,
    JSON.stringify({ operationId, annualAccounts, ...overrides }),
    { mode: 0o600 },
  );
  return { parent, directory, filePath };
}

test("loads a private annual-accounts input and exposes only a bounded hash summary", async () => {
  const { filePath } = await privateInputFixture();
  const loaded = await loadPrivateAnnualAccountsTt02Input(filePath);

  assert.equal(loaded.documents.operationId, operationId);
  assert.equal(loaded.documents.organizationNumber, "310279617");
  assert.match(loaded.documents.mainFormXml, /dataFormatId="1266"/u);
  assert.deepEqual(Object.keys(loaded.summary).sort(), [
    "accountsFormHash",
    "application",
    "incomeYear",
    "mainFormHash",
    "operationId",
    "organizationNumber",
  ]);
  assert.match(loaded.summary.mainFormHash, /^[a-f0-9]{64}$/u);
  assert.doesNotMatch(JSON.stringify(loaded.summary), /<melding>|post@example/u);
});

test("rejects permissive, symlinked, malformed, and over-specified operator inputs", async () => {
  const permissive = await privateInputFixture();
  await chmod(permissive.filePath, 0o644);
  await assert.rejects(loadPrivateAnnualAccountsTt02Input(permissive.filePath), /private/u);

  const good = await privateInputFixture();
  const symlinkPath = path.join(good.directory, "linked.json");
  await symlink(good.filePath, symlinkPath);
  await assert.rejects(loadPrivateAnnualAccountsTt02Input(symlinkPath), /regular file/u);

  const extra = await privateInputFixture({ privateKey: "must-not-be-accepted" });
  await assert.rejects(
    loadPrivateAnnualAccountsTt02Input(extra.filePath),
    (error) =>
      error instanceof AnnualAccountsTt02RunnerError &&
      error.code === "annual_accounts_tt02_input_invalid",
  );
});

test("validates the approved customer and year before token issuance", async () => {
  const { filePath } = await privateInputFixture();
  const loaded = await loadPrivateAnnualAccountsTt02Input(filePath);

  assert.deepEqual(validateAnnualAccountsTt02Target(loaded, "310279617", 2025), loaded.summary);
  for (const [organizationNumber, incomeYear] of [
    ["930835978", 2025],
    ["310279617", 2024],
  ]) {
    assert.throws(
      () => validateAnnualAccountsTt02Target(loaded, organizationNumber, incomeYear),
      (error) =>
        error instanceof AnnualAccountsTt02RunnerError &&
        error.code === "annual_accounts_tt02_target_mismatch",
    );
  }
});

test("issues only the annual instance scopes and advances exactly one guarded TT02 step", async () => {
  const { filePath } = await privateInputFixture();
  const loaded = await loadPrivateAnnualAccountsTt02Input(filePath);
  const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
  let grantPayload;
  const tokenFetchImplementation = async (_url, init) => {
    const assertion = new URLSearchParams(init.body).get("assertion");
    grantPayload = JSON.parse(Buffer.from(assertion.split(".")[1], "base64url").toString("utf8"));
    return new Response(
      JSON.stringify({
        access_token: "short-lived-maskinporten-token",
        token_type: "Bearer",
        expires_in: 120,
        scope: "altinn:instances.read altinn:instances.write",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  const responses = [
    {
      status: 200,
      headers: { "content-type": "text/plain" },
      body: new TextEncoder().encode("short-lived-altinn-token"),
    },
    {
      status: 201,
      headers: { "content-type": "application/json" },
      body: new TextEncoder().encode(JSON.stringify({
        id: `500700/${instanceGuid}`,
        instanceOwner: { partyId: "500700", organisationNumber: "310279617" },
        process: { currentTask: { elementId: "Task_1", altinnTaskType: "data" }, ended: null },
        data: [
          { id: mainFormId, instanceGuid, dataType: "Hovedskjema", contentType: "application/xml", filename: null },
          { id: accountsFormId, instanceGuid, dataType: "Underskjema", contentType: "application/xml", filename: null },
        ],
      })),
    },
  ];
  const output = await runAnnualAccountsTt02Step({
    loaded,
    journal: memoryJournal(),
    clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
    keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
    customerOrgNumber: "310279617",
    incomeYear: 2025,
    privateKeyPem,
    tokenFetchImplementation,
    altinnTransport: async () => responses.shift(),
  });

  assert.equal(grantPayload.scope, "altinn:instances.read altinn:instances.write");
  assert.equal(output.before.nextOperation, "create-draft");
  assert.equal(output.result.checkpoint.calls.length, 1);
  assert.equal(output.result.checkpoint.calls[0].operation, "create-draft");
  assert.doesNotMatch(
    JSON.stringify(output),
    /short-lived|BEGIN PRIVATE KEY|<melding>|post@example/iu,
  );
});

test("requires a separate flag before the lock-for-signature transition", async () => {
  const { filePath } = await privateInputFixture();
  const loaded = await loadPrivateAnnualAccountsTt02Input(filePath);
  const journal = memoryJournal();

  // Build a valid checkpoint through the real orchestration with an in-memory client.
  const client = {
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
      return { id: dataElementId, instanceGuid, dataType: "Hovedskjema", contentType: "application/xml", filename: null };
    },
    async validateDraft() {
      return { valid: true, issues: [] };
    },
    async lockForPersonalSignature() {
      throw new Error("must not lock");
    },
  };
  const { runNextAnnualAccountsStep } = await import("../app/lib/annual-accounts-orchestration.ts");
  for (let step = 0; step < 4; step += 1) {
    await runNextAnnualAccountsStep({ documents: loaded.documents, client, journal });
  }
  await assert.rejects(
    runAnnualAccountsTt02Step({
      loaded,
      journal,
      clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
      keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
      customerOrgNumber: "310279617",
      incomeYear: 2025,
      privateKeyPem: "not-opened-before-lock-check",
    }),
    (error) =>
      error instanceof AnnualAccountsTt02RunnerError &&
      error.code === "annual_accounts_tt02_lock_confirmation_required",
  );
});

async function lockedJournal(loaded) {
  const journal = memoryJournal();
  const client = {
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
  const { runNextAnnualAccountsStep } = await import("../app/lib/annual-accounts-orchestration.ts");
  for (let step = 0; step < 5; step += 1) {
    await runNextAnnualAccountsStep({ documents: loaded.documents, client, journal });
  }
  return journal;
}

test("verifies a personally completed instance with read scope only", async () => {
  const { filePath } = await privateInputFixture();
  const loaded = await loadPrivateAnnualAccountsTt02Input(filePath);
  const journal = await lockedJournal(loaded);
  const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
  let grantPayload;
  const tokenFetchImplementation = async (_url, init) => {
    const assertion = new URLSearchParams(init.body).get("assertion");
    grantPayload = JSON.parse(Buffer.from(assertion.split(".")[1], "base64url").toString("utf8"));
    return new Response(
      JSON.stringify({
        access_token: "short-lived-maskinporten-token",
        token_type: "Bearer",
        expires_in: 120,
        scope: "altinn:instances.read",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  const requests = [];
  const responses = [
    {
      status: 200,
      headers: { "content-type": "text/plain" },
      body: new TextEncoder().encode("short-lived-altinn-token"),
    },
    {
      status: 200,
      headers: { "content-type": "application/json" },
      body: new TextEncoder().encode(JSON.stringify({
        id: `500700/${instanceGuid}`,
        instanceOwner: { partyId: "500700", organisationNumber: "310279617" },
        process: { currentTask: null, ended: "2026-07-13T12:42:31.123Z" },
        data: [
          { id: mainFormId, instanceGuid, dataType: "Hovedskjema", contentType: "application/xml", filename: null },
          { id: accountsFormId, instanceGuid, dataType: "Underskjema", contentType: "application/xml", filename: null },
          { id: signatureId, instanceGuid, dataType: "signature", contentType: "application/json", filename: "signature.json" },
        ],
      })),
    },
  ];

  const output = await verifyAnnualAccountsTt02SignedInstance({
    loaded,
    journal,
    completionStore: memoryCompletionStore(),
    clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
    keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
    customerOrgNumber: "310279617",
    incomeYear: 2025,
    privateKeyPem,
    tokenFetchImplementation,
    altinnTransport: async (request) => {
      requests.push(request);
      return responses.shift();
    },
  });

  assert.equal(grantPayload.scope, "altinn:instances.read");
  assert.equal(output.summary.organizationNumber, "310279617");
  assert.equal(output.evidence.signatureDataElementId, signatureId);
  assert.deepEqual(output.stored, { evidenceSha256: "c".repeat(64), alreadyStored: false });
  assert.equal(requests[1].method, "GET");
  assert.match(requests[1].url, new RegExp(`/instances/500700/${instanceGuid}$`, "u"));
  assert.doesNotMatch(JSON.stringify(output), /short-lived|BEGIN PRIVATE KEY|<melding>|post@example/iu);
});

test("checks the locked checkpoint before issuing a post-signature read token", async () => {
  const { filePath } = await privateInputFixture();
  const loaded = await loadPrivateAnnualAccountsTt02Input(filePath);
  let tokenCalls = 0;
  await assert.rejects(
    verifyAnnualAccountsTt02SignedInstance({
      loaded,
      journal: memoryJournal(),
      completionStore: memoryCompletionStore(),
      clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
      keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
      customerOrgNumber: "310279617",
      incomeYear: 2025,
      privateKeyPem: "not-opened-before-checkpoint-check",
      tokenFetchImplementation: async () => {
        tokenCalls += 1;
        throw new Error("must not issue token");
      },
    }),
    /locked for personal signing/u,
  );
  assert.equal(tokenCalls, 0);
});
