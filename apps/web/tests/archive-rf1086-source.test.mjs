import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";
import { presentOpeningSnapshots } from "../features/ledger/presentation.ts";
import * as rfPresentation from "../features/shareholder-register-filing/presentation.ts";
import { loadRf1086ArchiveSource } from "../features/shareholder-register-filing/transport.ts";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../app/archive/[companyId]/[incomeYear]/download/route.ts", import.meta.url), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));
const companyId = "10000000-0000-4000-8000-000000000001";
const uid = n => `20000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const at = "2026-09-09T12:00:00Z";
const opening = year => ({
  setupId: uid(year), companyId, incomeYear: year,
  bankBalance: { amount: "30001.25", currency: "NOK" }, shareCapital: { amount: "30000.00", currency: "NOK" },
  nominalValue: { amount: "300.00", currency: "NOK" }, shareCount: 100, lockedAt: at, createdBy: uid(1), createdAt: at,
  shareholders: [{ shareholderId: uid(year + 100), setupId: uid(year), companyId, name: "Original æ eier",
    shareholderKind: "norwegian_person", nationalId: "01017012345", orgNumber: null, shareCount: 100 }],
});
const simulation = (year = 2025, mode = "simulation") => ({
  id: uid(year + 200), companyId, incomeYear: year, previewId: uid(year + 300), filing: "aksjonærregisteroppgaven",
  mode, adapterMode: "simulation", payloadHash: "a".repeat(64), idempotencyKey: uid(2), status: "receipt_stored",
  calls: [{ endpoint: "/1086H", bodyHash: "b".repeat(64), idempotencyKey: uid(3), status: "prepared", createdAt: at }],
  receiptId: "sim-original", authorityTestRunId: mode === "test_authority" ? uid(4) : null,
  feedbackDocumentIds: ["doc-original"], feedbackItems: [{ original_field: "æ", nested: [1, { camelKey: "unchanged" }] }],
  receiptMetadata: { schema_version: "original-v1", keyOrder: ["B", "a", "æ"] },
  submittedPayloadRef: { original_key: "exact-ref" },
  submittedPayload: { hovedskjemaXml: "<H>æ</H>\r\n", underskjemaXml: { "original.ID": "<U />\n" } },
  authorityConfirmedAt: at, previewConfirmedAt: at, submittedBy: uid(1), createdAt: at, updatedAt: at,
});
const preview = year => ({ id: uid(year + 300), companyId, incomeYear: year, setupId: uid(year),
  filing: "aksjonærregisteroppgaven", status: "ready", issues: [], preview: "Original æ preview",
  hovedskjemaXml: "<H>æ</H>\r\n", underskjemaXml: { "original.ID": "<U />\n" }, source: "deterministic_rf1086_engine", createdAt: at });
const evidence = id => ({ id, companyId, obligation: "aksjonaerregisteroppgaven", environment: "test", status: "passed",
  testReference: "original-test", feedbackSummary: "recorded only", receiptReference: "original-receipt",
  archiveReference: null, evidenceUrl: null, payloadHash: "c".repeat(64), recordedBy: uid(1), recordedAt: at });
const workspace = () => ({ companyId, incomeYear: null,
  simulations: [simulation(), simulation(2024)], previews: [preview(2025), preview(2024)],
  permissions: [{ id: uid(5), companyId, obligation: "aksjonaerregisteroppgaven", submitterUserId: uid(1),
    confirmedBy: uid(1), confirmedAt: at, productionEnabled: false, updatedAt: at }],
  reviewComments: [{ id: uid(6), previewId: uid(2024 + 300), companyId, target: "rf1086_preview", severity: "hard_block",
    body: "Retained older-year comment", createdBy: uid(1), acknowledgedBy: uid(1), acknowledgedAt: at, createdAt: at }],
  testEvidence: [evidence(uid(4)), evidence(uid(44))], overrides: [], approvals: [],
  productionSubmissions: [{ id: uid(8), companyId, incomeYear: 2025, status: "accepted" }], feedbackArtifacts: [], actions: [],
});

function route({ generic = {}, failures = {}, rf = workspace(), openings = [opening(2025), opening(2024)],
  user = true, token = true, mfa = true, receiptError = false, routeSource = source, rfLoader, taxFiling = {} } = {}) {
  const calls = [], readTables = [], captures = [], openingYears = [], rfYears = [];
  const ledgerProjection = presentOpeningSnapshots(openings);
  const legacy = { opening_balance_setups: ledgerProjection.setups, opening_shareholders: ledgerProjection.shareholders, ...generic };
  const supabase = {
    auth: { getUser: async () => { calls.push("user"); return { data: { user: user ? { id: uid(1) } : null } }; } },
    rpc: async name => { calls.push(name); return { data: uid(9), error: failures[name] ?? null }; },
    from(table) {
      const filters = []; let columns;
      const query = {
        select(value) { columns = value.split(",").map(v => v.trim()); return query; },
        eq(key, value) { filters.push(row => row[key] === value); return query; },
        in(key, values) { filters.push(row => values.includes(row[key])); return query; },
        then(resolve, reject) {
          calls.push(`read:${table}`); readTables.push(table);
          const data = (legacy[table] ?? []).filter(row => filters.every(filter => filter(row)))
            .map(row => Object.fromEntries(columns.map(key => [key, row[key]])));
          return Promise.resolve({ data, error: failures[table] ?? null }).then(resolve, reject);
        },
      };
      return query;
    },
  };
  const empty = async () => [];
  const dependencies = {
    "../../../../lib/company-tax-workspace-source": {
      loadPresentedCompanyTaxSource: async (access, companies, year) => {
        calls.push("read:tax-filing-api");
        assert.equal(access, "verified-owner"); assert.deepEqual(plain(companies), [companyId]);
        assert.equal(Number.isInteger(year), true);
        return { previews: [], submissions: [], overrides: [], comments: [], authorityPermissions: [], authorityTestRuns: [],
          ...taxFiling, error: failures.taxFiling ?? null };
      },
    },
    "../../../../../features/ledger": {
      loadOpeningSnapshotsForYear: async (access, company, year) => {
        calls.push("read:opening-api"); openingYears.push(year); assert.equal(access, "verified-owner");
        assert.equal(company, companyId); assert.equal(Number.isInteger(year), true);
        if (failures.opening || failures.openingYears?.[year]) throw Error("unavailable");
        return openings.filter(row => row.incomeYear === year);
      },
      presentOpeningSnapshots, loadLedgerEntriesForArchive: empty, presentLedgerEntriesForArchive: value => value,
    },
    "../../../../../features/company-tax-filing": {
      loadTaxSettlementArchiveSource: async (access, company, year) => {
        calls.push("read:tax-api");
        assert.equal(access, "verified-owner"); assert.equal(company, companyId);
        assert.equal(Number.isInteger(year), true);
        return { data: (generic.holding_actions ?? []).filter(row => row.company_id === company && row.income_year === year),
          error: failures.tax ?? null };
      },
    },
    "../../../../../features/shareholder-register-filing": { ...rfPresentation,
      loadRf1086ArchiveSource: async (access, company, year) => {
        calls.push("read:rf-api"); rfYears.push(year); assert.equal(access, "verified-owner");
        assert.equal(company, companyId); assert.equal(Number.isInteger(year), true);
        if (failures.rf) throw Error("unavailable");
        if (rfLoader) return rfLoader(access, company, year);
        const simulations = rf.simulations.filter(row => row.incomeYear === year);
        const evidenceIds = new Set(simulations.map(row => row.authorityTestRunId).filter(Boolean));
        return { companyId: company, incomeYear: year, simulations,
          previews: rf.previews.filter(row => row.incomeYear === year),
          reviewComments: rf.reviewComments, permissions: rf.permissions,
          testEvidence: rf.testEvidence.filter(row => evidenceIds.has(row.id)) };
      },
    },
    "../../../../../features/investments": Object.fromEntries([
      ...["loadInvestmentAcquisitionLots", "loadInvestmentActivity", "loadInvestmentPositions", "loadInvestmentShareSaleAllocations", "loadInvestmentCorrections"].map(key => [key, empty]),
      ...["effectiveInvestmentActivity", "presentAcquisitionLots", "presentInvestmentActivity", "presentInvestmentPositions", "presentShareSaleAllocations", "presentInvestmentCorrections"].map(key => [key, value => value]),
    ]),
    "../../../../../features/documents": { loadDocumentBackupProjection: async (_access, _company, incomeYear) => ({ companyId, incomeYear, objects: [] }) },
    "../../../../../features/corporate-governance": { listCorporateDecisionLifecycle: async () => ({ corporateDecisions: [], corporateDocumentSets: [], corporateDocumentArtifacts: [], corporateDocumentEvents: [], corporateDecisionFinalizations: [] }), listSupportedCorporateEvents: empty },
    "../../../../../features/billing": { loadBillingSnapshot: async () => ({ accounts: [] }), presentBillingAccount: value => value },
    "../../../../lib/archive": { firstArchiveSourceError: results => results.find(result => result.error)?.error ?? null,
      buildPersistedCompanyArchive: value => { calls.push("build"); captures.push(value); return { originalArchiveInput: value }; } },
    "../../../../lib/company-access-context": { loadAcceptedMembershipCompany: async () => ({ id: companyId, org_number: "923456789", name: "Synthetic AS" }) },
    "../../../../lib/security": { requireStepUpForAction: async () => { calls.push("mfa"); if (!mfa) throw Error("step-up"); } },
    "../../../../lib/supabase/auth-session": { getCurrentSessionAccessToken: async () => token ? "verified-owner" : null },
    "../../../../lib/supabase/server": { createSupabaseServerClient: async () => supabase,
      createSupabaseServiceRoleClient: () => ({ rpc: async (name, args) => { calls.push(name);
        assert.equal(name, "company_archive_complete_export"); assert.equal(args.p_attempt_id, uid(9));
        assert.equal(args.p_archive_sha256, createHash("sha256").update(JSON.stringify({ originalArchiveInput: captures.at(-1) }, null, 2)).digest("hex"));
        return { error: receiptError ? Error("denied") : null }; } }) },
  };
  const exports = {};
  vm.runInNewContext(ts.transpileModule(routeSource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText,
    { exports, require: id => id in dependencies ? dependencies[id] : require(id), Response, Request, Error, Set, Map });
  return { calls, captures, readTables, openingYears, rfYears,
    run: (incomeYear = 2025) => exports.GET(new Request("https://talli.example/archive"), { params: Promise.resolve({ companyId, incomeYear: String(incomeYear) }) }) };
}

// Captured original query chains at 91b before removing the two wholly owned opening reads.
const ORIGINAL_MIXED_CHAINS = [
  {
    "table": "filing_submissions",
    "expression": "supabase .from(\"filing_submissions\") .select(\"id, preview_id, authority_test_run_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by\") .eq(\"company_id\", companyId) .eq(\"income_year\", incomeYear)"
  },
  {
    "table": "authority_test_runs",
    "expression": "supabase .from(\"authority_test_runs\") .select(\"id, company_id, obligation, environment, status, test_reference, feedback_summary, receipt_reference, archive_reference, evidence_url, payload_hash, recorded_by, recorded_at\") .in(\"id\", authorityTestRunIds)"
  },
  {
    "table": "filing_previews",
    "expression": "supabase .from(\"filing_previews\") .select(\"id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at\") .eq(\"company_id\", companyId) .eq(\"income_year\", incomeYear)"
  },
  {
    "table": "holding_actions",
    "expression": "supabase .from(\"holding_actions\") .select(\"id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at\") .eq(\"company_id\", companyId) .eq(\"income_year\", incomeYear)"
  },
  {
    "table": "authority_permissions",
    "expression": "supabase .from(\"authority_permissions\") .select(\"id, company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled, updated_at\") .eq(\"company_id\", companyId)"
  },
  {
    "table": "filing_review_comments",
    "expression": "supabase .from(\"filing_review_comments\") .select(\"id, preview_id, company_id, target, severity, body, created_by, acknowledged_by, acknowledged_at, created_at\") .eq(\"company_id\", companyId)"
  },
  {
    "table": "audit_events",
    "expression": "supabase .from(\"audit_events\") .select(\"id, company_id, actor_id, category, action, message, created_at\") .eq(\"company_id\", companyId)"
  },
  {
    "table": "bank_suggestion_acceptances",
    "expression": "supabase .from(\"bank_suggestion_acceptances\") .select(\"id, company_id, bank_transaction_id, ledger_entry_id, rule_id, rule_version, reason, lines, accepted_by, accepted_at\") .eq(\"company_id\", companyId)"
  }
];
function queryChains(text) {
  const parsed = ts.createSourceFile("route.ts", text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const printer = ts.createPrinter({ removeComments: true });
  const chains = [];
  function visit(node) {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "from") {
      let outer = node;
      while (ts.isPropertyAccessExpression(outer.parent) && ts.isCallExpression(outer.parent.parent) && outer.parent.parent.expression === outer.parent) outer = outer.parent.parent;
      chains.push({ table: node.arguments[0].text, expression: printer.printNode(ts.EmitHint.Expression, outer, parsed).replace(/\s+/gu, " ") });
    }
    ts.forEachChild(node, visit);
  }
  visit(parsed);
  return chains;
}

test("archive preserves frozen mixed chains except the exact owned RF and Tax read retirements", () => {
  assert.deepEqual(queryChains(source), ORIGINAL_MIXED_CHAINS.filter(chain => chain.table !== "holding_actions"));
  assert.equal(source.includes('.from("holding_actions")'), false);
  assert.equal(source.includes('.from("opening_balance_setups")'), false);
  assert.equal(source.includes('.from("opening_shareholders")'), false);
});

test("archive preserves original selected opening and shareholder fields through the joined owner projection", async () => {
  const fixture = route(); const response = await fixture.run(); assert.equal(response.status, 200);
  const input = fixture.captures[0];
  assert.deepEqual(plain(input.setups), [{ id: uid(2025), company_id: companyId, income_year: 2025, bank_balance: 30001.25,
    share_capital: 30000, share_count: 100, nominal_value: 300, locked_at: at, created_by: uid(1) }]);
  assert.deepEqual(plain(input.shareholders), [{ id: uid(2125), setup_id: uid(2025), company_id: companyId, name: "Original æ eier",
    shareholder_kind: "norwegian_person", national_id: "01017012345", org_number: null, share_count: 100 }]);
  assert.deepEqual(fixture.calls.filter(call => call === "read:opening-api"), ["read:opening-api"]);
  assert.deepEqual(fixture.openingYears, [2025]);
  assert.equal(fixture.calls.at(-1), "company_archive_complete_export");
  assert.ok(fixture.calls.indexOf("build") > fixture.calls.lastIndexOf("read:opening-api"));
});

test("a failing 2024 opening does not prevent a valid 2025 archive but still blocks the 2024 export", async () => {
  const options = { failures: { openingYears: { 2024: Error("historical opening unavailable") } } };
  const valid = route(options);
  assert.equal((await valid.run(2025)).status, 200);
  assert.deepEqual(valid.openingYears, [2025]);
  assert.deepEqual(plain(valid.captures[0].setups).map(row => row.income_year), [2025]);
  assert.deepEqual(plain(valid.captures[0].shareholders).map(row => row.setup_id), [uid(2025)]);
  assert.equal(valid.calls.at(-1), "company_archive_complete_export");

  const unavailable = route(options);
  assert.equal((await unavailable.run(2024)).status, 500);
  assert.deepEqual(unavailable.openingYears, [2024]);
  assert.equal(unavailable.captures.length, 0);
  assert.equal(unavailable.calls.includes("company_archive_complete_export"), false);
});

test("RF-only archive preserves original nested payload identities, requested year and company-wide history", async () => {
  const rf = workspace(); const fixture = route({ rf }); assert.equal((await fixture.run()).status, 200);
  const input = fixture.captures[0], original = rf.simulations[0];
  assert.equal(input.filingSubmissions.length, 1); assert.equal(input.filingPreviews.length, 1);
  assert.equal(input.filingSubmissions[0].submitted_payload, original.submittedPayload);
  assert.deepEqual(plain(input.filingSubmissions[0]), plain(rfPresentation.presentRf1086Simulation(original)));
  assert.deepEqual(plain(input.reviewComments), [rfPresentation.presentRf1086ReviewComment(workspace().reviewComments[0])]);
  assert.equal(input.reviewComments[0].preview_id, uid(2324));
  assert.equal(input.authorityPermissions.length, 1); assert.deepEqual(plain(input.authorityTestRuns), []);
  assert.equal("productionSubmissions" in input, false); assert.equal("feedbackArtifacts" in input, false);
  assert.equal(fixture.readTables.includes("authority_test_runs"), false);
  assert.deepEqual(fixture.rfYears, [2025]);
});

test("actual generated RF archive transport isolates a malformed 2024 preview from the valid 2025 download", async (t) => {
  const previousUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  t.after(() => {
    if (previousUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = previousUrl;
  });
  const queries = [];
  t.mock.method(globalThis, "fetch", async (url, request) => {
    const parsed = new URL(url), year = Number(parsed.searchParams.get("incomeYear"));
    assert.equal(parsed.pathname, "/api/v1/shareholder-register-filings/archive-source");
    assert.deepEqual([...parsed.searchParams.entries()].sort(), [["companyId", companyId], ["incomeYear", String(year)]]);
    assert.equal(new Headers(request.headers).get("Authorization"), "Bearer verified-owner");
    assert.equal(request.cache, "no-store");
    queries.push(year);
    const row = preview(year);
    if (year === 2024) row.issues = [{ level: "warning", message: "Retained historical issue without a code" }];
    return Response.json({ companyId, incomeYear: year, previews: [row],
      simulations: [{ ...simulation(year), calls: [], feedbackItems: [], receiptMetadata: null,
        submittedPayloadRef: null, submittedPayload: null }],
      reviewComments: workspace().reviewComments, permissions: workspace().permissions, testEvidence: [] });
  });
  const valid = route({ rfLoader: loadRf1086ArchiveSource });
  assert.equal((await valid.run(2025)).status, 200);
  assert.deepEqual(valid.rfYears, [2025]);
  assert.deepEqual(plain(valid.captures[0].filingPreviews).map(row => row.income_year), [2025]);
  assert.deepEqual(plain(valid.captures[0].reviewComments), [rfPresentation.presentRf1086ReviewComment(workspace().reviewComments[0])]);
  assert.equal(valid.calls.at(-1), "company_archive_complete_export");

  const malformed = route({ rfLoader: loadRf1086ArchiveSource });
  assert.equal((await malformed.run(2024)).status, 500);
  assert.equal(malformed.captures.length, 0);
  assert.equal(malformed.calls.includes("company_archive_complete_export"), false);
  assert.deepEqual(queries, [2025, 2024]);
});

test("RF authority evidence is limited to retained submission references without adding a generic persistence call", async () => {
  const rf = workspace(); rf.simulations = [simulation(2025, "test_authority")];
  const fixture = route({ rf }); assert.equal((await fixture.run()).status, 200);
  assert.deepEqual(plain(fixture.captures[0].authorityTestRuns), [rfPresentation.presentRf1086TestEvidence(evidence(uid(4)))]);
  assert.equal(fixture.readTables.includes("authority_test_runs"), false);
});

test("mixed sibling chains retain their conditional authority read and overlap never duplicates RF rows", async () => {
  const rf = workspace(), rfRow = rfPresentation.presentRf1086Simulation(rf.simulations[0]);
  const sibling = { ...rfRow, id: uid(70), filing: "skattemelding", mode: "test_authority", authority_test_run_id: uid(71) };
  const siblingEvidence = { ...rfPresentation.presentRf1086TestEvidence(evidence(uid(71))), obligation: "skattemelding" };
  const fixture = route({ rf, generic: { filing_submissions: [rfRow, sibling], authority_test_runs: [siblingEvidence] } });
  assert.equal((await fixture.run()).status, 200);
  assert.deepEqual(fixture.readTables.slice(0, 2), ["filing_submissions", "authority_test_runs"]);
  assert.equal(fixture.captures[0].filingSubmissions.length, 2);
  assert.deepEqual(plain(fixture.captures[0].filingSubmissions[1]), sibling);
  assert.deepEqual(plain(fixture.captures[0].authorityTestRuns), [siblingEvidence]);
});

for (const failure of ["rf", "opening", "tax", "taxFiling", "filing_previews", "authority_permissions", "filing_review_comments", "audit_events"]) {
  test(`unavailable ${failure} source cannot complete the authoritative export`, async () => {
    const fixture = route({ failures: { [failure]: Error("unavailable") } });
    assert.equal((await fixture.run()).status, 500);
    assert.equal(fixture.captures.length, 0); assert.equal(fixture.calls.includes("company_archive_complete_export"), false);
  });
}

test("original submission and authority errors retain priority and effect order", async () => {
  const first = route({ failures: { filing_submissions: true, rf: true } });
  assert.equal(await (await first.run()).text(), "Kunne ikke lese innsendingsgrunnlaget");
  assert.equal(first.calls.includes("read:rf-api"), false);
  const sibling = { ...rfPresentation.presentRf1086Simulation(simulation(2025, "test_authority")), filing: "skattemelding" };
  const second = route({ generic: { filing_submissions: [sibling] }, failures: { authority_test_runs: true, rf: true } });
  assert.equal(await (await second.run()).text(), "Kunne ikke lese myndighetsdokumentasjonen");
  assert.equal(second.calls.includes("read:opening-api"), false);
});

for (const options of [{ user: false }, { token: false }, { mfa: false }]) {
  test(`authentication and step-up precede every source and export effect ${JSON.stringify(options)}`, async () => {
    const fixture = route(options); assert.ok([401, 403].includes((await fixture.run()).status));
    assert.equal(fixture.calls.includes("company_archive_begin_export"), false); assert.deepEqual(fixture.readTables, []);
  });
}

test("empty retained history still rejects export and failed receipt never yields a downloadable archive", async () => {
  const rf = workspace(); rf.simulations = [];
  const empty = route({ rf }); assert.equal((await empty.run()).status, 409); assert.equal(empty.captures.length, 0);
  const denied = route({ receiptError: true }); const response = await denied.run();
  assert.equal(response.status, 409); assert.equal(response.headers.get("content-disposition"), null);
});


test("owned Tax source preserves all thirteen original fields beside unchanged RF history", async () => {
  const row = { id: uid(90), company_id: companyId, income_year: 2025, action_type: "tax_settlement",
    action_date: "2025-09-01", payload: { amount: 125.5, settlement_type: "payment", original_extra: { retained: [1, "æ"] } },
    ledger_entry_id: uid(91), bank_transaction_id: uid(92), document_id: uid(93), risk_level: "ready",
    blocker_code: null, created_by: uid(1), created_at: "2025-09-01T10:11:12.123456+00:00" };
  const fixture = route({ generic: { holding_actions: [row] } });
  assert.equal((await fixture.run()).status, 200);
  assert.deepEqual(plain(fixture.captures[0].holdingActions), [row]);
  assert.equal(fixture.readTables.includes("holding_actions"), false);
  assert.equal(fixture.calls.filter(call => call === "read:tax-api").length, 1);
  assert.equal(fixture.calls.at(-1), "company_archive_complete_export");
});


test("owned Tax filing preserves nested payload and only linked evidence inside the Archive generation boundary", async () => {
  const rf = workspace(); rf.simulations = []; rf.previews = []; rf.reviewComments = []; rf.permissions = [];
  const submission = { ...rfPresentation.presentRf1086Simulation(simulation(2025, "test_authority")),
    id: uid(152), filing: "skattemelding for AS", adapter_mode: "test_authority", status: "feedback_ready",
    authority_test_run_id: uid(153), submitted_payload: { original: { immutable: ["æ", 2025] } } };
  const permission = { id: uid(155), company_id: companyId, obligation: "skattemelding", production_enabled: false };
  const taxEvidence = { ...rfPresentation.presentRf1086TestEvidence(evidence(uid(153))), obligation: "skattemelding", status: "pending" };
  const fixture = route({ rf, taxFiling: { submissions: [submission], authorityPermissions: [permission],
    authorityTestRuns: [taxEvidence, { ...taxEvidence, id: uid(154), test_reference: "unrelated" }] } });
  assert.equal((await fixture.run()).status, 200);
  assert.deepEqual(plain(fixture.captures[0].filingSubmissions), [submission]);
  assert.deepEqual(plain(fixture.captures[0].authorityTestRuns), [taxEvidence]);
  assert.deepEqual(plain(fixture.captures[0].authorityPermissions), [permission]);
  assert.equal(fixture.captures[0].filingSubmissions[0].submitted_payload, submission.submitted_payload);
  assert.ok(fixture.calls.indexOf("read:tax-filing-api") > fixture.calls.indexOf("company_archive_begin_export"));
  assert.ok(fixture.calls.indexOf("read:tax-filing-api") < fixture.calls.indexOf("company_archive_complete_export"));
  assert.equal(fixture.readTables.includes("authority_test_runs"), false);
});
