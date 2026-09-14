import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
function module(source, dependencies = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  } }).outputText, { exports, require: () => dependencies });
  return exports;
}
const presenters = module(read("../apps/web/features/company-tax-filing/presentation.ts"));
const plain = value => JSON.parse(JSON.stringify(value));
const capture = JSON.parse(read("../architecture/evidence/issues/152/legacy-characterization.json"));
const imports = Object.values(capture).find(value => Array.isArray(value) && value.some(item => item.output?.value?.submission));
const wire = row => Object.fromEntries(Object.entries(row).map(([key,value]) => [key.replace(/_([a-z])/gu, (_, letter) => letter.toUpperCase()), value]));
const completeSubmission = row => ({ id: "submission", preview_id: null, authority_test_run_id: "evidence", setup_id: null,
  authority_confirmed_by: null, authority_confirmed_at: null, preview_confirmed_by: null, preview_confirmed_at: null,
  created_at: row.updated_at, ...row });
const positiveImports = imports.filter(item => item.output?.value?.submission);
for (const fixture of positiveImports) {
  test(`stored Tax receipt remains byte-equivalent after wire presentation: ${fixture.id}`, () => {
    const row = completeSubmission(fixture.output.value.submission);
    assert.deepEqual(plain(presenters.presentCompanyTaxSubmission(wire(row))), row);
  });
}
const row = completeSubmission(positiveImports[0].output.value.submission);
test("nested receipt, call, feedback and payload-reference extension fields survive presentation", () => {
  const extended = structuredClone(row);
  for (const value of [extended.receipt_metadata, extended.calls[0], extended.feedback_items[0], extended.submitted_payload_ref]) {
    value.extension = { retained: [null, "value", 42] };
  }
  assert.deepEqual(plain(presenters.presentCompanyTaxSubmission(wire(extended))), extended);
});
function load(query) {
  return module(read("../apps/web/app/lib/company-tax-workspace-source.ts"), {
    ...presenters, loadCompanyTaxFilingWorkspace: query,
  }).loadPresentedCompanyTaxSource;
}
const empty = () => ({ previews: [], submissions: [], overrides: [], reviewComments: [], permissions: [], testEvidence: [] });
const unavailable = { error: "Skattemeldingsgrunnlaget kunne ikke leses. Prøv igjen.", previews: [], submissions: [], overrides: [], comments: [], authorityPermissions: [], authorityTestRuns: [] };
test("one query per company supplies the complete source and keeps omitted year unscoped", async () => {
  const calls = [];
  const readSource = load(async (...args) => { calls.push(args); return { ...empty(), submissions: [wire(row)] }; });
  const source = await readSource("token", ["first", "second"]);
  assert.deepEqual(calls, [["token", "first", null], ["token", "second", null]]);
  assert.equal(source.error, null);
  assert.equal(source.submissions.length, 2);
  calls.length = 0;
  await readSource("token", ["first"], 2024);
  assert.deepEqual(calls, [["token", "first", 2024]]);
});
test("one unavailable company discards partial results and retains an explicit error", async () => {
  const source = await load(async (_, company) => {
    if (company === "second") throw new Error("private upstream details");
    return { ...empty(), submissions: [wire(row)] };
  })("token", ["first", "second"], 2025);
  assert.deepEqual(plain(source), unavailable);
});
for (const [name, mutate] of [
  ["receipt type", value => value.receiptMetadata.contentType = "application/json"],
  ["receipt hash", value => delete value.receiptMetadata.contentSha256],
  ["feedback classification", value => value.feedbackItems[0].severity = "unknown"],
  ["payload reference", value => value.submittedPayloadRef.incomeYear = "2025"],
  ["call chronology", value => delete value.calls[0].created_at],
  ["unsupported raw payload", value => value.submittedPayload = { raw: "content" }],
]) {
  test(`incomplete ${name} fails the whole source visibly`, async () => {
    const submission = structuredClone(wire(row));
    mutate(submission);
    const source = await load(async () => ({ ...empty(), submissions: [submission] }))("token", ["company"], 2025);
    assert.deepEqual(plain(source), unavailable);
  });
}

function functionFrom(path, name, dependencies) {
  const source = read(path);
  const parsed = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
  const node = parsed.statements.find(value => ts.isFunctionDeclaration(value) && value.name?.text === name);
  assert.ok(node, name);
  const code = ts.transpileModule(node.getText(parsed).replace("export async", "async"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
  }).outputText;
  return new Function(...Object.keys(dependencies), `${code}\nreturn ${name};`)(...Object.values(dependencies));
}
const compose = (existing, owned) => [...new Map([...existing, ...owned].map(row => [row.id, row])).values()];
function consumerSetup(failed = false) {
  const effects = [];
  const taxSource = { error: failed ? "Tax unavailable" : null,
    previews: [{ id: "tax-preview" }], submissions: [{ id: "tax-submission", mode: "test_authority", authority_test_run_id: "linked" }],
    comments: [{ id: "tax-comment" }], overrides: [{ id: "tax-override" }],
    authorityPermissions: [{ id: "tax-permission", company_id: "company", obligation: "skattemelding" }],
    authorityTestRuns: [{ id: "linked" }, { id: "unrelated-year" }],
  };
  const rfSource = { error: null, previews: [], submissions: [], comments: [], overrides: [], authorityPermissions: [], authorityTestRuns: [] };
  const supabase = {
    auth: { getUser: async () => ({ data: { user: { id: "owner" } } }) },
    rpc: async (name, body) => { effects.push({ name, body }); return { data: "attempt", error: null }; },
    from(table) {
      let mutation;
      const chain = new Proxy({}, { get(_, key) {
        if (key === "then") return resolve => {
          if (mutation) effects.push({ name: table, body: mutation });
          resolve({ data: table === "annual_data" ? null : [], error: null });
        };
        return body => { if (["insert", "upsert"].includes(key)) mutation = body; return chain; };
      } });
      return chain;
    },
  };
  const dependencies = {
    createSupabaseServerClient: async () => supabase, createSupabaseServiceRoleClient: () => supabase,
    getCurrentSessionAccessToken: async () => "token", requireStepUpForAction: async () => {},
    loadAcceptedMembershipCompany: async () => ({ id: "company", org_number: "123456789" }),
    loadPresentedCompanyTaxSource: async (...args) => { effects.push({ name: "tax-query", body: args }); return taxSource; },
    loadPresentedRf1086Source: async () => rfSource,
    loadArchiveRf1086: async () => ({ error: null, data: { submissions: [], previews: [], permissions: [], comments: [], testEvidence: [] } }),
    loadArchiveOpeningSnapshots: async () => ({ data: [], shareholders: [], error: null }),
    loadArchiveLedgerEntries: async () => ({ data: [], error: null }),
    loadArchiveDocuments: async () => ({ data: [], error: null }),
    loadTaxSettlementArchiveSource: async () => ({ data: [], error: null }),
    loadArchiveBilling: async () => ({ data: [], error: null }),
    loadArchiveInvestments: async () => ({ data: null, error: null }),
    loadArchiveCorporateLifecycle: async () => ({ data: null, error: null }),
    firstArchiveSourceError: results => results.find(item => item.error),
    mergeArchiveRfRows: compose, effectiveInvestmentActivity: value => value,
    buildPersistedCompanyArchive: value => { effects.push({ name: "archive", body: value }); return value; },
    createHash: () => ({ update: () => ({ digest: () => "synthetic-hash" }) }),
    hasSupabaseEnv: () => true, formString: (data,key) => data.get(key) ?? "",
    listOpeningSetups: async () => ({ setups: [], error: null }),
    listLedgerEntries: async () => ({ entries: [], error: null }),
    listPresentedInvestmentActivity: async () => ({ actions: [], error: null }),
    listPresentedInvestmentCorrections: async () => ({ corrections: [], error: null }),
    listBankTransactions: async () => ({ transactions: [], error: null }),
    listDocumentsForCompanies: async () => ({ documents: [], error: null }),
    listPeriodLocks: async () => ({ locks: [], error: null }),
    loadAnnualBillingEntitlements: async () => ({}), billingActionErrorMessage: () => "Billing unavailable",
    composeFilingSources: compose, readCorporateDecisionReadiness: async () => ({}),
    evaluateAnnualReadinessGates: value => { effects.push({ name: "readiness", body: value }); return []; },
    revalidatePath: () => {}, returnTarget: () => "/workspace", redirect: url => { throw new Error(`redirect:${url}`); },
  };
  return { effects, dependencies, taxSource };
}
test("Archive includes Tax-only submissions and only their linked evidence for the requested year", async () => {
  const { effects, dependencies, taxSource } = consumerSetup();
  const get = functionFrom("../apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts", "GET", dependencies);
  const response = await get(new Request("https://example.test/archive"), { params: Promise.resolve({ companyId: "company", incomeYear: "2024" }) });
  assert.equal(response.status, 200);
  const archive = effects.find(item => item.name === "archive").body;
  assert.deepEqual(archive.filingSubmissions, taxSource.submissions);
  assert.deepEqual(archive.filingPreviews, taxSource.previews);
  assert.deepEqual(archive.reviewComments, taxSource.comments);
  assert.deepEqual(archive.authorityPermissions, taxSource.authorityPermissions);
  assert.deepEqual(archive.authorityTestRuns, [{ id: "linked" }]);
  assert.deepEqual(effects.find(item => item.name === "tax-query").body, ["token", ["company"], 2024]);
  assert.equal(effects.filter(item => item.name === "company_archive_complete_export").length, 1);
});
test("Archive source failure returns unavailable before building an archive or recording a receipt", async () => {
  const { effects, dependencies } = consumerSetup(true);
  const get = functionFrom("../apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts", "GET", dependencies);
  const response = await get(new Request("https://example.test/archive"), { params: Promise.resolve({ companyId: "company", incomeYear: "2025" }) });
  assert.equal(response.status, 500);
  assert.equal(effects.some(item => ["archive", "company_archive_complete_export"].includes(item.name)), false);
});
for (const failed of [false, true]) test(`readiness refresh ${failed ? "stops without snapshot or Audit writes on Tax failure" : "uses every owned Tax readiness family"}`, async () => {
  const { effects, dependencies, taxSource } = consumerSetup(failed);
  const refresh = functionFrom("../apps/web/app/actions.ts", "refreshAnnualReadinessSnapshots", dependencies);
  const form = new FormData(); form.set("companyId", "company"); form.set("incomeYear", "2024");
  await assert.rejects(refresh(form), /redirect:/u);
  assert.deepEqual(effects.find(item => item.name === "tax-query").body, ["token", ["company"], 2024]);
  if (failed) {
    assert.equal(effects.some(item => ["readiness", "filing_readiness_snapshots", "audit_events"].includes(item.name)), false);
  } else {
    const input = effects.find(item => item.name === "readiness").body;
    assert.deepEqual(input.overrides, taxSource.overrides);
    assert.deepEqual(input.filingPreviews, taxSource.previews);
    assert.deepEqual(input.filingSubmissions, taxSource.submissions);
    assert.deepEqual(input.authorityPermissions, taxSource.authorityPermissions);
    assert.equal(effects.filter(item => item.name === "filing_readiness_snapshots").length, 1);
    assert.equal(effects.filter(item => item.name === "audit_events").length, 1);
  }
});

test("missing session token cannot turn an authorized company scope into complete empty Tax data", async () => {
  let calls = 0;
  const readSource = load(async () => { calls += 1; return empty(); });
  assert.deepEqual(plain(await readSource(null, ["company"], 2025)), unavailable);
  assert.deepEqual(plain(await readSource(null, [])), { ...unavailable, error: null });
  assert.equal(calls, 0);
});
