import assert from "node:assert/strict";
import test from "node:test";

import {
  Rf1086ProductionRunnerError,
  runRf1086ProductionStep,
} from "../app/lib/rf1086-production-runner.ts";

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
  hovedskjema_xml: "<melding><EnhetOrganisasjonsnummer-datadef-18>310279617</EnhetOrganisasjonsnummer-datadef-18></melding>",
  underskjema_xml: {
    shareholder: "<melding><AksjeErvervType-datadef-17745>N</AksjeErvervType-datadef-17745></melding>",
  },
  source: "python_rf1086_engine",
  created_at: "2026-07-13T18:00:00.000Z",
};

function readyRelease(overrides = {}) {
  return {
    actorId,
    membership: {
      company_id: companyId,
      user_id: actorId,
      role: "owner",
      accepted_at: "2026-07-13T17:00:00.000Z",
    },
    authorityPermissions: [
      {
        company_id: companyId,
        obligation: "aksjonaerregisteroppgaven",
        submitter_user_id: actorId,
        confirmed_by: actorId,
        confirmed_at: "2026-07-13T17:00:00.000Z",
        production_enabled: true,
      },
    ],
    authorityTestRuns: [
      {
        company_id: companyId,
        obligation: "aksjonaerregisteroppgaven",
        status: "accepted",
        receipt_reference: "tt02-receipt",
        archive_reference: "tt02-archive",
        recorded_at: "2026-07-13T17:00:00.000Z",
      },
    ],
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
      refund_completed: false,
      no_charge_reason: null,
    },
    filingReady: true,
    stepUpContext: {
      actorId,
      mfaVerifiedAt: "2026-07-13T17:55:00.000Z",
      securityReviewApproved: true,
      productionCredentialsEnabled: true,
    },
    launchSignoffs: [
      {
        key: "rf1086_authority",
        status: "approved",
        reviewer: "Independent reviewer",
        reviewedAt: "2026-07-13T17:30:00.000Z",
        evidenceLink: "https://evidence.example/rf1086",
        decision: "Approved supported RF-1086 production scope.",
      },
    ],
    hardReviewBlockCount: 0,
    blockingOverrideCount: 0,
    confirmations: { authorityConfirmed: true, previewConfirmed: true },
    now: new Date("2026-07-13T18:00:00.000Z"),
    ...overrides,
  };
}

function memoryDatabaseClient() {
  let row = null;
  let writes = 0;
  return {
    from(table) {
      assert.equal(table, "rf1086_authority_checkpoints");
      return {
        select() {
          return {
            eq(column, value) {
              assert.equal(column, "preview_id");
              assert.equal(value, preview.id);
              return {
                async maybeSingle() {
                  return { data: structuredClone(row), error: null };
                },
              };
            },
          };
        },
      };
    },
    async rpc(name, parameters) {
      assert.equal(name, "save_rf1086_authority_checkpoint");
      const currentRevision = row?.revision ?? null;
      if (currentRevision !== parameters.p_expected_revision) {
        return { data: null, error: { code: "PT409" } };
      }
      row = {
        preview_id: preview.id,
        company_id: companyId,
        income_year: 2025,
        revision: parameters.p_checkpoint.revision,
        checkpoint: structuredClone(parameters.p_checkpoint),
      };
      writes += 1;
      return { data: row.revision, error: null };
    },
    current() {
      return structuredClone(row);
    },
    writes() {
      return writes;
    },
  };
}

function jsonResponse(value) {
  return {
    status: 200,
    headers: { "content-type": "application/json" },
    body: new TextEncoder().encode(JSON.stringify(value)),
  };
}

function authorityTransport(events) {
  return async (request) => {
    events.push({ method: request.method, url: request.url, authorization: request.headers.Authorization });
    if (request.url.endsWith("/1086H")) {
      return jsonResponse({ hovedskjemaId: "52345678-1234-4234-9234-123456789abc" });
    }
    if (request.url.endsWith("/1086U")) {
      return { status: 200, headers: {}, body: new Uint8Array() };
    }
    return jsonResponse({
      oppgavegiversLeveranseReferanse: "52345678-1234-4234-9234-123456789abc",
      dialogId: "62345678-1234-4234-9234-123456789abc",
      forsendelseId: "72345678-1234-4234-9234-123456789abc",
    });
  };
}

test("advances one production call only after every release and owner gate passes", async () => {
  const databaseClient = memoryDatabaseClient();
  const events = [];
  const accessToken = "short-lived-production-system-user-token";

  const result = await runRf1086ProductionStep({
    preview,
    databaseClient,
    accessToken,
    authorityTransport: authorityTransport(events),
    release: readyRelease(),
  });

  assert.equal(result.complete, false);
  assert.equal(result.checkpoint.environment, "production");
  assert.equal(result.checkpoint.calls[0].status, "accepted");
  assert.equal(databaseClient.writes(), 3);
  assert.equal(events.length, 1);
  assert.equal(events[0].url, "https://api.skatteetaten.no/api/aksjonaerregister/v1/2025/1086H");
  assert.equal(events[0].authorization, `Bearer ${accessToken}`);
  assert.doesNotMatch(JSON.stringify(databaseClient.current()), new RegExp(accessToken, "u"));
  assert.doesNotMatch(JSON.stringify(result), new RegExp(accessToken, "u"));
});

test("blocks fabricated ownership, incomplete gates, current review blocks, and unsupported events before transport", async () => {
  const cases = [
    {
      release: readyRelease({ membership: { ...readyRelease().membership, user_id: "82345678-1234-4234-9234-123456789abc" } }),
      expectedCode: "rf1086_production_owner_required",
    },
    {
      release: readyRelease({ authorityTestRuns: [] }),
      expectedCode: "rf1086_production_gate_disabled",
      expectedReason: "test_evidence_missing",
    },
    {
      release: readyRelease({ hardReviewBlockCount: 1 }),
      expectedCode: "rf1086_production_gate_disabled",
      expectedReason: "hard_review_block",
    },
    {
      release: readyRelease({ confirmations: { authorityConfirmed: true, previewConfirmed: false } }),
      expectedCode: "rf1086_production_confirmation_missing",
    },
  ];

  for (const candidate of cases) {
    const databaseClient = memoryDatabaseClient();
    let transports = 0;
    await assert.rejects(
      runRf1086ProductionStep({
        preview,
        databaseClient,
        accessToken: "short-lived-production-system-user-token",
        authorityTransport: async () => {
          transports += 1;
          throw new Error("must not be called");
        },
        release: candidate.release,
      }),
      (error) =>
        error instanceof Rf1086ProductionRunnerError &&
        error.code === candidate.expectedCode &&
        (!candidate.expectedReason || error.disabledReasons.includes(candidate.expectedReason)),
    );
    assert.equal(transports, 0);
    assert.equal(databaseClient.writes(), 0);
  }

  const dividendPreview = {
    ...preview,
    underskjema_xml: {
      shareholder: "<melding><AksjeUtbytteHendelsestype-datadef-36564>U</AksjeUtbytteHendelsestype-datadef-36564></melding>",
    },
  };
  await assert.rejects(
    runRf1086ProductionStep({
      preview: dividendPreview,
      databaseClient: memoryDatabaseClient(),
      accessToken: "short-lived-production-system-user-token",
      authorityTransport: async () => {
        throw new Error("must not be called");
      },
      release: readyRelease(),
    }),
    (error) => error instanceof Rf1086ProductionRunnerError && error.code === "rf1086_production_scope_unsupported",
  );
});

test("requires a separate flag before the non-idempotent production confirmation", async () => {
  const databaseClient = memoryDatabaseClient();
  const events = [];
  const base = {
    preview,
    databaseClient,
    accessToken: "short-lived-production-system-user-token",
    authorityTransport: authorityTransport(events),
    release: readyRelease(),
  };

  await runRf1086ProductionStep(base);
  await runRf1086ProductionStep(base);
  await assert.rejects(
    runRf1086ProductionStep(base),
    (error) => error instanceof Rf1086ProductionRunnerError && error.code === "rf1086_production_confirmation_required",
  );
  assert.equal(events.length, 2);

  const confirmed = await runRf1086ProductionStep({ ...base, allowConfirm: true });
  assert.equal(confirmed.complete, true);
  assert.equal(confirmed.checkpoint.status, "confirmed");
  assert.equal(events.length, 3);
});
