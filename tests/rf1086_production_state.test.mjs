import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import test from "node:test";

import {
  deriveRf1086ProductionState,
  loadRf1086ProductionState,
} from "../app/lib/rf1086-production-state.ts";
import { Rf1086ProductionRunnerError } from "../app/lib/rf1086-production-runner.ts";
import {
  runPersistedRf1086ProductionStep,
  runPersistedRf1086ProductionStepWithSystemUser,
} from "../app/lib/rf1086-production-service.ts";

const actorId = "12345678-1234-4234-9234-123456789abc";
const companyId = "22345678-1234-4234-9234-123456789abc";
const preview = {
  id: "32345678-1234-4234-9234-123456789abc",
  company_id: companyId,
  setup_id: "42345678-1234-4234-9234-123456789abc",
  income_year: 2025,
  filing: "aksjonærregisteroppgaven",
  status: "ready",
  issues: [],
  preview: "RF-1086 no-activity preview",
  hovedskjema_xml: "<melding />",
  underskjema_xml: { shareholder: "<melding />" },
  source: "python_rf1086_engine",
  created_at: "2026-07-13T18:00:00.000Z",
};

function readyInput(overrides = {}) {
  const company = {
    id: companyId,
    org_number: "310279617",
    name: "LOGISK ØDE TIGER AS",
    entity_type: "AS",
    address: "Klokkargarden 44",
    postal_code: "5200",
    city: "OS",
    status_text: "aktiv",
    source: "brreg",
    created_by: actorId,
    identity_confirmed_at: "2026-07-13T16:00:00.000Z",
    identity_locked_at: "2026-07-13T16:00:00.000Z",
    created_at: "2026-07-13T16:00:00.000Z",
  };
  const authorityPermissions = [{
    company_id: companyId,
    obligation: "aksjonaerregisteroppgaven",
    submitter_user_id: actorId,
    confirmed_by: actorId,
    confirmed_at: "2026-07-13T17:00:00.000Z",
    production_enabled: true,
  }];
  return {
    actorId,
    preview,
    company,
    membership: {
      company_id: companyId,
      user_id: actorId,
      role: "owner",
      accepted_at: "2026-07-13T17:00:00.000Z",
    },
    incomeYear: 2025,
    setups: [{
      id: preview.setup_id,
      company_id: companyId,
      income_year: 2025,
      bank_balance: 1_000_000,
      share_capital: 1_000_000,
      share_count: 500,
      nominal_value: 2_000,
      locked_at: "2026-07-13T17:00:00.000Z",
      created_by: actorId,
    }],
    ledgerEntries: [],
    holdingActions: [],
    bankTransactions: [],
    documents: [],
    overrides: [],
    locks: [{
      id: "52345678-1234-4234-9234-123456789abc",
      company_id: companyId,
      income_year: 2025,
      reason: "Annual close",
      locked_by: actorId,
      locked_at: "2026-07-13T17:00:00.000Z",
    }],
    annualData: {
      id: "62345678-1234-4234-9234-123456789abc",
      company_id: companyId,
      income_year: 2025,
      answers: {
        shares_owned_at_year_end: false,
        bought_or_sold_shares: false,
        received_dividends: false,
        declared_owner_dividends: false,
        shareholder_loans: false,
        paid_costs: false,
        bank_balance_confirmed: true,
        has_unpaid_items: false,
        general_meeting_approved: true,
        authority_to_submit_confirmed: true,
      },
      confirmations: ["bank_balance_confirmed", "authority_to_submit_confirmed", "no_activity_confirmed"],
      no_activity_confirmed: true,
      annual_full_time_equivalents: 0,
      completed_by: actorId,
      completed_at: "2026-07-13T17:00:00.000Z",
      updated_by: actorId,
      updated_at: "2026-07-13T17:00:00.000Z",
    },
    billingAccount: {
      company_id: companyId,
      pricing_plan: "founder",
      monthly_nok: 29,
      filing_package_nok: 299,
      founder_cohort_number: 1,
      subscription_active: true,
      filing_package_paid: true,
      supported_case: true,
      refund_eligible: false,
      no_charge_reason: null,
    },
    authorityPermissions,
    filingPreviews: [preview],
    filingSubmissions: [],
    authorityTestRuns: [{
      company_id: companyId,
      obligation: "aksjonaerregisteroppgaven",
      status: "accepted",
      receipt_reference: "tt02-receipt",
      archive_reference: "tt02-archive",
      recorded_at: "2026-07-13T17:00:00.000Z",
    }],
    stepUpContext: {
      actorId,
      mfaVerifiedAt: "2026-07-13T17:55:00.000Z",
      securityReviewApproved: true,
      productionCredentialsEnabled: true,
    },
    launchSignoffRows: [{
      key: "rf1086_authority",
      status: "approved",
      reviewer: "Independent reviewer",
      reviewed_at: "2026-07-13T17:30:00.000Z",
      evidence_link: "https://evidence.example/rf1086",
      decision: "Approved supported RF-1086 production scope.",
      recorded_by: actorId,
      updated_at: "2026-07-13T17:30:00.000Z",
    }],
    reviewComments: [],
    confirmations: { authorityConfirmed: true, previewConfirmed: true },
    now: new Date("2026-07-13T18:00:00.000Z"),
    ...overrides,
  };
}

test("derives a production release from current rows and normalizes launch signoffs", () => {
  const state = deriveRf1086ProductionState(readyInput());

  assert.equal(state.preview.id, preview.id);
  assert.equal(state.release.filingReady, true);
  assert.equal(state.release.hardReviewBlockCount, 0);
  assert.equal(state.release.blockingOverrideCount, 0);
  assert.deepEqual(state.release.launchSignoffs, [{
    key: "rf1086_authority",
    status: "approved",
    reviewer: "Independent reviewer",
    reviewedAt: "2026-07-13T17:30:00.000Z",
    evidenceLink: "https://evidence.example/rf1086",
    decision: "Approved supported RF-1086 production scope.",
  }]);
});

test("fresh unmatched bank data disables a release instead of trusting old readiness", () => {
  const input = readyInput();
  input.bankTransactions.push({
    id: "72345678-1234-4234-9234-123456789abc",
    company_id: companyId,
    income_year: 2025,
    transaction_date: "2025-12-31",
    text: "Unmatched",
    amount: 100,
    balance: null,
    source_hash: "source-hash",
    matched_entry_id: null,
    matched_action_id: null,
    accepted_warning: false,
    created_by: actorId,
    created_at: "2026-07-13T17:59:00.000Z",
  });

  const state = deriveRf1086ProductionState(input);

  assert.equal(state.release.filingReady, false);
});

test("open warnings, hard review comments, and blocking overrides remain production blockers", () => {
  const input = readyInput({ locks: [] });
  input.reviewComments.push({ preview_id: preview.id, severity: "hard_block" });
  input.overrides.push({
    id: "82345678-1234-4234-9234-123456789abc",
    preview_id: preview.id,
    company_id: companyId,
    income_year: 2025,
    filing: "aksjonærregisteroppgaven",
    field_target: "rf1086.shareholder",
    old_value: "",
    new_value: "unsupported",
    reason: "manual override",
    risk_level: "block",
    owner_confirmed_by: actorId,
    owner_confirmed_at: "2026-07-13T17:59:00.000Z",
    created_by: actorId,
    created_at: "2026-07-13T17:59:00.000Z",
  });

  const state = deriveRf1086ProductionState(input);

  assert.equal(state.release.filingReady, false);
  assert.equal(state.release.hardReviewBlockCount, 1);
  assert.equal(state.release.blockingOverrideCount, 1);
});

function rowsFor(input) {
  return {
    filing_previews: input.filingPreviews,
    company_memberships: [input.membership],
    companies: [input.company],
    opening_balance_setups: input.setups,
    ledger_entries: input.ledgerEntries,
    holding_actions: input.holdingActions,
    bank_transactions: input.bankTransactions,
    documents: input.documents,
    filing_overrides: input.overrides,
    period_locks: input.locks,
    annual_data: input.annualData ? [input.annualData] : [],
    billing_accounts: input.billingAccount ? [input.billingAccount] : [],
    authority_permissions: input.authorityPermissions,
    filing_submissions: input.filingSubmissions,
    authority_test_runs: input.authorityTestRuns,
    step_up_events: [{ actor_id: actorId, mfa_verified_at: input.stepUpContext.mfaVerifiedAt }],
    production_security_grants: [{
      actor_id: actorId,
      security_review_approved: input.stepUpContext.securityReviewApproved,
      production_credentials_enabled: input.stepUpContext.productionCredentialsEnabled,
      expires_at: "2026-07-14T18:00:00.000Z",
      revoked_at: null,
    }],
    launch_signoffs: input.launchSignoffRows,
    filing_review_comments: input.reviewComments,
    filing_readiness_snapshots: [{
      company_id: companyId,
      income_year: 2025,
      obligation: "aksjonaerregisteroppgaven",
      ready: true,
      status: "ready",
    }],
  };
}

function memorySupabase(seed, errors = {}, operationEvents = []) {
  const tables = [];
  const auditRows = [];
  let checkpointRow = null;
  let activeLeaseId = null;
  class Query {
    constructor(table) {
      this.table = table;
      this.filters = [];
      this.limitCount = null;
    }
    select() {
      return this;
    }
    eq(column, value) {
      this.filters.push([column, value]);
      return this;
    }
    order() {
      return this;
    }
    limit(value) {
      this.limitCount = value;
      return this;
    }
    result(single) {
      if (errors[this.table]) return { data: null, error: errors[this.table] };
      let data = (seed[this.table] ?? []).filter((row) =>
        this.filters.every(([column, value]) => row?.[column] === value),
      );
      if (this.limitCount !== null) data = data.slice(0, this.limitCount);
      return { data: structuredClone(single ? (data[0] ?? null) : data), error: null };
    }
    maybeSingle() {
      if (this.table === "rf1086_authority_checkpoints") {
        return Promise.resolve({ data: structuredClone(checkpointRow), error: errors[this.table] ?? null });
      }
      return Promise.resolve(this.result(true));
    }
    insert(value) {
      operationEvents.push(`insert:${this.table}`);
      if (this.table === "audit_events" && !errors[this.table]) {
        auditRows.push(structuredClone(value));
      }
      return Promise.resolve({ data: null, error: errors[this.table] ?? null });
    }
    then(resolve, reject) {
      return Promise.resolve(this.result(false)).then(resolve, reject);
    }
  }
  return {
    from(table) {
      tables.push(table);
      return new Query(table);
    },
    async rpc(name, parameters) {
      operationEvents.push(`rpc:${name}`);
      if (name === "acquire_rf1086_production_lease") {
        assert.equal(parameters.p_preview_id, preview.id);
        assert.equal(parameters.p_actor_id, actorId);
        if (activeLeaseId) return { data: null, error: { code: "PT409" } };
        activeLeaseId = "a2345678-1234-4234-9234-123456789abc";
        return { data: activeLeaseId, error: null };
      }
      if (name === "release_rf1086_production_lease") {
        assert.equal(parameters.p_preview_id, preview.id);
        assert.equal(parameters.p_lease_id, activeLeaseId);
        activeLeaseId = null;
        return { data: true, error: null };
      }
      assert.equal(name, "save_rf1086_authority_checkpoint");
      const currentRevision = checkpointRow?.revision ?? null;
      if (currentRevision !== parameters.p_expected_revision) {
        return { data: null, error: { code: "PT409" } };
      }
      checkpointRow = {
        preview_id: preview.id,
        company_id: companyId,
        income_year: 2025,
        revision: parameters.p_checkpoint.revision,
        checkpoint: structuredClone(parameters.p_checkpoint),
      };
      return { data: checkpointRow.revision, error: null };
    },
    tables() {
      return [...tables];
    },
    auditRows() {
      return structuredClone(auditRows);
    },
  };
}

function splitClients(databaseClient) {
  return {
    workspaceClient: databaseClient,
    controlClient: databaseClient,
    journalClient: databaseClient,
  };
}

test("loads fresh release state only after accepted owner membership", async () => {
  const input = readyInput();
  input.bankTransactions.push({
    id: "92345678-1234-4234-9234-123456789abc",
    company_id: companyId,
    income_year: 2025,
    transaction_date: "2025-12-31",
    text: "Fresh unmatched transaction",
    amount: 100,
    balance: null,
    source_hash: "fresh-source-hash",
    matched_entry_id: null,
    matched_action_id: null,
    accepted_warning: false,
    created_by: actorId,
    created_at: "2026-07-13T17:59:00.000Z",
  });
  const databaseClient = memorySupabase(rowsFor(input));

  const state = await loadRf1086ProductionState({
    ...splitClients(databaseClient),
    actorId,
    previewId: preview.id,
    confirmations: input.confirmations,
    now: input.now,
  });

  assert.equal(state.release.filingReady, false);
  assert.deepEqual(databaseClient.tables().slice(0, 2), ["filing_previews", "company_memberships"]);
  assert.equal(databaseClient.tables().includes("filing_readiness_snapshots"), false);
});

test("keeps tenant reads on the owner client and global signoff reads on the control client", async () => {
  const input = readyInput();
  const workspaceClient = memorySupabase(rowsFor(input));
  const controlClient = memorySupabase({ launch_signoffs: input.launchSignoffRows });

  const state = await loadRf1086ProductionState({
    workspaceClient,
    controlClient,
    actorId,
    previewId: preview.id,
    confirmations: input.confirmations,
    now: input.now,
  });

  assert.equal(state.release.launchSignoffs.length, 1);
  assert.equal(workspaceClient.tables().includes("launch_signoffs"), false);
  assert.deepEqual(controlClient.tables(), ["launch_signoffs"]);
});

test("rejects a non-owner before reading tenant accounting state", async () => {
  const input = readyInput({ membership: { ...readyInput().membership, role: "reviewer" } });
  const databaseClient = memorySupabase(rowsFor(input));

  await assert.rejects(
    loadRf1086ProductionState({
      ...splitClients(databaseClient),
      actorId,
      previewId: preview.id,
      confirmations: input.confirmations,
      now: input.now,
    }),
    (error) =>
      error instanceof Rf1086ProductionRunnerError &&
      error.code === "rf1086_production_owner_required",
  );
  assert.deepEqual(databaseClient.tables(), ["filing_previews", "company_memberships"]);
});

test("maps database failures without reflecting provider diagnostics", async () => {
  const input = readyInput();
  const databaseClient = memorySupabase(rowsFor(input), {
    companies: { message: "postgres password and internal host must remain private" },
  });

  await assert.rejects(
    loadRf1086ProductionState({
      ...splitClients(databaseClient),
      actorId,
      previewId: preview.id,
      confirmations: input.confirmations,
      now: input.now,
    }),
    (error) =>
      error instanceof Rf1086ProductionRunnerError &&
      error.code === "rf1086_production_state_load_failed" &&
      !error.message.includes("postgres") &&
      !error.message.includes("password") &&
      !error.message.includes("host"),
  );
});

function jsonResponse(value) {
  return {
    status: 200,
    headers: { "content-type": "application/json" },
    body: new TextEncoder().encode(JSON.stringify(value)),
  };
}

test("audits an authoritative release before making one production transport call", async () => {
  const input = readyInput();
  const operationEvents = [];
  const databaseClient = memorySupabase(rowsFor(input), {}, operationEvents);
  const accessToken = "short-lived-production-system-user-token";

  const result = await runPersistedRf1086ProductionStep({
    ...splitClients(databaseClient),
    actorId,
    previewId: preview.id,
    confirmations: input.confirmations,
    accessToken,
    now: input.now,
    authorityTransport: async () => {
      operationEvents.push("authority-transport");
      return jsonResponse({ hovedskjemaId: "a2345678-1234-4234-9234-123456789abc" });
    },
  });

  assert.equal(result.complete, false);
  assert.ok(operationEvents.indexOf("insert:audit_events") < operationEvents.indexOf("authority-transport"));
  assert.equal(databaseClient.auditRows().length, 1);
  assert.equal(databaseClient.auditRows()[0].action, "rf1086_production_step_authorized");
  assert.doesNotMatch(JSON.stringify(databaseClient.auditRows()), new RegExp(accessToken, "u"));
});

test("fails closed before journal or transport when the audit write fails", async () => {
  const input = readyInput();
  const operationEvents = [];
  const databaseClient = memorySupabase(rowsFor(input), {
    audit_events: { message: "internal audit database credentials" },
  }, operationEvents);
  let transports = 0;

  await assert.rejects(
    runPersistedRf1086ProductionStep({
      ...splitClients(databaseClient),
      actorId,
      previewId: preview.id,
      confirmations: input.confirmations,
      accessToken: "short-lived-production-system-user-token",
      now: input.now,
      authorityTransport: async () => {
        transports += 1;
        throw new Error("must not be called");
      },
    }),
    (error) =>
      error instanceof Rf1086ProductionRunnerError &&
      error.code === "rf1086_production_audit_failed" &&
      !error.message.includes("credentials"),
  );
  assert.equal(transports, 0);
  assert.equal(operationEvents.some((event) => event.startsWith("rpc:")), false);
});

test("derives the production token customer and fixed scope from authoritative state", async () => {
  const input = readyInput();
  const operationEvents = [];
  const databaseClient = memorySupabase(rowsFor(input), {}, operationEvents);
  const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
  let grantPayload;

  const result = await runPersistedRf1086ProductionStepWithSystemUser({
    ...splitClients(databaseClient),
    actorId,
    previewId: preview.id,
    confirmations: input.confirmations,
    now: input.now,
    maskinporten: {
      clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
      keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
      privateKeyPem,
      fetchImplementation: async (url, init) => {
        operationEvents.push("maskinporten-transport");
        assert.equal(url, "https://maskinporten.no/token");
        const assertion = new URLSearchParams(init.body).get("assertion");
        grantPayload = JSON.parse(Buffer.from(assertion.split(".")[1], "base64url").toString("utf8"));
        return new Response(JSON.stringify({
          access_token: "short-lived-production-system-user-token",
          token_type: "Bearer",
          expires_in: 120,
          scope: "skatteetaten:innrapporteringaksjonaerregisteroppgave",
        }), { status: 200, headers: { "content-type": "application/json" } });
      },
    },
    authorityTransport: async (request) => {
      operationEvents.push("authority-transport");
      assert.equal(request.headers.Authorization, "Bearer short-lived-production-system-user-token");
      return jsonResponse({ hovedskjemaId: "a2345678-1234-4234-9234-123456789abc" });
    },
  });

  assert.equal(result.complete, false);
  assert.equal(grantPayload.aud, "https://maskinporten.no/");
  assert.equal(grantPayload.scope, "skatteetaten:innrapporteringaksjonaerregisteroppgave");
  assert.equal(grantPayload.authorization_details[0].systemuser_org.ID, "0192:310279617");
  for (const event of [
    "rpc:acquire_rf1086_production_lease",
    "maskinporten-transport",
    "authority-transport",
    "rpc:release_rf1086_production_lease",
  ]) {
    assert.notEqual(operationEvents.indexOf(event), -1);
  }
  assert.ok(operationEvents.indexOf("insert:audit_events") < operationEvents.indexOf("maskinporten-transport"));
  assert.ok(operationEvents.lastIndexOf("insert:audit_events") < operationEvents.indexOf("authority-transport"));
  assert.ok(operationEvents.indexOf("rpc:acquire_rf1086_production_lease") < operationEvents.indexOf("maskinporten-transport"));
  assert.ok(operationEvents.indexOf("maskinporten-transport") < operationEvents.indexOf("authority-transport"));
  assert.ok(operationEvents.indexOf("authority-transport") < operationEvents.indexOf("rpc:release_rf1086_production_lease"));
  assert.deepEqual(databaseClient.auditRows().map((row) => row.action), [
    "rf1086_production_token_authorized",
    "rf1086_production_step_authorized",
  ]);
  assert.doesNotMatch(JSON.stringify(result), /short-lived-production-system-user-token/u);
  assert.doesNotMatch(JSON.stringify(databaseClient.auditRows()), /short-lived-production-system-user-token/u);
});

test("does not sign or request a production token when the pre-token audit fails", async () => {
  const input = readyInput();
  const databaseClient = memorySupabase(rowsFor(input), {
    audit_events: { message: "private audit backend detail" },
  });
  let tokenRequests = 0;
  let authorityRequests = 0;

  await assert.rejects(
    runPersistedRf1086ProductionStepWithSystemUser({
      ...splitClients(databaseClient),
      actorId,
      previewId: preview.id,
      confirmations: input.confirmations,
      now: input.now,
      maskinporten: {
        clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
        keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
        privateKeyPem: "not opened before the audit succeeds",
        fetchImplementation: async () => {
          tokenRequests += 1;
          throw new Error("must not be called");
        },
      },
      authorityTransport: async () => {
        authorityRequests += 1;
        throw new Error("must not be called");
      },
    }),
    (error) =>
      error instanceof Rf1086ProductionRunnerError &&
      error.code === "rf1086_production_audit_failed" &&
      !error.message.includes("backend"),
  );
  assert.equal(tokenRequests, 0);
  assert.equal(authorityRequests, 0);
});
