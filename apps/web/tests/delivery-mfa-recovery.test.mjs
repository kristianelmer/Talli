import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { TalliApiError } from "@talli/talli-api-client";
import { taxDeliveryMfaRequired } from "../features/company-tax-filing/transport.ts";
import { accountsDeliveryMfaRequired } from "../features/annual-accounts-filing/transport.ts";
import { inspectOwnerMfa } from "../app/lib/owner-mfa.ts";

const require = createRequire(import.meta.url);
async function recoveryHref(family, error) {
  const exports = {};
  const source = readFileSync(new URL(`../app/(owner)/filing/_${family}-delivery.tsx`, import.meta.url), "utf8");
  const unavailable = async () => { throw error; };
  const transport = family === "tax" ? {
    loadTaxDeliveryWorkspace: unavailable, taxDeliveryMfaRequired, companyTaxActionErrorMessage: () => "MFA required",
  } : { loadAccountsDeliveryWorkspace: unavailable, accountsDeliveryMfaRequired, annualAccountsActionErrorMessage: () => "MFA required" };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require(name) {
    if (name === "react/jsx-runtime" || name === "node:crypto") return require(name);
    if (name === "../../components/ui") return {
      Banner: ({children}) => React.createElement("div", null, children),
      LinkButton: ({href,children}) => React.createElement("a", {href}, children),
    };
    if (name === "../../lib/supabase/auth-session") return { getCurrentSessionAccessToken: async () => "test-session" };
    if (name.startsWith("../../../features/")) return transport;
    if (name.startsWith("./")) return {};
    throw new Error(`Unexpected dependency: ${name}`);
  } });
  const Panel = family === "tax" ? exports.TaxDeliveryPanel : exports.AccountsDeliveryPanel;
  const html = renderToStaticMarkup(await Panel({companyId:"10000000-0000-4000-8000-000000000001",incomeYear:2025}));
  return new URL(html.match(/href="([^"]+)"/u)[1].replaceAll("&amp;", "&"), "https://talli.test");
}

test("delivery MFA recovery challenges an existing AAL2 session instead of returning it unchanged", async () => {
  for (const [family,code,next] of [["tax","COMPANY_TAX_MFA_REQUIRED","/filing/skattemelding"],
    ["accounts","ANNUAL_ACCOUNTS_MFA_REQUIRED","/filing/aarsregnskap"]]) {
    const href = await recoveryHref(family,new TalliApiError(403,{code}));
    assert.equal(href.pathname,"/mfa");
    assert.equal(href.searchParams.get("next"),next);
    let factorReads=0;
    const inspection=await inspectOwnerMfa({
      async getAuthenticatorAssuranceLevel(){return {data:{currentLevel:"aal2"},error:null};},
      async listFactors(){factorReads+=1;return {data:{totp:[{id:"existing-factor"}]},error:null};},
    },{requireFreshChallenge:href.searchParams.get("fresh")==="1",accessToken:"test-session"});
    assert.equal(inspection.kind,"challenge",`${family} must not loop through a stale AAL2 session`);
    assert.equal(factorReads,1);
    assert.equal(inspection.factorId,"existing-factor");
  }
});

test("unrelated delivery failures offer status refresh without forcing MFA", async () => {
  for (const [family,path] of [["tax","/filing/skattemelding"],["accounts","/filing/aarsregnskap"]]) {
    const href=await recoveryHref(family,new TalliApiError(503));
    assert.equal(href.pathname,path);
    assert.equal(href.search,"");
  }
});
