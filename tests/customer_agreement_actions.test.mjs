import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("company-year admission validates explicit authority and every immutable document before the generated command", async () => {
  const actions = await read("apps/web/app/(owner)/onboarding/actions.ts");

  assert.match(actions, /readEligibilityContinuation\(\)/u);
  assert.match(actions, /getCurrentSessionAccessToken\(\)/u);
  assert.match(actions, /companyYearPromiseAccepted/u);
  assert.match(actions, /businessTermsVersion/u);
  assert.match(actions, /businessTermsSha256/u);
  assert.match(actions, /dpaVersion/u);
  assert.match(actions, /dpaSha256/u);
  assert.match(actions, /privacyNoticeVersion/u);
  assert.match(actions, /privacyNoticeSha256/u);
  assert.match(actions, /capabilityManifestVersion/u);
  assert.match(actions, /capabilityManifestSha256/u);
  assert.match(actions, /authorityAccepted: true/u);
  assert.match(actions, /companyYearPromiseAccepted: true/u);
  assert.match(actions, /agreementAccepted: true/u);
  assert.match(actions, /admitCompanyYearThroughApi/u);
  assert.match(actions, /clearEligibilityContinuation\(\)/u);
  assert.doesNotMatch(actions, /createSupabaseServiceRoleClient|\.rpc\(|\.from\(/u);
});

test("the customer sees and explicitly accepts the complete pinned promise", async () => {
  const form = await read("apps/web/app/(owner)/onboarding/CompanyYearAdmissionForm.tsx");
  const manifest = JSON.parse(await read(
    "apps/backend/src/talli_backend/modules/company_access/capability_manifest.json",
  ));

  assert.match(form, /type="checkbox"/u);
  assert.match(form, /name="companyYearPromiseAccepted"/u);
  assert.match(form, /continuation\.customerClaims\.map/u);
  assert.match(form, /required/u);
  assert.doesNotMatch(form, /defaultChecked|checked=\{true\}/u);
  for (const path of ["/vilkar", "/databehandleravtale", "/personvern"]) {
    assert.match(form, new RegExp(`href="${path}"`, "u"));
  }
  for (const field of [
    "businessTermsVersion",
    "businessTermsSha256",
    "dpaVersion",
    "dpaSha256",
    "privacyNoticeVersion",
    "privacyNoticeSha256",
    "capabilityManifestVersion",
    "capabilityManifestSha256",
  ]) {
    assert.match(form, new RegExp(`name="${field}"`, "u"));
  }
  const claims = manifest.promise.customerClaims.join(" ");
  assert.match(claims, /aksjonærregisteroppgaven/u);
  assert.match(claims, /skattemeldingen/u);
  assert.match(claims, /årsregnskapet/u);
  assert.match(claims, /SAF-T/u);
  assert.match(form, /eneste regnskaps- og innsendingsproduktet/u);
  assert.match(form, /beholder leseadgangen/u);
  assert.match(form, /Ferdige arkiver kan fortsatt eksporteres/u);
});

test("legacy AS-only creation controls are absent", async () => {
  const globalActions = await read("apps/web/app/actions.ts");
  const workspace = await read("apps/web/app/(owner)/workspace/page.tsx");

  assert.doesNotMatch(globalActions, /createWorkspace|onboardCompanyThroughApi/u);
  assert.doesNotMatch(workspace, /action=\{createWorkspace\}|CustomerAgreementAcceptanceFields/u);
  assert.match(workspace, /href="\/sjekk-selskapet"/u);
  for (const legacyPath of [
    "../apps/web/app/(owner)/onboarding/CompanyLookupForm.tsx",
    "../apps/web/app/components/CustomerAgreementAcceptanceFields.tsx",
  ]) {
    await assert.rejects(access(new URL(legacyPath, import.meta.url)), { code: "ENOENT" });
  }
});
