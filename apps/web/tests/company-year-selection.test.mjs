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
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  }}).outputText, {exports, URLSearchParams, process:{env:{NODE_ENV:"production"}}, require(name) {
    if (name in dependencies) return dependencies[name];
    if (name === "node:crypto") return require(name);
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
