import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";

import {
  loadLedgerEntries,
  loadLedgerPeriodLocks,
  postLedgerManualJournal,
  startNewYear,
  ledgerActionErrorMessage,
  ledgerOutcomeMayBeUnknown,
  presentLedgerEntries,
  presentLedgerPeriodLocks,
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
    ledgerActionErrorMessage(problem("LEDGER_COMPANY_YEAR_NOT_ADMITTED")),
    "Selskapsåret er ikke godkjent for denne handlingen.",
  );
  assert.equal(
    ledgerActionErrorMessage(problem("LEDGER_OPENING_ALREADY_EXISTS")),
    "Åpningsbalansen er allerede registrert for dette året.",
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
    warningAcceptedBy: "20000000-0000-0000-0000-000000000002",
    warningAcceptedAt: "2026-08-27T09:59:58Z",
    ...overrides,
  };
}

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
    assert.match(calls[1].url, /cursor=cursor-2/u);
    assert.equal(new Headers(calls[0].request.headers).get("Authorization"), "Bearer session-token");
    assert.equal(new Headers(calls[0].request.headers).get("X-Request-ID"), "ledger-list-test");
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

test("ledger period-lock transport returns an empty result without a backend call", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => assert.fail("empty company scope must not call backend");
  try {
    assert.deepEqual(await loadLedgerPeriodLocks("session-token", []), []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
