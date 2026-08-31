import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";

import {
  loadLedgerEntries,
  loadLedgerEntriesForArchive,
  loadLedgerPeriodLocks,
  loadLedgerCompanyYearCloseAssessment,
  loadLedgerReconstructionAssessment,
  loadOpeningSnapshots,
  postLedgerAdministrativeCost,
  postLedgerManualJournal,
  startNewYear,
  ledgerActionErrorMessage,
  ledgerOutcomeMayBeUnknown,
  presentLedgerEntries,
  presentLedgerEntriesForArchive,
  presentLedgerPeriodLocks,
  presentLedgerCompanyYearClose,
  presentLedgerReconstruction,
  presentOpeningSnapshots,
} from "../features/ledger/index.ts";

test("an in-progress idempotent command preserves its operation id for retry", () => {
  const error = new TalliApiError(409, {
    code: "LEDGER_IDEMPOTENCY_IN_PROGRESS",
    detail: "Command is still running.",
    instance: "/api/v1/ledger/manual-journals",
    requestId: "ledger-retry-test",
    status: 409,
    title: "Conflict",
    type: "https://talli.no/problems/ledger-idempotency-in-progress",
  });

  assert.equal(ledgerOutcomeMayBeUnknown(error), true);
});

test("ledger errors keep the frozen plain-Norwegian guidance", () => {
  const problem = (code) => new TalliApiError(422, {
    code,
    detail: "Invalid ledger input.",
    instance: "/api/v1/ledger/manual-journals",
    requestId: "ledger-error-copy-test",
    status: 422,
    title: "Ledger request failed",
    type: "https://talli.no/problems/ledger-input",
  });

  assert.equal(
    ledgerActionErrorMessage(problem("AUTHENTICATION_REQUIRED")),
    "Innlogging kreves.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_DESCRIPTION_REQUIRED")),
    "Alle journallinjer må ha beskrivelse.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_INVALID_INPUT")),
    "Kontroller beløp, aksjetall og øvrige opplysninger.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_PAYEE_REQUIRED")),
    "Mottaker må fylles ut.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_ADMINISTRATIVE_COST_NOT_POSITIVE")),
    "Beløp må være større enn 0.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_COMPANY_YEAR_NOT_ADMITTED")),
    "Selskapsåret er ikke godkjent for denne handlingen.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_OPENING_ALREADY_EXISTS")),
    "Åpningsbalansen er allerede registrert for dette året.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_OPENING_BALANCE_INVALID")),
    "Åpningsbalansen må være komplett og balansere.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_OPENING_EVIDENCE_INVALID")),
    "Dokumentasjonen for åpningsbalansen er ikke komplett.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_OPENING_SOURCE_OVERLAP")),
    "Samme kilde kan ikke brukes flere ganger i én åpningspost.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("SHAREHOLDER_REGISTER_FILING_INVALID_INPUT")),
    "Kontroller aksjetall og aksjonæropplysninger.",
  );
});

function page(items, nextCursor = null) {
  return { items, page: { hasMore: nextCursor !== null, nextCursor } };
}

function entry(overrides = {}) {
  return {
    companyId: "10000000-0000-0000-0000-000000000001",
    entryId: "40000000-0000-0000-0000-000000000004",
    entryKind: "MANUAL_JOURNAL",
    incomeYear: 2026,
    lines: [
      {
        account: "1800",
        description: "Investment",
        debit: { amount: "100.00", currency: "NOK" },
        credit: { amount: "0.00", currency: "NOK" },
      },
      {
        account: "1920",
        description: "Bank",
        debit: { amount: "0.00", currency: "NOK" },
        credit: { amount: "100.00", currency: "NOK" },
      },
    ],
    memo: "Manual correction",
    postedAt: "2026-08-27T10:00:00Z",
    postedBy: "20000000-0000-0000-0000-000000000002",
    riskFlags: [{ account: "1800", code: "MANUAL_JOURNAL_SENSITIVE_ACCOUNT" }],
    sourceCapability: "LEDGER",
    sourceRecordId: "manual:test-entry",
    createdAt: "2026-08-27T09:59:57Z",
    warningAcceptedBy: "20000000-0000-0000-0000-000000000002",
    warningAcceptedAt: "2026-08-27T09:59:58Z",
    ...overrides,
  };
}

const OPENING_COMPANY_ID = "10000000-0000-0000-0000-000000000001";
const OPENING_SETUP_ID = "60000000-0000-0000-0000-000000000006";

function openingSnapshot(overrides = {}) {
  return {
    setupId: OPENING_SETUP_ID,
    companyId: OPENING_COMPANY_ID,
    incomeYear: 2026,
    bankBalance: { amount: "45000.00", currency: "NOK" },
    shareCapital: { amount: "30000.00", currency: "NOK" },
    shareCount: 100,
    nominalValue: { amount: "300.00", currency: "NOK" },
    lockedAt: "2026-08-27T10:00:00Z",
    createdAt: "2026-08-27T09:00:00Z",
    createdBy: "20000000-0000-0000-0000-000000000002",
    shareholders: [{
      shareholderId: "70000000-0000-0000-0000-000000000007",
      setupId: OPENING_SETUP_ID,
      companyId: OPENING_COMPANY_ID,
      name: "Owner",
      shareholderKind: "norwegian_person",
      nationalId: "01010112345",
      orgNumber: null,
      shareCount: 100,
    }],
    ...overrides,
  };
}

function openingPage(items, nextCursor = null) {
  return { items, hasMore: nextCursor !== null, nextCursor };
}

test("opening-snapshot transport chunks companies and follows opaque pages", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const calls = [];
  const companyIds = Array.from({ length: 101 }, (_, index) => (
    `10000000-0000-0000-0000-${(index + 1).toString(16).padStart(12, "0")}`
  ));
  const secondChunkSetupId = "60000000-0000-0000-0000-000000000008";
  globalThis.fetch = async (url, request) => {
    calls.push({ url: String(url), request });
    if (String(url).includes("cursor=opaque-next")) {
      return Response.json(openingPage([]));
    }
    if ((String(url).match(/companyId=/gu) ?? []).length === 100) {
      return Response.json(openingPage([openingSnapshot()], "opaque-next"));
    }
    return Response.json(openingPage([openingSnapshot({
      setupId: secondChunkSetupId,
      companyId: companyIds[100],
      createdAt: "2026-08-27T11:00:00Z",
      shareholders: [{
        ...openingSnapshot().shareholders[0],
        shareholderId: "70000000-0000-0000-0000-000000000009",
        setupId: secondChunkSetupId,
        companyId: companyIds[100],
      }],
    })]));
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const result = await loadOpeningSnapshots(
      "session-token",
      [...companyIds, companyIds[0]],
      "opening-query-test",
    );

    assert.equal(result.length, 2);
    assert.equal(result[0].setupId, secondChunkSetupId);
    assert.equal(result[1].setupId, OPENING_SETUP_ID);
    assert.equal(calls.length, 3);
    assert.equal((calls[0].url.match(/companyId=/gu) ?? []).length, 100);
    assert.match(calls[1].url, /cursor=opaque-next/u);
    assert.equal((calls[2].url.match(/companyId=/gu) ?? []).length, 1);
    const headers = new Headers(calls[0].request.headers);
    assert.equal(headers.get("Authorization"), "Bearer session-token");
    assert.equal(headers.get("X-Request-ID"), "opening-query-test");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("opening-snapshot compatibility projection preserves the frozen shape", () => {
  assert.deepEqual(presentOpeningSnapshots([openingSnapshot()]), {
    setups: [{
      id: OPENING_SETUP_ID,
      company_id: OPENING_COMPANY_ID,
      income_year: 2026,
      bank_balance: 45000,
      share_capital: 30000,
      share_count: 100,
      nominal_value: 300,
      locked_at: "2026-08-27T10:00:00Z",
      created_by: "20000000-0000-0000-0000-000000000002",
    }],
    shareholders: [{
      id: "70000000-0000-0000-0000-000000000007",
      setup_id: OPENING_SETUP_ID,
      company_id: OPENING_COMPANY_ID,
      name: "Owner",
      shareholder_kind: "norwegian_person",
      national_id: "01010112345",
      org_number: null,
      share_count: 100,
    }],
  });
});

test("opening-snapshot decoders reject malformed collections and invariants", async () => {
  const generated = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () => Response.json(openingPage([
      openingSnapshot({ shareholders: [] }),
    ])),
  });
  await assert.rejects(
    generated.ledgerListOpeningSnapshots({ companyIds: [OPENING_COMPANY_ID] }),
    (error) => error instanceof TalliApiError && error.status === 502,
  );

  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  try {
    for (const malformed of [
      openingSnapshot({ shareCapital: { amount: "29999.00", currency: "NOK" } }),
      openingSnapshot({
        shareholders: [{
          ...openingSnapshot().shareholders[0],
          shareholderKind: "norwegian_company",
        }],
      }),
      openingSnapshot({
        shareholders: [
          { ...openingSnapshot().shareholders[0], shareCount: 50 },
          { ...openingSnapshot().shareholders[0], shareCount: 50 },
        ],
      }),
    ]) {
      globalThis.fetch = async () => Response.json(openingPage([malformed]));
      await assert.rejects(
        loadOpeningSnapshots("session-token", [OPENING_COMPANY_ID]),
        /inconsistent/u,
      );
    }
    globalThis.fetch = async () => Response.json({
      items: [],
      nextCursor: "unexpected",
      hasMore: false,
    });
    await assert.rejects(
      loadOpeningSnapshots("session-token", [OPENING_COMPANY_ID]),
      /page is inconsistent/u,
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("ledger query transport follows opaque pages through the generated client", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const calls = [];
  globalThis.fetch = async (url, request) => {
    calls.push({ url: String(url), request });
    return Response.json(calls.length === 1 ? page([entry()], "cursor-2") : page([]));
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const result = await loadLedgerEntries(
      "session-token",
      ["10000000-0000-0000-0000-000000000001"],
      "ledger-list-test",
    );

    assert.equal(result.length, 1);
    assert.equal(calls.length, 2);
    assert.match(calls[0].url, /companyId=10000000-0000-0000-0000-000000000001/u);
    assert.doesNotMatch(calls[0].url, /includeSource/u);
    assert.match(calls[1].url, /cursor=cursor-2/u);
    assert.equal(new Headers(calls[0].request.headers).get("Authorization"), "Bearer session-token");
    assert.equal(new Headers(calls[0].request.headers).get("X-Request-ID"), "ledger-list-test");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("reconstruction readiness comes from the generated backend contract", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const calls = [];
  globalThis.fetch = async (url, request) => {
    calls.push({ url: String(url), request });
    return Response.json({
      assessmentId: "40000000-0000-0000-0000-000000000004",
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
      asOf: "2026-08-27",
      state: "BLOCKED",
      gapCodes: ["BANK_MOVEMENTS_INCOMPLETE", "DOCUMENTS_INCOMPLETE"],
      evidenceDigest: "a".repeat(64),
      ledgerStateDigest: "d".repeat(64),
      economicFactsDigest: "e".repeat(64),
      economicFactCount: 4,
      sourceEvidenceDigest: "a".repeat(64),
      sourceEvidenceCount: 13,
      recordedAt: "2026-08-27T10:00:00Z",
    });
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const result = await loadLedgerReconstructionAssessment(
      "session-token",
      OPENING_COMPANY_ID,
      2026,
      "reconstruction-query-test",
    );

    assert.equal(result.state, "BLOCKED");
    assert.match(calls[0].url, /companyId=10000000-0000-0000-0000-000000000001/u);
    assert.match(calls[0].url, /incomeYear=2026/u);
    const headers = new Headers(calls[0].request.headers);
    assert.equal(headers.get("Authorization"), "Bearer session-token");
    assert.equal(headers.get("X-Request-ID"), "reconstruction-query-test");
    assert.deepEqual(presentLedgerReconstruction(result), {
      assessment_id: "40000000-0000-0000-0000-000000000004",
      company_id: OPENING_COMPANY_ID,
      income_year: 2026,
      as_of: "2026-08-27",
      ready: false,
      refresh_message: null,
      gaps: [
        {
          code: "BANK_MOVEMENTS_INCOMPLETE",
          message: "Alle bankbevegelser fra 1. januar er ikke dokumentert ennå.",
        },
        {
          code: "DOCUMENTS_INCOMPLETE",
          message: "Nødvendige bilag mangler.",
        },
      ],
      evidence_digest: "a".repeat(64),
      ledger_state_digest: "d".repeat(64),
      recorded_at: "2026-08-27T10:00:00Z",
    });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("current company-year close comes from the generated read-only backend contract", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const calls = [];
  globalThis.fetch = async (url, request) => {
    calls.push({ url: String(url), request });
    return Response.json({
      assessmentId: "42000000-0000-0000-0000-000000000004",
      closeLockId: "43000000-0000-0000-0000-000000000004",
      reconstructionAssessmentId: "41000000-0000-0000-0000-000000000004",
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
      periodEnd: "2026-12-31",
      state: "CLOSED",
      gapCodes: [],
      evidenceDigest: "b".repeat(64),
      ledgerStateDigest: "c".repeat(64),
      recordedAt: "2026-08-27T10:00:00Z",
      replayed: false,
      isCurrent: true,
    });
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const result = await loadLedgerCompanyYearCloseAssessment(
      "session-token",
      OPENING_COMPANY_ID,
      2026,
      "company-year-close-query-test",
    );

    assert.match(calls[0].url, /company-year-close-assessment/u);
    assert.match(calls[0].url, /companyId=10000000-0000-0000-0000-000000000001/u);
    assert.match(calls[0].url, /incomeYear=2026/u);
    const headers = new Headers(calls[0].request.headers);
    assert.equal(headers.get("Authorization"), "Bearer session-token");
    assert.equal(headers.get("X-Request-ID"), "company-year-close-query-test");
    assert.deepEqual(presentLedgerCompanyYearClose(result), {
      assessment_id: "42000000-0000-0000-0000-000000000004",
      close_lock_id: "43000000-0000-0000-0000-000000000004",
      reconstruction_assessment_id: "41000000-0000-0000-0000-000000000004",
      company_id: OPENING_COMPANY_ID,
      income_year: 2026,
      period_end: "2026-12-31",
      status: "closed_current",
      title: "Året er avsluttet",
      message: "Avslutningen bygger på siste bokførte versjon.",
      gaps: [],
      evidence_digest: "b".repeat(64),
      ledger_state_digest: "c".repeat(64),
      recorded_at: "2026-08-27T10:00:00Z",
      replayed: false,
      is_current: true,
    });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("company-year close presentation distinguishes stale and blocked assessments", () => {
  const current = {
    assessmentId: "42000000-0000-0000-0000-000000000004",
    closeLockId: "43000000-0000-0000-0000-000000000004",
    reconstructionAssessmentId: "41000000-0000-0000-0000-000000000004",
    companyId: OPENING_COMPANY_ID,
    incomeYear: 2026,
    periodEnd: "2026-12-31",
    state: "CLOSED",
    gapCodes: [],
    evidenceDigest: "b".repeat(64),
    ledgerStateDigest: "c".repeat(64),
    recordedAt: "2026-08-27T10:00:00Z",
    replayed: false,
    isCurrent: true,
  };

  const stale = presentLedgerCompanyYearClose({ ...current, isCurrent: false });
  assert.equal(stale.status, "closed_stale");
  assert.equal(stale.title, "Året må avsluttes på nytt");
  assert.equal(
    stale.message,
    "Kontrollgrunnlaget er ikke lenger det nyeste. Oppdater kontrollene og avslutt året på nytt.",
  );
  assert.equal(stale.close_lock_id, current.closeLockId);
  assert.equal(stale.is_current, false);

  const blocked = presentLedgerCompanyYearClose({
    ...current,
    closeLockId: null,
    state: "BLOCKED",
    gapCodes: ["SOURCE_INCOMPLETE", "BANK_NOT_RECONCILED"],
    isCurrent: false,
  });
  assert.equal(blocked.status, "blocked");
  assert.equal(blocked.title, "Året kan ikke avsluttes ennå");
  assert.equal(blocked.message, "Fullfør kontrollene før året avsluttes.");
  assert.deepEqual(blocked.gaps, [
    {
      code: "SOURCE_INCOMPLETE",
      message: "Kildegrunnlaget for året er ikke komplett.",
    },
    {
      code: "BANK_NOT_RECONCILED",
      message: "Bankkontoene er ikke fullt avstemt.",
    },
  ]);
});

test("generated reconstruction decoder rejects unknown gap codes", async () => {
  const generated = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () => Response.json({
      assessmentId: "40000000-0000-0000-0000-000000000004",
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
      asOf: "2026-08-27",
      state: "BLOCKED",
      gapCodes: ["OWNER_SUPPLIED_FREE_TEXT"],
      evidenceDigest: "a".repeat(64),
      ledgerStateDigest: "d".repeat(64),
      economicFactsDigest: "e".repeat(64),
      economicFactCount: 4,
      sourceEvidenceDigest: "a".repeat(64),
      sourceEvidenceCount: 13,
      recordedAt: "2026-08-27T10:00:00Z",
    }),
  });

  await assert.rejects(
    generated.ledgerGetReconstructionAssessment({
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
    }),
    (error) => error instanceof TalliApiError && error.status === 502,
  );
});

test("generated reconstruction decoder preserves historical null and rejects partial bindings", async () => {
  const response = {
    assessmentId: "40000000-0000-0000-0000-000000000004",
    companyId: OPENING_COMPANY_ID,
    incomeYear: 2026,
    asOf: "2026-08-27",
    state: "READY",
    gapCodes: [],
    evidenceDigest: "a".repeat(64),
    ledgerStateDigest: null,
    economicFactsDigest: null,
    economicFactCount: null,
    sourceEvidenceDigest: null,
    sourceEvidenceCount: null,
    recordedAt: "2026-08-27T10:00:00Z",
  };
  const generated = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () => Response.json(response),
  });

  const historical = await generated.ledgerGetReconstructionAssessment({
    companyId: OPENING_COMPANY_ID,
    incomeYear: 2026,
  });
  const historicalPresentation = presentLedgerReconstruction(historical);
  assert.equal(historicalPresentation.ledger_state_digest, null);
  assert.equal(historicalPresentation.ready, false);
  assert.equal(
    historicalPresentation.refresh_message,
    "Oppdater årsgrunnlaget før du avslutter året.",
  );

  response.ledgerStateDigest = "not-authoritative";

  await assert.rejects(
    generated.ledgerGetReconstructionAssessment({
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
    }),
    (error) => error instanceof TalliApiError && error.status === 502,
  );

  response.ledgerStateDigest = null;
  delete response.economicFactCount;

  await assert.rejects(
    generated.ledgerGetReconstructionAssessment({
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
    }),
    (error) => error instanceof TalliApiError && error.status === 502,
  );

  response.economicFactCount = null;
  delete response.sourceEvidenceCount;

  await assert.rejects(
    generated.ledgerGetReconstructionAssessment({
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
    }),
    (error) => error instanceof TalliApiError && error.status === 502,
  );
});

test("generated company-year close decoder rejects unknown gap codes", async () => {
  const generated = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () => Response.json({
      assessmentId: "42000000-0000-0000-0000-000000000004",
      closeLockId: null,
      reconstructionAssessmentId: "41000000-0000-0000-0000-000000000004",
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
      periodEnd: "2026-12-31",
      state: "BLOCKED",
      gapCodes: ["OWNER_SUPPLIED_FREE_TEXT"],
      evidenceDigest: "b".repeat(64),
      ledgerStateDigest: "c".repeat(64),
      recordedAt: "2026-08-27T10:00:00Z",
      replayed: false,
      isCurrent: false,
    }),
  });

  await assert.rejects(
    generated.ledgerGetCompanyYearCloseAssessment({
      companyId: OPENING_COMPANY_ID,
      incomeYear: 2026,
    }),
    (error) => error instanceof TalliApiError && error.status === 502,
  );
});

test("generated ledger query rejects a partial expanded source pair", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const item = entry();
  delete item.sourceRecordId;
  globalThis.fetch = async () => Response.json(page([item]));
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    await assert.rejects(
      loadLedgerEntriesForArchive("session-token", ["10000000-0000-0000-0000-000000000001"]),
      (error) => error instanceof TalliApiError && error.status === 502,
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("source-aware ledger query fails closed against a source-unaware backend", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const item = entry();
  delete item.sourceCapability;
  delete item.sourceRecordId;
  delete item.createdAt;
  globalThis.fetch = async () => Response.json(page([item]));
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    await assert.rejects(
      loadLedgerEntriesForArchive("session-token", ["10000000-0000-0000-0000-000000000001"]),
      /archive facts/iu,
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("source-aware ledger queries opt into the expanded response", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  let capturedUrl = "";
  globalThis.fetch = async (url) => {
    capturedUrl = String(url);
    return Response.json(page([entry()]));
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const entries = await loadLedgerEntriesForArchive(
      "session-token",
      ["10000000-0000-0000-0000-000000000001"],
    );
    assert.equal(entries.length, 1);
    assert.match(capturedUrl, /includeSource=true/u);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("ledger mutation transport injects decimal money and idempotency headers", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  let captured;
  globalThis.fetch = async (url, request) => {
    captured = { url: String(url), request };
    return Response.json({
      companyId: "10000000-0000-0000-0000-000000000001",
      entryId: "40000000-0000-0000-0000-000000000004",
      entryKind: "MANUAL_JOURNAL",
      incomeYear: 2026,
      postedAt: "2026-08-27T10:00:00Z",
      replayed: false,
    }, { status: 201 });
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    await postLedgerManualJournal(
      "session-token",
      {
        companyId: "10000000-0000-0000-0000-000000000001",
        incomeYear: 2026,
        lines: entry().lines,
        memo: "Manual correction",
        warningAccepted: true,
      },
      "30000000-0000-4000-8000-000000000003",
      "ledger-write-test",
    );

    assert.equal(captured.url, "https://backend.example/api/v1/ledger/manual-journals");
    const headers = new Headers(captured.request.headers);
    assert.equal(headers.get("Authorization"), "Bearer session-token");
    assert.equal(headers.get("Idempotency-Key"), "30000000-0000-4000-8000-000000000003");
    assert.deepEqual(JSON.parse(captured.request.body).lines[0].debit, {
      amount: "100.00",
      currency: "NOK",
    });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("administrative-cost transport requires exact purpose-bound success evidence", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const operationId = "30000000-0000-4000-8000-000000000030";
  const command = {
    amount: { amount: "125.50", currency: "NOK" },
    bankTransactionId: "70000000-0000-4000-8000-000000000007",
    category: "BANK_FEE",
    companyId: "10000000-0000-0000-0000-000000000001",
    documentId: null,
    incomeYear: 2026,
    paidDate: "2026-04-15",
    payee: "Example Bank",
  };
  let captured;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  try {
    globalThis.fetch = async (url, request) => {
      captured = { url: String(url), request };
      return Response.json({
        companyId: command.companyId,
        entryId: "40000000-0000-0000-0000-000000000004",
        entryKind: "ADMINISTRATIVE_COST",
        incomeYear: 2026,
        postedAt: "2026-08-27T10:00:00Z",
        replayed: false,
      }, { status: 201 });
    };
    await postLedgerAdministrativeCost(
      "session-token", command, operationId, operationId,
    );
    assert.equal(
      captured.url,
      "https://backend.example/api/v1/ledger/administrative-costs",
    );
    const headers = new Headers(captured.request.headers);
    assert.equal(headers.get("Idempotency-Key"), operationId);
    assert.deepEqual(JSON.parse(captured.request.body), command);

    for (const inconsistent of [
      { entryKind: "MANUAL_JOURNAL" },
      { companyId: "10000000-0000-0000-0000-000000000099" },
      { incomeYear: 2025 },
    ]) {
      globalThis.fetch = async () => Response.json({
        companyId: command.companyId,
        entryId: "40000000-0000-0000-0000-000000000004",
        entryKind: "ADMINISTRATIVE_COST",
        incomeYear: 2026,
        postedAt: "2026-08-27T10:00:00Z",
        replayed: false,
        ...inconsistent,
      }, { status: 201 });
      await assert.rejects(
        postLedgerAdministrativeCost(
          "session-token", command, operationId, operationId,
        ),
        (error) => error instanceof TalliApiError && error.status === 502,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("new-year start uses the generated atomic workflow without exposing ledger lines", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  let captured;
  globalThis.fetch = async (url, request) => {
    captured = { url: String(url), request };
    return Response.json({
      setupId: "60000000-0000-0000-0000-000000000006",
      postedEntry: {
        companyId: "10000000-0000-0000-0000-000000000001",
        entryId: "40000000-0000-0000-0000-000000000004",
        entryKind: "OPENING_BALANCE",
        incomeYear: 2026,
        postedAt: "2026-08-27T10:00:00Z",
        replayed: false,
      },
    }, { status: 201 });
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    await startNewYear(
      "session-token",
      {
        bankBalance: { amount: "45000.00", currency: "NOK" },
        companyId: "10000000-0000-0000-0000-000000000001",
        incomeYear: 2026,
        nominalValue: { amount: "300.00", currency: "NOK" },
        shareCapital: { amount: "30000.00", currency: "NOK" },
        shareCount: 100,
        shareholders: [{
          name: "Owner",
          nationalId: "01010112345",
          orgNumber: null,
          shareCount: 100,
          shareholderKind: "norwegian_person",
        }],
      },
      "60000000-0000-4000-8000-000000000006",
      "new-year-test",
    );

    assert.equal(captured.url, "https://backend.example/api/v1/new-year-starts");
    const headers = new Headers(captured.request.headers);
    assert.equal(headers.get("Idempotency-Key"), "60000000-0000-4000-8000-000000000006");
    assert.equal("lines" in JSON.parse(captured.request.body), false);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("new-year start rejects malformed or non-opening success evidence", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  const command = {
    bankBalance: { amount: "45000.00", currency: "NOK" },
    companyId: "10000000-0000-0000-0000-000000000001",
    incomeYear: 2026,
    nominalValue: { amount: "300.00", currency: "NOK" },
    shareCapital: { amount: "30000.00", currency: "NOK" },
    shareCount: 100,
    shareholders: [{
      name: "Owner",
      nationalId: "01010112345",
      orgNumber: null,
      shareCount: 100,
      shareholderKind: "norwegian_person",
    }],
  };

  try {
    for (const response of [
      {
        setupId: "",
        postedEntry: {
          companyId: command.companyId,
          entryId: "40000000-0000-0000-0000-000000000004",
          entryKind: "OPENING_BALANCE",
          incomeYear: 2026,
          postedAt: "2026-08-27T10:00:00Z",
          replayed: false,
        },
      },
      {
        setupId: "60000000-0000-0000-0000-000000000006",
        postedEntry: {
          companyId: command.companyId,
          entryId: "40000000-0000-0000-0000-000000000004",
          entryKind: "MANUAL_JOURNAL",
          incomeYear: 2026,
          postedAt: "2026-08-27T10:00:00Z",
          replayed: false,
        },
      },
    ]) {
      globalThis.fetch = async () => Response.json(response, { status: 201 });
      await assert.rejects(
        startNewYear(
          "session-token",
          command,
          "60000000-0000-4000-8000-000000000006",
        ),
        (error) => error instanceof TalliApiError && error.status === 502,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("opening setup action has no direct business persistence or duplicate posting policy", () => {
  const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
  const form = readFileSync(
    new URL("../app/(owner)/onboarding/OpeningBalanceForm.tsx", import.meta.url),
    "utf8",
  );
  const start = actions.indexOf("export async function createOpeningBalanceSetup");
  const end = actions.indexOf("export async function lockCompanyYear", start);
  const body = actions.slice(start, end);
  assert.match(body, /startNewYear\(/u);
  assert.doesNotMatch(body, /\.from\("(?:opening_balance_setups|opening_shareholders|ledger_entries)"\)/u);
  assert.match(body, /persistLedgerAudit\(/u);
  assert.match(body, /\.from\("audit_events"\)/u);
  assert.doesNotMatch(body, /(?:1920|2000|2050)/u);
  assert.match(body, /newYearOperationId/iu);
  assert.match(body, /kontrollsporet kunne ikke bekreftes/u);
  assert.doesNotMatch(form, /useMemo|capitalOk|sharesOk|shareholdersOk|canSubmit/u);
});

test("manual journals and period locks reconcile their frozen audit continuation", () => {
  const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
  const lockStart = actions.indexOf("export async function lockCompanyYear");
  const lockEnd = actions.indexOf("export async function queueDeadlineReminders", lockStart);
  const lockBody = actions.slice(lockStart, lockEnd);
  const manualStart = actions.indexOf("export async function postManualJournal");
  const manualEnd = actions.indexOf("/*\n * The TypeScript manual-journal validator", manualStart);
  const manualBody = actions.slice(manualStart, manualEnd);

  for (const [body, continuation] of [
    [lockBody, "lockOperationId"],
    [manualBody, "manualOperationId"],
  ]) {
    assert.match(body, /persistLedgerAudit\(/u);
    assert.match(body, /createInvitationSideEffectStore\(supabase\)/u);
    assert.match(body, /\.from\("audit_events"\)\.insert\(row\)/u);
    assert.match(body, new RegExp(continuation, "u"));
    assert.match(body, /kontrollsporet kunne ikke bekreftes/u);
    assert.doesNotMatch(body, /await supabase\.from\("audit_events"\)\.insert\(\{/u);
  }
});

test("ledger presentation maps generated facts without recreating posting policy", () => {
  const [presented] = presentLedgerEntries([entry()]);
  assert.equal(presented.entry_type, "manual_journal");
  assert.deepEqual(presented.lines[0], {
    account: "1800",
    description: "Investment",
    debit: 100,
    credit: 0,
  });
  assert.deepEqual(presented.risk_flags[0], {
    account: "1800",
    code: "manual_journal_sensitive_account",
    message: "Manuell journal berører filing-sensitiv konto 1800.",
  });
  assert.equal(presented.warning_accepted_at, "2026-08-27T09:59:58Z");

  for (const [entryKind, entryType] of [
    ["BANK_INTEREST", "bank_interest"],
    ["BANK_LOAN", "bank_loan"],
    ["CAPITAL_INCREASE", "capital_increase"],
    ["CAPITAL_REDUCTION", "capital_reduction"],
    ["COMPANY_TAX_ACCRUAL", "company_tax_accrual"],
    ["CORRECTION_REVERSAL", "correction_reversal"],
    ["GROUP_CONTRIBUTION", "group_contribution"],
    ["INTERCOMPANY_LOAN", "intercompany_loan"],
  ]) {
    assert.equal(
      presentLedgerEntries([entry({ entryKind })])[0].entry_type,
      entryType,
    );
  }

  assert.deepEqual(presentLedgerPeriodLocks([{
    companyId: "10000000-0000-0000-0000-000000000001",
    incomeYear: 2026,
    lockedAt: "2026-08-27T10:00:00Z",
    lockedBy: "20000000-0000-0000-0000-000000000002",
    periodLockId: "50000000-0000-0000-0000-000000000005",
    reason: "Filing complete",
    replayed: false,
  }])[0], {
    company_id: "10000000-0000-0000-0000-000000000001",
    id: "50000000-0000-0000-0000-000000000005",
    income_year: 2026,
    locked_at: "2026-08-27T10:00:00Z",
    locked_by: "20000000-0000-0000-0000-000000000002",
    reason: "Filing complete",
  });
});

test("opening entries recover their setup identity from canonical ledger source facts", () => {
  const [opening] = presentLedgerEntries([entry({
    entryKind: "OPENING_BALANCE",
    sourceCapability: "SHAREHOLDER_REGISTER_FILING",
    sourceRecordId: "opening-setup:60000000-0000-0000-0000-000000000006",
  })]);
  assert.equal(opening.setup_id, "60000000-0000-0000-0000-000000000006");

  const [legacyOpening] = presentLedgerEntries([entry({
    entryKind: "OPENING_BALANCE",
    sourceCapability: "LEDGER",
    sourceRecordId: "legacy:40000000-0000-0000-0000-000000000004",
  })]);
  assert.equal(legacyOpening.setup_id, null);
  assert.throws(() => presentLedgerEntries([entry({
    entryKind: "OPENING_BALANCE",
    sourceCapability: "SHAREHOLDER_REGISTER_FILING",
    sourceRecordId: "legacy:40000000-0000-0000-0000-000000000004",
  })]), /opening ledger source/iu);
});

test("archive presentation preserves the complete frozen ledger row projection", () => {
  const [archived] = presentLedgerEntriesForArchive([entry({
    entryKind: "OPENING_BALANCE",
    sourceCapability: "SHAREHOLDER_REGISTER_FILING",
    sourceRecordId: "opening-setup:60000000-0000-0000-0000-000000000006",
  })]);
  assert.deepEqual(archived, {
    id: "40000000-0000-0000-0000-000000000004",
    company_id: "10000000-0000-0000-0000-000000000001",
    setup_id: "60000000-0000-0000-0000-000000000006",
    income_year: 2026,
    entry_type: "opening_balance",
    memo: "Manual correction",
    lines: [
      {
        debit: 100,
        credit: 0,
        account: "1800",
        currency: "NOK",
        description: "Investment",
      },
      {
        debit: 0,
        credit: 100,
        account: "1920",
        currency: "NOK",
        description: "Bank",
      },
    ],
    created_by: "20000000-0000-0000-0000-000000000002",
    created_at: "2026-08-27T09:59:57Z",
  });
});

test("ledger period-lock transport returns an empty result without a backend call", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => assert.fail("empty company scope must not call backend");
  try {
    assert.deepEqual(await loadLedgerPeriodLocks("session-token", []), []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

const presentationSource = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const transactionPageSource = presentationSource("../app/(owner)/transactions/page.tsx");
const workspacePageSource = presentationSource("../app/(owner)/workspace/page.tsx");
const actionPageSource = presentationSource("../app/(owner)/actions/[type]/page.tsx");
const corporateDecisionPageSource = presentationSource(
  "../app/(owner)/corporate-decisions/[decisionId]/page.tsx",
);
const ledgerActionWizardSources = {
  recordDividendReceived: presentationSource(
    "../app/(owner)/actions/_components/DividendReceivedWizard.tsx",
  ),
  recordSharePurchase: presentationSource(
    "../app/(owner)/actions/_components/SharePurchaseWizard.tsx",
  ),
  recordShareSale: presentationSource(
    "../app/(owner)/actions/_components/ShareSaleWizard.tsx",
  ),
  recordShareholderLoan: presentationSource(
    "../app/(owner)/actions/_components/ShareholderLoanWizard.tsx",
  ),
  recordTaxSettlement: presentationSource(
    "../app/(owner)/actions/_components/TaxSettlementWizard.tsx",
  ),
};

function formsForLedgerAction(pageSource, actionName) {
  const form = new RegExp(
    `<form\\b[^>]*\\baction=\\{${actionName}\\}[^>]*>([\\s\\S]*?)<\\/form>`,
    "gu",
  );
  return [...pageSource.matchAll(form)].map((match) => match[1]);
}

function assertSingleHiddenOperationId(form, context) {
  const fields = form.match(/<input\b[^>]*\bname="operationId"[^>]*\/>/gu) ?? [];
  assert.equal(fields.length, 1, `${context} must submit exactly one operation ID`);
  assert.match(fields[0], /\btype="hidden"/u, `${context} operation ID must be hidden`);
}

test("every approved ledger-coordinator form submits one operation ID", () => {
  const instances = [
    [transactionPageSource, "acceptBankTransactionSuggestion", "transaction suggestion"],
    [transactionPageSource, "recordAdminCost", "transaction administrative cost"],
    [workspacePageSource, "recordAdminCost", "workspace administrative cost"],
    [workspacePageSource, "recordDividendReceived", "workspace received dividend"],
    [workspacePageSource, "recordSharePurchase", "workspace share purchase"],
    [workspacePageSource, "recordShareSale", "workspace share sale"],
    [workspacePageSource, "recordShareholderLoan", "workspace shareholder loan"],
    [workspacePageSource, "recordTaxSettlement", "workspace tax settlement"],
    [workspacePageSource, "recordOwnerDividendPayment", "workspace owner-dividend payment"],
    [
      corporateDecisionPageSource,
      "finalizeCorporateDecision",
      "corporate-decision finalization",
    ],
    ...Object.entries(ledgerActionWizardSources).map(([actionName, wizardSource]) => [
      wizardSource,
      actionName,
      `${actionName} wizard`,
    ]),
  ];

  assert.equal(instances.length, 15);
  for (const [pageSource, actionName, context] of instances) {
    const forms = formsForLedgerAction(pageSource, actionName);
    assert.equal(forms.length, 1, `${context} form must remain present`);
    assertSingleHiddenOperationId(forms[0], context);
  }
});

test("client action wizards keep one stable operation ID for their mounted form", () => {
  for (const [actionName, wizardSource] of Object.entries(ledgerActionWizardSources)) {
    assert.match(wizardSource, /operationId\?: string/u, `${actionName} accepts a retry ID`);
    assert.match(
      wizardSource,
      /useState\(\(\) => initialOperationId \?\? crypto\.randomUUID\(\)\)/u,
      `${actionName} creates its operation ID only once`,
    );
    assert.doesNotMatch(
      wizardSource,
      /value=\{crypto\.randomUUID\(\)\}/u,
      `${actionName} must not regenerate the ID while rendering`,
    );
  }
});

test("ledger retry IDs are plumbed only to the matching page form", () => {
  for (const [queryName, componentName] of [
    ["dividendReceivedOperationId", "DividendReceivedWizard"],
    ["sharePurchaseOperationId", "SharePurchaseWizard"],
    ["shareSaleOperationId", "ShareSaleWizard"],
    ["shareholderLoanOperationId", "ShareholderLoanWizard"],
    ["taxSettlementOperationId", "TaxSettlementWizard"],
  ]) {
    assert.match(actionPageSource, new RegExp(`${queryName}\\?: string`, "u"));
    assert.match(
      actionPageSource,
      new RegExp(`<${componentName}[\\s\\S]*?operationId=\\{query\\?\\.${queryName}\\}`, "u"),
    );
  }

  assert.match(transactionPageSource, /suggestionOperationId\?: string/u);
  assert.match(transactionPageSource, /suggestionBankTransactionId\?: string/u);
  assert.match(
    transactionPageSource,
    /name="companyId"[\s\S]*?transaction\.company_id[\s\S]*?name="incomeYear"[\s\S]*?transaction\.income_year/u,
  );
  assert.match(
    transactionPageSource,
    /query\?\.suggestionBankTransactionId === transaction\.id[\s\S]*?query\.suggestionOperationId[\s\S]*?randomUUID\(\)/u,
  );
  assert.match(transactionPageSource, /adminCostOperationId\?: string/u);
  assert.match(transactionPageSource, /adminCostBankTransactionId\?: string/u);
  assert.match(
    transactionPageSource,
    /query\?\.adminCostBankTransactionId === transaction\.id[\s\S]*?query\.adminCostOperationId[\s\S]*?randomUUID\(\)/u,
  );

  for (const queryName of [
    "adminCostOperationId",
    "dividendReceivedOperationId",
    "sharePurchaseOperationId",
    "shareSaleOperationId",
    "shareholderLoanOperationId",
    "taxSettlementOperationId",
    "ownerDividendPaymentOperationId",
    "ownerDividendPaymentBankTransactionId",
  ]) {
    assert.match(workspacePageSource, new RegExp(`${queryName}\\?: string`, "u"));
  }
  assert.match(corporateDecisionPageSource, /finalizeDecisionOperationId\?: string/u);
  assert.match(
    corporateDecisionPageSource,
    /name="operationId" value=\{query\?\.finalizeDecisionOperationId \?\? randomUUID\(\)\}/u,
  );
});

const ledgerActionsSource = presentationSource("../app/actions.ts");

function ledgerServerActionSource(actionName) {
  const start = ledgerActionsSource.indexOf(`export async function ${actionName}`);
  assert.notEqual(start, -1, `${actionName} must exist`);
  const end = ledgerActionsSource.indexOf("\nexport async function ", start + 1);
  return ledgerActionsSource.slice(start, end < 0 ? undefined : end);
}

test("all relocated ledger writers use the stable operation ID at the generated boundary", () => {
  const coordinators = {
    recordAdminCost: ["postLedgerAdministrativeCost", null],
    recordDividendReceived: ["recordInvestmentReceivedDividend", "actionId"],
    finalizeCorporateDecision: ["finalizeLedgerCorporateDecision", "finalizationId"],
    recordOwnerDividendPayment: ["postLedgerOwnerDividendPayment", null],
    recordShareholderLoan: ["postLedgerShareholderLoan", "actionId"],
    recordTaxSettlement: ["postLedgerTaxSettlement", "actionId"],
  };

  for (const [actionName, [coordinator, commandIdentity]] of Object.entries(coordinators)) {
    const action = ledgerServerActionSource(actionName);
    assert.match(action, /requiredFormUuid\(formData, "operationId"\)/u, actionName);
    assert.match(action, /getCurrentSessionAccessToken\(\)/u, actionName);
    assert.match(action, new RegExp(`await ${coordinator}\\(`, "u"), actionName);
    assert.match(
      action,
      new RegExp(`${coordinator}\\([\\s\\S]*?operationId,[\\s\\S]*?operationId`, "u"),
      `${actionName} uses operationId as Idempotency-Key and request ID`,
    );
    if (commandIdentity) {
      assert.match(action, new RegExp(`${commandIdentity}: operationId`, "u"), actionName);
    }
    assert.doesNotMatch(action, /\.from\("ledger_entries"\)|buildAdminCostLedgerLines|dividendReceivedLedgerLines|shareholderLoanLedgerLines|taxSettlementLedgerLines/u, actionName);
    assert.doesNotMatch(action, /\.rpc\("(?:accept_bank_transaction_suggestion|record_share_purchase_fifo|record_share_sale_fifo|finalize_corporate_decision|record_owner_dividend_payment)"/u, actionName);
  }
});

test("share purchases and sales use the investments generated interface", () => {
  const action = ledgerServerActionSource("recordSharePurchase");
  assert.match(action, /await recordInvestmentSharePurchase\(/u);
  assert.match(
    action,
    /recordInvestmentSharePurchase\([\s\S]*?operationId,[\s\S]*?operationId/u,
  );
  assert.match(action, /actionId: operationId/u);
  assert.match(action, /investmentsOutcomeMayBeUnknown\(error\)/u);
  assert.match(action, /investmentsActionErrorMessage\(error\)/u);
  assert.doesNotMatch(action, /postLedgerInvestmentPurchase|validateSharePurchase/u);

  const sale = ledgerServerActionSource("recordShareSale");
  assert.match(sale, /await recordInvestmentShareSale\(/u);
  assert.match(
    sale,
    /recordInvestmentShareSale\([\s\S]*?operationId,[\s\S]*?operationId/u,
  );
  assert.match(sale, /actionId: operationId/u);
  assert.match(sale, /investmentsOutcomeMayBeUnknown\(error\)/u);
  assert.match(sale, /investmentsActionErrorMessage\(error\)/u);
  assert.doesNotMatch(sale, /postLedgerInvestmentSale|validateShareSale/u);
});

test("share-sale wizard submits intent without duplicating authoritative FIFO policy", () => {
  const wizard = ledgerActionWizardSources.recordShareSale;
  assert.doesNotMatch(
    wizard,
    /share-sale|share-lots|validateShareSale|shareSaleLedgerLines|acquisition_lots/u,
  );
  assert.match(
    wizard,
    /type="hidden" name="documentStatus" value="not_required"/u,
  );
  assert.match(wizard, /SubmitButton disabled=\{!ready\}/u);
  assert.match(wizard, /c\.fifoNote/u);
});

test("committed retries reach the coordinator before mutable legacy state can reject them", () => {
  const suggestion = ledgerServerActionSource("acceptBankTransactionSuggestion");
  assert.doesNotMatch(suggestion, /matched_entry_id|matched_action_id|accepted_warning|suggestBankTransaction/u);
  assert.match(suggestion, /await acceptBankSuggestion\(/u);

  const sale = ledgerServerActionSource("recordShareSale");
  assert.doesNotMatch(sale, /investment_positions|investment_lots|validateShareSale/u);

  const finalization = ledgerServerActionSource("finalizeCorporateDecision");
  assert.match(finalization, /verifyCurrentAnnualSource: false/u);

  const payment = ledgerServerActionSource("recordOwnerDividendPayment");
  assert.doesNotMatch(payment, /corporate_decision_finalizations|corporate_document_events|bank_transactions|deriveOpenDividendPayable|validateOwnerDividendPaymentInput/u);

  for (const actionName of [
    "recordAdminCost",
    "recordDividendReceived",
    "recordShareholderLoan",
    "recordTaxSettlement",
  ]) {
    const action = ledgerServerActionSource(actionName);
    assert.doesNotMatch(action, /\.from\("(?:bank_transactions|documents|holding_actions|investment_positions|investment_lots)"\)/u, actionName);
  }
});

test("unknown coordinator outcomes preserve only the scoped retry operation", () => {
  const retryFields = {
    recordAdminCost: ["adminCostOperationId", "adminCostBankTransactionId"],
    finalizeCorporateDecision: ["finalizeDecisionOperationId"],
    recordOwnerDividendPayment: ["ownerDividendPaymentOperationId", "ownerDividendPaymentBankTransactionId"],
    recordShareholderLoan: ["shareholderLoanOperationId"],
    recordTaxSettlement: ["taxSettlementOperationId"],
  };
  for (const [actionName, fields] of Object.entries(retryFields)) {
    const action = ledgerServerActionSource(actionName);
    assert.match(action, /ledgerOutcomeMayBeUnknown\(error\)/u, actionName);
    assert.match(action, /ledgerActionErrorMessage\(error\)/u, actionName);
    for (const field of fields) assert.match(action, new RegExp(field, "u"), actionName);
  }

  for (const [actionName, operationField] of [
    ["recordDividendReceived", "dividendReceivedOperationId"],
    ["recordSharePurchase", "sharePurchaseOperationId"],
    ["recordShareSale", "shareSaleOperationId"],
  ]) {
    const action = ledgerServerActionSource(actionName);
    assert.match(action, /investmentsOutcomeMayBeUnknown\(error\)/u, actionName);
    assert.match(action, /investmentsActionErrorMessage\(error\)/u, actionName);
    assert.match(action, new RegExp(operationField, "u"), actionName);
  }

  const bankingSuggestion = ledgerServerActionSource("acceptBankTransactionSuggestion");
  assert.match(bankingSuggestion, /bankingOutcomeMayBeUnknown\(error\)/u);
  assert.match(bankingSuggestion, /bankingActionErrorMessage\(error\)/u);
  assert.match(bankingSuggestion, /suggestionOperationId/u);
  assert.match(bankingSuggestion, /suggestionBankTransactionId/u);

  for (const actionName of [
    "recordAdminCost",
    "recordShareholderLoan",
    "recordTaxSettlement",
  ]) {
    const action = ledgerServerActionSource(actionName);
    assert.match(action, /await persistLedgerAudit\(/u, actionName);
    assert.ok(
      action.indexOf("postLedger") < action.indexOf("persistLedgerAudit"),
      `${actionName} keeps audit after the committed business coordinator`,
    );
  }
  for (const actionName of [
    "acceptBankTransactionSuggestion",
    "recordDividendReceived",
    "recordSharePurchase",
    "recordShareSale",
    "finalizeCorporateDecision",
    "recordOwnerDividendPayment",
  ]) {
    assert.doesNotMatch(ledgerServerActionSource(actionName), /persistLedgerAudit/u, actionName);
  }
});
