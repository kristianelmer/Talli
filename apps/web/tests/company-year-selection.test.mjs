import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(path, dependencies) {
  const exports = {};
  const source = readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText, {exports, URL, URLSearchParams, process:{env:{NODE_ENV:"production"}}, require(name) {
    if (name in dependencies) return dependencies[name];
    if (name === "node:crypto" || name === "react/jsx-runtime") return require(name);
    if (dependencies["*"]) return dependencies["*"];
    throw new Error(`Unexpected dependency: ${name}`);
  }});
  return exports;
}

function continuationHarness() {
  let value;
  let options;
  const module = compile("lib/eligibility-continuation.ts", {"next/headers": {
    cookies: async () => ({
      get: () => value === undefined ? undefined : {value},
      set: (_name, content, config) => {value=content;options=config;},
      delete: () => {value=undefined;},
    }),
  }});
  return {module, raw: raw => {value=raw;}, options: () => options};
}

function continuation(year) {
  return {orgNumber:"992803750",companyName:"Synthetic private fixture",accountingYear:year,
    publicFactsSha256:"a".repeat(64),capabilityManifestVersion:`${year}.1`,capabilityManifestSha256:"b".repeat(64),
    answers:{ordinary_holding:"yes"},answersSha256:"c".repeat(64),reconstructFrom:`${year}-01-01`,
    onlyAccountingAndFilingProduct:true,customerClaims:Array.from({length:12},(_,i)=>`Claim ${i}`)};
}

test("both company years survive the real private continuation cookie with year-bound dates and versions", async () => {
  const {module,options}=continuationHarness();
  for (const year of [2025,2026]) {
    const value=continuation(year);
    await module.setEligibilityContinuation(value);
    assert.deepEqual(JSON.parse(JSON.stringify(await module.readEligibilityContinuation())),value);
    assert.equal(options().httpOnly,true);
    assert.equal(options().secure,true);
    assert.equal(options().sameSite,"lax");
  }
});

test("cross-year or unsupported continuation evidence cannot resume an admission", async () => {
  const {module,raw}=continuationHarness();
  for (const mutation of [{accountingYear:2024},{capabilityManifestVersion:"2026.1"},
    {reconstructFrom:"2026-01-01"},{capabilityManifestSha256:"bad"},{unexpectedAuthority:true}]) {
    raw(JSON.stringify({...continuation(2025),...mutation}));
    assert.equal(await module.readEligibilityContinuation(),null);
  }
});

test("public precheck and interview actions forward the selected year instead of silently choosing 2026", async () => {
  for (const year of [2025,2026]) {
    const harness=continuationHarness();
    const calls=[];
    const value=continuation(year);
    const result={decision:"supported",provisional:false,accountingYear:year,
      publicFacts:{orgNumber:value.orgNumber,name:value.companyName},
      publicFactsSha256:value.publicFactsSha256,capabilityManifestVersion:value.capabilityManifestVersion,
      capabilityManifestSha256:value.capabilityManifestSha256,answers:value.answers,answersSha256:value.answersSha256,
      companyYearPromise:{reconstructionRequiredFrom:value.reconstructFrom,onlyAccountingAndFilingProduct:true,
        customerClaims:value.customerClaims}};
    const actions=compile("sjekk-selskapet/actions.ts", {
      "../../features/company-access": {
        precheckCompanyEligibility: async input => {calls.push(input);return result;},
        assessCompanyEligibility: async input => {calls.push(input);return result;},
        eligibilityActionErrorMessage: () => "Unavailable",
      },
      "../lib/eligibility-continuation":harness.module,
    });
    const form=new FormData();form.set("orgNumber",value.orgNumber);form.set("accountingYear",String(year));
    form.set("publicFactsSha256",value.publicFactsSha256);form.set("capabilityManifestVersion",value.capabilityManifestVersion);
    form.set("capabilityManifestSha256",value.capabilityManifestSha256);form.append("questionCode","ordinary_holding");
    form.set("answer:ordinary_holding","yes");
    await actions.precheckEligibilityAction({},form);
    const outcome=await actions.definitiveEligibilityAction({},form);
    assert.equal(outcome.error,undefined);
    assert.equal(calls.length,2);
    assert.ok(calls.every(call=>call.accountingYear===year));
    assert.equal((await harness.module.readEligibilityContinuation()).accountingYear,year);
    form.set("accountingYear","2024");
    const refused=await actions.precheckEligibilityAction({},form);
    assert.ok(refused.error);
    assert.equal(calls.length,2);
  }
});

test("owner material-answer updates select the submitted year and cannot update a different admission", async () => {
  for (const year of [2025, 2026]) {
    for (const returnedYear of [2025, 2026]) {
      const calls = [];
      const actions = compile("(owner)/selskapsgrense/actions.ts", {
        "next/cache": { revalidatePath() {} },
        "next/navigation": { redirect(url) { throw new Error(`REDIRECT:${url}`); } },
        "../../../features/company-access/index.ts": {
          eligibilityActionErrorMessage: () => "Unavailable",
          recheckCompanyYearEligibilityThroughApi: async (_token, admission, command) => {
            calls.push(["recheck", admission, command]);
            return { decision: "supported" };
          },
        },
        "../../lib/company-access-context": {
          listCompanyAccessContexts: async options => {
            calls.push(["context", options]);
            return { error: null, companies: [{
              id: "10000000-0000-4000-8000-000000000001",
              admittedAccountingYear: returnedYear,
              companyYearAdmissionId: `admission-${returnedYear}`,
            }] };
          },
        },
        "../../lib/supabase/auth-session": { getCurrentSessionAccessToken: async () => "session-token" },
      });
      const form = new FormData();
      form.set("companyId", "10000000-0000-4000-8000-000000000001");
      form.set("accountingYear", String(year));
      form.append("questionCode", "is_small_enterprise");
      form.set("answer:is_small_enterprise", "yes");
      await assert.rejects(actions.recheckMaterialCompanyYearAnswers(form), error => {
        assert.ok(error.message.startsWith("REDIRECT:/selskapsgrense?"), error.message);
        const params = new URL(error.message.slice("REDIRECT:".length), "https://test.invalid").searchParams;
        assert.equal(params.get("accountingYear"), String(year));
        assert.equal(params.get("result"), year === returnedYear ? "supported" : null);
        return true;
      });
      assert.equal(calls[0][1].accountingYear, year);
      assert.equal(calls.filter(([kind]) => kind === "recheck").length, year === returnedYear ? 1 : 0);
      if (year === returnedYear) assert.equal(calls[1][1], `admission-${year}`);
    }
  }
});


test("default owner navigation keeps a 2025-only admission instead of redirecting to the free check", async () => {
  for (const requestedYear of [undefined, "2025", "2026"]) {
    const calls = [];
    const { default: Page } = compile("(owner)/selskapsgrense/page.tsx", {
      "next/link": { default() {} },
      "next/navigation": {
        redirect(url) { throw new Error(`REDIRECT:${url}`); },
        notFound() { throw new Error("NOT_FOUND"); },
      },
      "../../../features/company-access/index.ts": {
        eligibilityActionErrorMessage: () => "Unavailable",
        precheckCompanyEligibility: async input => {
          calls.push(["precheck", input]);
          return { questions: [], reasonExplanations: [], nextStep: "Check" };
        },
      },
      "../../components/ui": { Banner() {} },
      "../../lib/company-access-context": {
        listCompanyAccessContexts: async options => {
          calls.push(["context", options]);
          const admitted = options.accountingYear === undefined || options.accountingYear === 2025;
          return { error: null, companies: [{
            id: "10000000-0000-4000-8000-000000000001", name: "Synthetic private fixture",
            org_number: "992803750", companyYearAdmissionId: admitted ? "admission-2025" : null,
            admittedAccountingYear: admitted ? 2025 : null,
          }] };
        },
      },
      "../../actions": { refreshCompanyYearEligibilityGate() {} },
      "../../sjekk-selskapet/EligibilityChecker": { EligibilityInterview() {} },
      "../../sjekk-selskapet/eligibility.module.css": { default: {} },
      "./actions": { recheckMaterialCompanyYearAnswers() {} },
    });
    const props = { searchParams: Promise.resolve(requestedYear ? { accountingYear: requestedYear } : {}) };
    if (requestedYear === "2026") {
      await assert.rejects(Page(props), /REDIRECT:\/sjekk-selskapet/u);
      assert.equal(calls.length, 1);
    } else {
      const page = await Page(props);
      assert.ok(page);
      assert.equal(calls[1][1].accountingYear, 2025);
    }
    assert.deepEqual(JSON.parse(JSON.stringify(calls[0][1])), requestedYear ? { accountingYear: Number(requestedYear) } : {});
  }
});

test("adding 2025 opens its balances even when the same company already has a 2026 setup", async () => {
  const companyId = "10000000-0000-4000-8000-000000000001";
  for (const year of [2025, 2026]) {
    const calls = [];
    function OpeningBalanceForm() {}
    const { default: Page } = compile("(owner)/onboarding/page.tsx", {
      "next/navigation": {
        redirect(url) { throw new Error(`REDIRECT:${url}`); },
        notFound() { throw new Error("NOT_FOUND"); },
      },
      "../../components/ui": { Banner() {}, WizardShell() {} },
      "../../lib/copy": { ownerCopy: { onboarding: {
        steps: { company: "Company", balances: "Balances", bank: "Bank" },
        lookup: {}, balances: {}, bank: {},
      } } },
      "../../lib/eligibility-continuation": { readEligibilityContinuation: async () => null },
      "../../lib/onboarding-presentation": compile("lib/onboarding-presentation.ts", {}),
      "../../lib/workspace-data": {
        loadWorkspaceData: async options => {
          calls.push(options);
          return { companies: [{ id: companyId, admittedAccountingYear: year }],
            primaryCompanyId: companyId, primaryIncomeYear: year,
            setups: [{ company_id: companyId, income_year: 2026 }], transactions: [] };
        },
      },
      "./BankImportForm": { BankImportForm() {} },
      "./CompanyYearAdmissionForm": { CompanyYearAdmissionForm() {} },
      "./OpeningBalanceForm": { OpeningBalanceForm },
    });
    const invocation = Page({ searchParams: Promise.resolve({ companyId, accountingYear: String(year) }) });
    if (year === 2026) await assert.rejects(invocation, /REDIRECT:\/dashboard/u);
    else {
      const page = await invocation;
      const balance = page.props.children.find(child => child?.type === OpeningBalanceForm);
      assert.ok(balance);
      assert.equal(balance.props.companyId, companyId);
      assert.equal(balance.props.incomeYear, 2025);
    }
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ companyId, accountingYear: year }]);
  }
});

test("successful company-year admission carries the admitted company and year through MFA", async () => {
  const companyId = "10000000-0000-4000-8000-000000000001";
  for (const year of [2025, 2026]) {
    const events = [];
    const continuationValue = continuation(year);
    const agreement = { version: "2026-08-30", contentSha256: "d".repeat(64) };
    const actions = compile("(owner)/onboarding/actions.ts", {
      "next/cache": { revalidatePath() {} },
      "next/navigation": { redirect(url) { throw new Error(`REDIRECT:${url}`); } },
      "../../../features/company-access": {
        admitCompanyYearThroughApi: async (_token, command) => {
          events.push(command.accountingYear);
          return { companyId, accountingYear: year };
        },
        eligibilityActionErrorMessage: () => "Unavailable",
        eligibilityAdmissionRestartRequired: () => false,
      },
      "../../lib/eligibility-continuation": {
        readEligibilityContinuation: async () => continuationValue,
        clearEligibilityContinuation: async () => events.push("cleared"),
      },
      "../../lib/customer-agreements": {
        currentCustomerAgreements: { businessTerms: agreement, dpa: agreement },
        currentPrivacyNotice: agreement,
      },
      "../../lib/supabase/auth-session": { getCurrentSessionAccessToken: async () => "session-token" },
    });
    const form = new FormData();
    form.set("companyYearPromiseAccepted", "accepted");
    for (const key of ["businessTerms", "dpa", "privacyNotice"]) {
      form.set(`${key}Version`, agreement.version); form.set(`${key}Sha256`, agreement.contentSha256);
    }
    form.set("capabilityManifestVersion", continuationValue.capabilityManifestVersion);
    form.set("capabilityManifestSha256", continuationValue.capabilityManifestSha256);
    await assert.rejects(actions.admitCompanyYear(form), error => {
      assert.ok(error.message.startsWith("REDIRECT:/mfa?"), error.message);
      const next = new URL(error.message.slice("REDIRECT:".length), "https://test.invalid").searchParams.get("next");
      const target = new URL(next, "https://test.invalid");
      assert.equal(target.pathname, "/onboarding");
      assert.equal(target.searchParams.get("companyId"), companyId);
      assert.equal(target.searchParams.get("accountingYear"), String(year));
      return true;
    });
    assert.deepEqual(events, [year, "cleared"]);
  }
});


test("real setup and bank actions retain company/year on success, preview and unknown-outcome recovery", async () => {
  const companyId = "10000000-0000-4000-8000-000000000001";
  const operationId = "40000000-0000-4000-8000-000000000004";
  for (const year of [2025, 2026]) for (const action of ["createOpeningBalanceSetup", "importBankCsv", "acceptBankCsvPreview"]) {
    for (const fail of [false, true]) {
      const calls = [];
      const effect = command => {
        calls.push(command);
        if (fail) throw new Error("Unknown synthetic operation outcome");
      };
      const audit = {
        select() { return this; }, eq() { return this; }, order() { return this; },
        async limit() { return { data: [] }; }, async insert() { return { error: null }; },
      };
      const dependencies = {
        hasSupabaseEnv: () => true,
        getCurrentSessionAccessToken: async () => "session-token",
        createSupabaseServerClient: async () => ({
          auth: { getUser: async () => ({ data: { user: { id: "synthetic-owner" } } }) },
          from: () => audit,
        }),
        revalidatePath() {}, redirect(url) { throw new Error(`REDIRECT:${url}`); },
        startNewYear: async (_token, command) => effect(command),
        previewBankSourceFile: async (_token, command) => {
          effect(command);
          return { sourceFileId: operationId, documentSha256: "a".repeat(64), transactionCount: 1 };
        },
        acceptBankSourceFile: async (_token, _source, command) => effect(command),
        ledgerOutcomeMayBeUnknown: () => true, bankingOutcomeMayBeUnknown: () => true,
        ledgerActionErrorMessage: () => "Retry same request", bankingActionErrorMessage: () => "Retry same request",
        createInvitationSideEffectStore: () => ({ findAudit() {} }), persistLedgerAudit: async () => {},
      };
      const actions = compile("actions.ts", {
        "./lib/action-return": compile("lib/action-return.ts", {}), "*": dependencies,
      });
      const form = new FormData();
      for (const [key, value] of Object.entries({
        returnTo: `/onboarding?step=bank&companyId=${companyId}&accountingYear=${year}`,
        companyId, incomeYear: String(year), operationId, accountId: operationId,
        sourceFileId: operationId, documentSha256: "a".repeat(64), transactionCount: "1",
        csvText: "date,text,amount\n2025-01-02,Synthetic,10",
      })) form.set(key, value);
      await assert.rejects(actions[action](form), error => {
        assert.ok(error.message.startsWith("REDIRECT:"), error.message);
        const target = new URL(error.message.slice("REDIRECT:".length), "https://test.invalid");
        assert.equal(target.pathname, "/onboarding");
        assert.equal(target.searchParams.get("step"), "bank");
        assert.equal(target.searchParams.get("companyId"), companyId);
        assert.equal(target.searchParams.get("accountingYear"), String(year));
        assert.equal(target.searchParams.has("error"), fail);
        if (action === "importBankCsv" && !fail) assert.equal(target.searchParams.get("bankPreviewSourceFileId"), operationId);
        return true;
      });
      assert.equal(calls.length, 1);
      assert.equal(calls[0].companyId, companyId);
      assert.equal(calls[0].incomeYear, year);
    }
  }
});
