import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const companyId = "10000000-0000-4000-8000-000000000001";
const purchaseId = "20000000-0000-4000-8000-000000000001";
const operationId = "30000000-0000-4000-8000-000000000001";
const cursor = "40000000-0000-4000-8000-000000000001";
const offer = { companyId, incomeYear: 2026, currency: "NOK", grossMinor: 149000, netMinor: 119200,
  vatMinor: 29800, vatBasisPoints: 2500, termsText: "Current public terms" };
const purchase = { ...offer, purchaseId, acceptedAt: "2026-09-05T11:00:00Z", status: "paid",
  recurringConsent: true, renewalCanceledAt: null, refundedMinor: 0, grossMinor: 125000,
  netMinor: 100000, vatMinor: 25000, paidThrough: "2027-12-31", exportThrough: "2028-03-30",
  recordedRefundMinor: 0, remainingRefundMinor: 0, refundInitiateBy: null, refundRequestCount: 0,
  latestRefundRequestedAt: null, refundOperations: { created: 0, pending: 0, unknown: 0, confirmed: 0, failed: 0 },
  renewalDate: "2027-01-01", termsText: "Stored purchase terms <script>never execute</script>" };

function compile(source, dependencies) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: (id) => id in dependencies ? dependencies[id] : require(id),
    URLSearchParams, Intl, Date, Object, Error });
  return exports;
}
const ui = {
  Banner: ({ children }) => React.createElement("div", { role: "status" }, children),
  Button: ({ children, variant: _variant, ...props }) => React.createElement("button", props, children),
  LinkButton: ({ children, ...props }) => React.createElement("a", props, children),
  EmptyState: ({ title, children }) => React.createElement("div", {}, title, children),
  StatusBadge: ({ label }) => React.createElement("span", {}, label),
};
const { AnnualAgreementCleanupControl } = compile(readFileSync(new URL("../app/components/billing/AnnualAgreementCleanupControl.tsx", import.meta.url), "utf8"), { "../ui": ui });
const { AnnualBillingView } = compile(readFileSync(new URL("../app/components/billing/AnnualBillingView.tsx", import.meta.url), "utf8"), { "../ui": ui, "./AnnualAgreementCleanupControl": { AnnualAgreementCleanupControl } });
function render(purchases = [purchase], extra = {}) {
  return renderToStaticMarkup(React.createElement(AnnualBillingView, { companyName: "Holding AS",
    snapshot: { offer, purchases, nextPurchaseId: null }, operationIds: { [purchaseId]: operationId },
    cancelAction: async () => {}, cleanupAction: async () => ({ kind: "idle" }), ...extra }));
}

test("annual history keeps stored purchase prices and terms separate from today's offer", () => {
  const html = render();
  assert.match(html, /1.?490,00/);
  assert.match(html, /1.?250,00/);
  assert.match(html, /Stored purchase terms &lt;script&gt;/);
  assert.doesNotMatch(html, /<script>never execute/);
  assert.match(html, /Betalt tilgang til og med 31\. desember 2027/);
  assert.match(html, /value="30000000-0000-4000-8000-000000000001"/);
  assert.match(html, /Stopp fornyelse/);
  assert.match(html, /\/archive\/10000000-0000-4000-8000-000000000001\/2026\/download/);
});

test("only persisted cancellation confirms success even after an ambiguous response", () => {
  const uncertain = render([purchase], { unconfirmedPurchaseId: purchaseId });
  assert.match(uncertain, /Vi fikk ikke bekreftet oppsigelsen/);
  assert.doesNotMatch(uncertain, /Fornyelsen ble stoppet/);
  const confirmed = render([{ ...purchase, renewalCanceledAt: "2026-09-05T11:01:00Z" }], { unconfirmedPurchaseId: purchaseId });
  assert.match(confirmed, /Fornyelsen ble stoppet 5\. september 2026/);
  assert.match(confirmed, /Betalt tilgang/);
  assert.doesNotMatch(confirmed, /Stopp fornyelse|Vi fikk ikke bekreftet/);
});

for (const status of ["pending", "failed", "refunded"]) {
  test(`${status} history never claims paid access and still permits renewal cancellation`, () => {
    const html = render([{ ...purchase, status, refundedMinor: status === "refunded" ? 125000 : 0 }]);
    assert.doesNotMatch(html, /Betalt tilgang/);
    assert.match(html, /Stopp fornyelse/);
    if (status === "refunded") assert.match(html, /Registrert refundert beløp/);
  });
}

test("nonrecurring purchase does not suggest renewal; history retains company and cursor", () => {
  const html = render([{ ...purchase, recurringConsent: false }], { beforePurchaseId: cursor,
    snapshot: { offer, purchases: [{ ...purchase, recurringConsent: false }], nextPurchaseId: purchaseId } });
  assert.match(html, /Automatisk fornyelse er ikke valgt/);
  assert.doesNotMatch(html, /Stopp fornyelse/);
  assert.match(html, /Nyeste kjøp/);
  assert.match(html, /companyId=10000000-0000-4000-8000-000000000001&amp;beforePurchaseId=20000000/);
  assert.match(render([]), /Ingen kjøp for dette selskapsåret/);
});

test("owner refund evidence shows cumulative liability and settled money independently", () => {
  const html = render([{ ...purchase, recordedRefundMinor: 125000, refundedMinor: 50000, remainingRefundMinor: 75000,
    refundRequestCount: 2, latestRefundRequestedAt: "2026-09-05T12:00:00Z",
    refundOperations: { ...purchase.refundOperations, confirmed: 1, unknown: 1 } }]);
  assert.match(html, /Registrert refusjonsbeløp: 1.?250,00/);
  assert.match(html, /Gjenstående registrert beløp: 750,00/);
  assert.match(html, /Registrert refundert beløp: 500,00/);
  assert.match(html, /Utfallet av et refusjonsforsøk er ikke kjent/);
  assert.match(html, /En registrert forespørsel er ikke en bekreftelse på utbetaling/);
  assert.match(html, /Betalt tilgang/);
  assert.doesNotMatch(html, /fullt refundert|refusjonen er fullført|<form[^>]*refund/i);
});

test("a pending refund past its initiation target never implies late initiation or bank receipt", () => {
  const html = render([{ ...purchase, recordedRefundMinor: 125000, remainingRefundMinor: 125000,
    refundInitiateBy: "2020-01-02", refundOperations: { ...purchase.refundOperations, pending: 1 } }]);
  assert.match(html, /Registrert frist for å starte refusjonen: 2\. januar 2020/);
  assert.match(html, /venter på bekreftelse fra betalingsleverandøren/);
  assert.match(html, /Tiden til pengene er på konto avhenger av betalingsleverandøren og banken/);
  assert.doesNotMatch(html, /forsinket|overskredet|på konto innen|fullført/);
});

for (const status of ["created", "failed"]) {
  test(`a ${status} attempt does not erase outstanding owner refund liability`, () => {
    const html = render([{ ...purchase, recordedRefundMinor: 125000, remainingRefundMinor: 125000,
      refundOperations: { ...purchase.refundOperations, [status]: 1 } }]);
    assert.match(html, /Gjenstående registrert beløp: 1.?250,00/);
    assert.match(html, status === "created" ? /klargjort, men ikke bekreftet/ : /Et refusjonsforsøk ble ikke fullført/);
    assert.match(html, /Registrert refundert beløp: 0,00/);
  });
}

test("a request without recorded liability is visible without inventing refund rights or settlement", () => {
  const html = render([{ ...purchase, refundRequestCount: 1, latestRefundRequestedAt: "2026-09-05T12:00:00Z" }]);
  assert.match(html, /Refusjonsforespørsel registrert 5\. september 2026/);
  assert.match(html, /Ingen refusjonsforsøk er registrert/);
  assert.doesNotMatch(html, /Registrert refusjonsbeløp:|Gjenstående registrert beløp:|ikke rett til|fullført/);
  assert.doesNotMatch(render(), /aria-label="Registrert refusjon"/);
});

test("web-first deployment keeps predecessor history and cancellation while refund details are unavailable", () => {
  const { recordedRefundMinor, remainingRefundMinor, refundInitiateBy, refundRequestCount,
    latestRefundRequestedAt, refundOperations, ...previous } = purchase;
  const html = render([{ ...previous, refundedMinor: 50000 }]);
  assert.match(html, /Refusjonsdetaljer er ikke tilgjengelige nå/);
  assert.match(html, /Registrert refundert beløp: 500,00/);
  assert.match(html, /Stopp fornyelse/);
  assert.doesNotMatch(html, /Gjenstående registrert beløp|Ingen refusjonsforsøk|ikke rett til/);
});

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const source = actions.slice(actions.indexOf("export async function cancelAnnualRenewal("), actions.indexOf("export async function cancelBillingSubscription("));
function actionHarness(recovery, authenticated = true) {
  const calls = [];
  const redirects = [];
  const dependencies = {
    requiredFormUuid: (form, key) => form.get(key), formString: (form, key) => form.get(key) ?? "",
    ownerPathWithQuery: (path, values) => `${path}?${new URLSearchParams(Object.entries(values).filter(([, value]) => value !== undefined))}`,
    getCurrentSessionAccessToken: async () => authenticated ? "test-session" : null,
    cancelAnnualRenewalThroughApi: async (...args) => { calls.push(args); if (recovery) throw new Error("private provider data"); },
    annualBillingRecovery: () => recovery, revalidatePath: (path) => calls.push(path),
    redirect: (path) => { redirects.push(path); throw new Error("redirect"); },
  };
  const boundSource = `const { ${Object.keys(dependencies).join(",")} } = require("dependencies");\n${source}`;
  return { action: compile(boundSource, { dependencies }).cancelAnnualRenewal, calls, redirects };
}
function form() {
  const result = new FormData();
  for (const [key, value] of Object.entries({ companyId, purchaseId, operationId, beforePurchaseId: cursor })) result.set(key, value);
  return result;
}
for (const recovery of ["unavailable", "step-up", "sign-in"]) {
  test(`cancellation ${recovery} recovery preserves the exact company/purchase/key/history`, async () => {
    const harness = actionHarness(recovery);
    await assert.rejects(harness.action(form()), /redirect/);
    assert.equal(harness.calls.length, 1);
    assert.deepEqual(JSON.parse(JSON.stringify(harness.calls[0])), ["test-session", { companyId, purchaseId }, operationId]);
    const location = new URL(harness.redirects[0], "https://talli.example");
    const target = new URL(location.searchParams.get("next") ?? location.href, location.origin);
    assert.equal(target.pathname, "/billing");
    assert.equal(target.searchParams.get("companyId"), companyId);
    assert.equal(target.searchParams.get("beforePurchaseId"), cursor);
    assert.equal(target.searchParams.get("cancellationOperationId"), operationId);
    assert.equal(target.searchParams.get("cancellationPurchaseId"), purchaseId);
    assert.doesNotMatch(harness.redirects[0], /private|provider/);
    assert.equal(location.pathname, recovery === "step-up" ? "/mfa" : recovery === "sign-in" ? "/login" : "/billing");
  });
}

test("successful cancellation refreshes history without fabricating a success flag", async () => {
  const harness = actionHarness();
  await assert.rejects(harness.action(form()), /redirect/);
  assert.equal(harness.calls.length, 2);
  assert.equal(harness.calls[1], "/billing");
  assert.equal(harness.redirects[0], `/billing?companyId=${companyId}&beforePurchaseId=${cursor}`);
});

test("missing session reaches sign-in with replay context before any mutation", async () => {
  const harness = actionHarness(undefined, false);
  await assert.rejects(harness.action(form()), /redirect/);
  assert.equal(harness.calls.length, 0);
  const target = new URL(harness.redirects[0], "https://talli.example");
  assert.equal(target.pathname, "/login");
  assert.match(target.searchParams.get("next"), new RegExp(operationId));
});

const pageSource = readFileSync(new URL("../app/(account)/billing/page.tsx", import.meta.url), "utf8");
const company = { id: companyId, name: "Holding AS", admittedAccountingYear: 2026 };
function pageHarness({ companies = [company], token = "session", contextError, requiresAal2, requiresSignIn, failure, purchases = [purchase] } = {}) {
  const reads = [];
  const { default: BillingPage } = compile(pageSource, {
    "../../../features/billing": { annualBillingRecovery: () => failure,
      loadAnnualBillingSnapshot: async (...args) => { reads.push(args); if (failure) throw new Error("internal detail");
        return { offer, purchases, nextPurchaseId: null }; } },
    "next/navigation": { redirect: (path) => { throw new Error(`redirect:${path}`); } },
    "../../actions": { cancelAnnualRenewal: async () => {}, cleanupAnnualAgreement: async () => ({ kind: "idle" }) },
    "../../components/billing/AnnualBillingView": { AnnualBillingView },
    "../../components/ui": { ...ui, EmptyState: ({ title, children, action }) => React.createElement("section", {}, title, children, action) },
    "../../lib/copy": { ownerCopy: { billing: { hubTitle: "Abonnement" } } },
    "../../lib/company-access-context": { listCompanyAccessContexts: async () => ({ companies, error: contextError, requiresAal2, requiresSignIn }) },
    "../../lib/supabase/auth-session": { getCurrentSessionAccessToken: async () => token },
  });
  return { reads, render: async (params = {}) => renderToStaticMarkup(await BillingPage({ searchParams: Promise.resolve(params) })) };
}

test("billing page binds the selected company and admitted year without loading legacy workspace state", async () => {
  const another = { id: "60000000-0000-4000-8000-000000000001", name: "Second AS", admittedAccountingYear: 2027 };
  const harness = pageHarness({ companies: [company, another] });
  await harness.render({ companyId: another.id });
  assert.deepEqual(JSON.parse(JSON.stringify(harness.reads[0])), ["session", { companyId: another.id, incomeYear: 2027 }]);
  assert.doesNotMatch(pageSource, /loadWorkspaceData|primaryBillingAccount|billingPricing/);
});

test("unknown company, missing admission and malformed cursor never send an annual request", async () => {
  for (const [options, params] of [
    [{}, { companyId: "unknown" }], [{ companies: [{ ...company, admittedAccountingYear: null }] }, {}],
    [{}, { beforePurchaseId: "broken" }],
  ]) {
    const harness = pageHarness(options);
    await harness.render(params);
    assert.equal(harness.reads.length, 0);
  }
});

test("read failure offers fresh history and MFA recovery retains cancellation context", async () => {
  const params = { companyId, beforePurchaseId: cursor, cancellationPurchaseId: purchaseId, cancellationOperationId: operationId };
  const harness = pageHarness({ failure: "step-up" });
  const html = await harness.render(params);
  assert.match(html, /Bekreft identiteten din/);
  assert.match(html, /Vis nyeste kjøp/);
  assert.match(html, new RegExp(`cancellationOperationId%3D${operationId}`));
  assert.doesNotMatch(html, /internal detail|Fornyelsen ble stoppet/);
  const unauthenticated = pageHarness({ token: null });
  await assert.rejects(unauthenticated.render(params), (error) => error.message.includes("/login?next=") && error.message.includes(operationId));
  assert.equal(unauthenticated.reads.length, 0);
});

test("read after uncertain cancellation reuses the key only on the same purchase", async () => {
  const harness = pageHarness();
  const html = await harness.render({ cancellationPurchaseId: purchaseId, cancellationOperationId: operationId, cancellationError: "unconfirmed" });
  assert.match(html, new RegExp(`value="${operationId}"`));
  assert.match(html, /Vi fikk ikke bekreftet oppsigelsen/);
  const another = await pageHarness().render({ cancellationPurchaseId: cursor, cancellationOperationId: operationId });
  assert.doesNotMatch(another, new RegExp(`value="${operationId}"`));
});

for (const recovery of ["mfa", "login", "retry"]) {
  test(`Company Access ${recovery} failure retains the selected second company before authorization succeeds`, async () => {
    const selectedCompanyId = "60000000-0000-4000-8000-000000000001";
    const params = { companyId: selectedCompanyId, beforePurchaseId: cursor,
      cancellationPurchaseId: purchaseId, cancellationOperationId: operationId };
    const harness = pageHarness({ companies: [], contextError: "Unavailable",
      requiresAal2: recovery === "mfa", requiresSignIn: recovery === "login" });
    const html = await harness.render(params);
    const href = html.match(/href="([^"]+)"/)?.[1].replaceAll("&amp;", "&");
    const link = new URL(href, "https://talli.example");
    assert.equal(link.pathname, recovery === "retry" ? "/billing" : `/${recovery}`);
    const target = new URL(link.searchParams.get("next") ?? link.href, link.origin);
    for (const [key, value] of Object.entries(params)) assert.equal(target.searchParams.get(key), value);
    assert.equal(harness.reads.length, 0);
    assert.doesNotMatch(html, /Fornyelsen ble stoppet|Stopp fornyelse/);
  });
}

const accountLayoutSource = readFileSync(new URL("../app/(account)/layout.tsx", import.meta.url), "utf8");
test("billing account layout leaves legal and company recovery to its authorized page", async () => {
  const child = React.createElement("p", {}, "Scoped billing recovery");
  for (const user of [null, { email: "owner@example.test", email_confirmed_at: "2026-09-05" }]) {
    const { default: AccountLayout } = compile(accountLayoutSource, {
      "next/navigation": { redirect: () => { throw new Error("unexpected redirect"); } },
      "../(owner)/AppNav": { AppNav: ({ children }) => children },
      "../actions": { signOut: async () => {} },
      "../lib/copy": { ownerCopy: { brand: "Talli", nav: { signOut: "Logg ut" } } },
      "../lib/supabase/server": { getOperatorContext: async () => ({ user, isOperator: false }), needsEmailVerification: () => false },
    });
    const html = renderToStaticMarkup(await AccountLayout({ children: child }));
    assert.match(html, /Scoped billing recovery/);
  }
  assert.doesNotMatch(accountLayoutSource, /listCompanyAccessContexts|currentAgreementAccepted|reacceptCompanyAgreement/);
});


for (const status of ["pending", "paid", "failed", "refunded"]) {
  test(`persisted cancellation exposes explicit agreement recovery for ${status} purchase without recurring consent`, () => {
    const html = render([{ ...purchase, status, recurringConsent: false, renewalCanceledAt: "2026-09-05T11:01:00Z" }]);
    assert.match(html, /Fullfør avslutning av betalingsavtalen/);
    assert.doesNotMatch(html, /har bekreftet at betalingsavtalen er avsluttet/);
  });
}

test("owner recovery selection survives login without trusting a forged cleanup confirmation", async () => {
  const params = { companyId, beforePurchaseId: cursor, cleanupPurchaseId: purchaseId, cleanupStatus: "confirmed" };
  const unauthenticated = pageHarness({ token: null });
  await assert.rejects(unauthenticated.render(params), (error) => error.message.includes("cleanupPurchaseId%3D" + purchaseId));
  const html = await pageHarness().render(params);
  assert.doesNotMatch(html, /har bekreftet at betalingsavtalen er afsluttet|har bekreftet at betalingsavtalen er avsluttet/);
});
