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
  recurringConsent: true, renewalCanceledAt: null, capturedMinor: 125000, refundedMinor: 0, grossMinor: 125000,
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
  buttonClass: () => "btn btn--secondary",
  Banner: ({ children }) => React.createElement("div", { role: "status" }, children),
  Button: ({ children, variant: _variant, ...props }) => React.createElement("button", props, children),
  LinkButton: ({ children, ...props }) => React.createElement("a", props, children),
  EmptyState: ({ title, children }) => React.createElement("div", {}, title, children),
  StatusBadge: ({ label }) => React.createElement("span", {}, label),
};
ui.EmptyState = compile(readFileSync(new URL("../app/components/ui/EmptyState.tsx", import.meta.url), "utf8"), {
  "./cx": { cx: (...values) => values.filter(Boolean).join(" ") },
}).EmptyState;
const { AnnualAgreementCleanupControl } = compile(readFileSync(new URL("../app/components/billing/AnnualAgreementCleanupControl.tsx", import.meta.url), "utf8"), { "../ui": ui });
const { AnnualCheckoutObservationControl } = compile(readFileSync(new URL("../app/components/billing/AnnualCheckoutObservationControl.tsx", import.meta.url), "utf8"), { "../ui": ui });
const checkoutDraft = compile(readFileSync(new URL("../app/lib/annual-checkout-request.ts", import.meta.url), "utf8"), {});
const { AnnualCheckoutControl } = compile(readFileSync(new URL("../app/components/billing/AnnualCheckoutControl.tsx", import.meta.url), "utf8"), { "../ui": ui, "../../lib/annual-checkout-request": checkoutDraft });
const { AnnualRefundRecoveryControl } = compile(readFileSync(new URL("../app/components/billing/AnnualRefundRecoveryControl.tsx", import.meta.url), "utf8"), { "../ui": ui });
const { AnnualBillingView } = compile(readFileSync(new URL("../app/components/billing/AnnualBillingView.tsx", import.meta.url), "utf8"), { "../ui": ui, "./AnnualAgreementCleanupControl": { AnnualAgreementCleanupControl }, "./AnnualCheckoutObservationControl": { AnnualCheckoutObservationControl }, "./AnnualRefundRecoveryControl": { AnnualRefundRecoveryControl } });
function render(purchases = [purchase], extra = {}) {
  return renderToStaticMarkup(React.createElement(AnnualBillingView, { companyId, companyName: "Holding AS",
    snapshot: { offer, purchases, nextPurchaseId: null }, operationIds: { [purchaseId]: operationId },
    cancelAction: async () => {}, cleanupAction: async () => ({ kind: "idle" }), observeAction: async () => ({ kind: "idle" }), recoverRefundAction: async () => ({ kind: "idle" }), ...extra }));
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

test("purchase and offer archive downloads bypass Next navigation and its automatic prefetch", () => {
  const nextLinks = [];
  const buttons = compile(readFileSync(new URL("../app/components/ui/Button.tsx", import.meta.url), "utf8"), {
    "next/link": ({ href, children, ...props }) => {
      nextLinks.push(href);
      return React.createElement("a", { href, ...props }, children);
    },
    "./cx": { cx: (...values) => values.filter(Boolean).join(" ") },
  });
  const { AnnualBillingView: View } = compile(readFileSync(new URL("../app/components/billing/AnnualBillingView.tsx", import.meta.url), "utf8"), {
    "../ui": { ...ui, ...buttons },
    "./AnnualAgreementCleanupControl": { AnnualAgreementCleanupControl },
    "./AnnualCheckoutObservationControl": { AnnualCheckoutObservationControl },
    "./AnnualRefundRecoveryControl": { AnnualRefundRecoveryControl },
  });
  const html = renderToStaticMarkup(React.createElement(View, { companyId,
    companyName: "Holding AS", offer,
    snapshot: { companyId, purchases: [{ ...purchase, incomeYear: 2025 }], nextPurchaseId: null },
    operationIds: {}, cancelAction: async () => {}, cleanupAction: async () => ({ kind: "idle" }),
    observeAction: async () => ({ kind: "idle" }), recoverRefundAction: async () => ({ kind: "idle" }),
  }));
  for (const year of [2025, 2026]) {
    assert.match(html, new RegExp(`href="/archive/${companyId}/${year}/download"`));
    assert.match(html, new RegExp(`Last ned årsarkivet for ${year}`));
  }
  assert.deepEqual(nextLinks.filter(href => href.startsWith("/archive/")), []);
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
  assert.match(render([]), /Ingen årskjøp registrert/);
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
    if (recovery === "step-up") assert.equal(location.searchParams.get("fresh"), "1");
    if (recovery === "sign-in") assert.equal(location.searchParams.get("reauth"), "1");
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
function pageHarness({ companies = [company], token = "session", user = { id: operationId }, contextError, requiresAal2, requiresSignIn, failure, purchases = [purchase], historyMissing = false, nextPurchaseId = null, offerFailure = false, offerAccessRejected = false, refundPage = null, refundFailure, refundAccessRejected = false, preparation = null, preparationFailure, preparationAccessRejected = false } = {}) {
  const reads = [];
  const offerReads = [];
  const refundReads = [];
  const preparationReads = [];
  const { default: BillingPage } = compile(pageSource, {
    "../../../features/billing": { annualBillingRecovery: () => refundFailure ?? failure,
      annualBillingAccessRejected: () => offerAccessRejected || refundAccessRejected || preparationAccessRejected,
      prepareAnnualCheckout: async (...args) => { preparationReads.push(args); if (preparationFailure) throw new Error("private preparation detail"); return preparation; },
      loadAnnualRefundRecoveryTargets: async (...args) => { refundReads.push(args); if (refundFailure) throw new Error("private refund detail"); return refundPage; },
      loadAnnualPurchaseHistory: async (...args) => { reads.push(args); if (failure) throw new Error("internal detail");
        return historyMissing ? null : { companyId: args[1].companyId, purchases, nextPurchaseId }; },
      loadAnnualBillingSnapshot: async (...args) => { offerReads.push(args); if (offerFailure) throw new Error("offer unavailable");
        return { offer: { ...offer, companyId: args[1].companyId, incomeYear: args[1].incomeYear }, purchases, nextPurchaseId }; } },
    "next/navigation": { redirect: (path) => { throw new Error(`redirect:${path}`); } },
    "../../actions": { cancelAnnualRenewal: async () => {}, cleanupAnnualAgreement: async () => ({ kind: "idle" }), observeAnnualCheckout: async () => ({ kind: "idle" }), recoverAnnualRefund: async () => ({ kind: "idle" }), startAnnualCheckoutRequest: async () => ({ kind: "idle" }), withdrawAnnualCheckoutRequest: async () => ({ kind: "idle" }) },
    "../../components/billing/AnnualBillingView": { AnnualBillingView },
    "../../components/billing/AnnualCheckoutControl": { AnnualCheckoutControl },
    "../../components/ui": { ...ui, EmptyState: ({ title, children, action }) => React.createElement("section", {}, title, children, action) },
    "../../lib/copy": { ownerCopy: { billing: { hubTitle: "Abonnement" } } },
    "../../lib/company-access-context": { listCompanyAccessContexts: async () => ({ companies, error: contextError, requiresAal2, requiresSignIn }) },
    "../../lib/supabase/auth-session": { getCurrentSessionAccessToken: async () => token },
    "../../lib/supabase/server": { getCurrentUser: async () => user },
  });
  return { reads, offerReads, refundReads, preparationReads, render: async (params = {}) => renderToStaticMarkup(await BillingPage({ searchParams: Promise.resolve(params) })) };
}

test("billing page binds the selected company and admitted year without loading legacy workspace state", async () => {
  const another = { id: "60000000-0000-4000-8000-000000000001", name: "Second AS", admittedAccountingYear: 2027 };
  const harness = pageHarness({ companies: [company, another] });
  await harness.render({ companyId: another.id });
  assert.deepEqual(JSON.parse(JSON.stringify(harness.reads[0])), ["session", { companyId: another.id }]);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.offerReads[0])), ["session", { companyId: another.id, incomeYear: 2027 }]);
  assert.doesNotMatch(pageSource, /loadWorkspaceData|primaryBillingAccount|billingPricing/);
});

test("unknown company and malformed cursor never send an annual request", async () => {
  for (const [options, params] of [
    [{}, { companyId: "unknown" }],
    [{}, { beforePurchaseId: "broken" }],
  ]) {
    const harness = pageHarness(options);
    await harness.render(params);
    assert.equal(harness.reads.length, 0);
  }
});

test("owner history remains available without admission, with each stored year and original action scope", async () => {
  const previous = { ...purchase, incomeYear: 2025, termsText: "Historical 2025 purchase terms" };
  const harness = pageHarness({ companies: [{ ...company, admittedAccountingYear: null }], purchases: [previous] });
  const html = await harness.render({ beforePurchaseId: cursor });
  assert.equal(harness.reads.length, 1);
  assert.equal(harness.offerReads.length, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.reads[0])), ["session", { companyId, beforePurchaseId: cursor }]);
  assert.match(html, /Nytt selskapsår er ikke klart/);
  assert.doesNotMatch(html, /<p><p>/, "The real EmptyState must not receive a nested paragraph");
  assert.match(html, /selskapsåret 2025/);
  assert.match(html, /Historical 2025 purchase terms/);
  assert.match(html, /Stopp fornyelse/);
  assert.match(html, new RegExp(`/archive/${companyId}/2025/download`));
  assert.match(html, /Last ned årsarkivet for 2025/);
  assert.doesNotMatch(html, /Ett abonnement for hele selskapsåret/);
});

test("new current offer never replaces older purchase terms or archive year", async () => {
  const harness = pageHarness({ purchases: [{ ...purchase, incomeYear: 2025 }], nextPurchaseId: purchaseId });
  const html = await harness.render();
  assert.match(html, /Holding AS · selskapsåret 2026/);
  assert.match(html, /1.?250,00\s+kr inkl\. mva\. for selskapsåret 2025/);
  assert.match(html, new RegExp(`/archive/${companyId}/2025/download`));
  assert.match(html, new RegExp(`/archive/${companyId}/2026/download`));
  assert.match(html, /Eldre kjøp/);
});

test("partial capture stays visible independently of price, refunds and paid access", async () => {
  const purchases = [{ ...purchase, status: "pending", capturedMinor: 50000, refundedMinor: 10000,
    incomeYear: 2025 }];
  const harness = pageHarness({ purchases });
  const params = { companyId, beforePurchaseId: cursor, checkoutPurchaseId: purchaseId, checkoutStatus: "paid" };
  const initial = await harness.render(params);
  assert.match(initial, /Registrert belastet beløp: 500,00/);
  assert.match(initial, /1.?250,00\s+kr inkl\. mva\. for selskapsåret 2025/);
  assert.match(initial, /Registrert refundert beløp: 100,00/);
  assert.match(initial, /Betalingen er ikke bekreftet/);
  assert.match(initial, /Sjekk betalingsstatus/);
  assert.doesNotMatch(initial, /Betalt tilgang/);

  // Only a later canonical read changes the displayed amount; a URL status does not.
  purchases[0] = { ...purchases[0], capturedMinor: 80000 };
  const refreshed = await harness.render(params);
  assert.match(refreshed, /Registrert belastet beløp: 800,00/);
  assert.doesNotMatch(refreshed, /Registrert belastet beløp: 500,00|Betalt tilgang/);
  assert.match(refreshed, /Betalingen er ikke bekreftet/);
});

test("web-first fallback is explicitly limited and never passes a company history cursor to the old snapshot", async () => {
  const first = pageHarness({ historyMissing: true, nextPurchaseId: purchaseId });
  const html = await first.render();
  assert.match(html, /Bare de nyeste kjøpene for selskapsåret 2026/);
  assert.match(html, /Stopp fornyelse/);
  assert.doesNotMatch(html, /Eldre kjøp/);
  assert.equal(first.offerReads[0][1].beforePurchaseId, undefined);
  const older = pageHarness({ historyMissing: true });
  const unavailable = await older.render({ beforePurchaseId: cursor });
  assert.match(unavailable, /Abonnementet kan ikke vises nå/);
  assert.match(unavailable, /Vis nyeste kjøp/);
  assert.equal(older.offerReads.length, 0);
  const noAdmission = pageHarness({ historyMissing: true, companies: [{ ...company, admittedAccountingYear: null }] });
  assert.match(await noAdmission.render(), /Abonnementet kan ikke vises nå/);
  assert.equal(noAdmission.offerReads.length, 0);
});

test("unavailable offer preserves readable history but a later access rejection hides it", async () => {
  const available = await pageHarness({ offerFailure: true }).render();
  assert.match(available, /Årstilbudet kan ikke vises nå/);
  assert.match(available, /Stored purchase terms/);
  assert.match(available, /Stopp fornyelse/);
  const rejected = await pageHarness({ offerFailure: true, offerAccessRejected: true }).render();
  assert.match(rejected, /Abonnementet kan ikke vises nå/);
  assert.doesNotMatch(rejected, /Stored purchase terms|Stopp fornyelse|Last ned årsarkivet/);
});

test("an empty company-wide history without admission is an authorized empty result", async () => {
  const harness = pageHarness({ companies: [{ ...company, admittedAccountingYear: null }], purchases: [] });
  const html = await harness.render();
  assert.match(html, /Ingen årskjøp registrert/);
  assert.doesNotMatch(html, /Stopp fornyelse|Last ned årsarkivet|Betalt tilgang/);
  assert.equal(harness.reads.length, 1);
});

test("an empty continuation page never claims the company has no purchase history", async () => {
  const html = await pageHarness({ purchases: [] }).render({ beforePurchaseId: cursor });
  assert.match(html, /Ingen eldre kjøp/);
  assert.match(html, /Nyeste kjøp/);
  assert.doesNotMatch(html, /Ingen årskjøp registrert|ikke registrert årskjøp for selskapet/);
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
  await assert.rejects(unauthenticated.render(params), (error) => {
    assert.match(error.message, /^redirect:/);
    const login = new URL(error.message.slice("redirect:".length), "https://talli.example");
    assert.equal(login.pathname, "/login");
    assert.equal(login.searchParams.get("reauth"), "1");
    const target = new URL(login.searchParams.get("next"), login.origin);
    for (const [key, value] of Object.entries(params)) assert.equal(target.searchParams.get(key), value);
    return true;
  });
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

const refundRequestId = "50000000-0000-4000-8000-000000000001";
const refundPage = { companyId, purchaseId, incomeYear: 2026, targets: [
  { refundRequestId, requestedAt: "2026-09-06T12:00:00Z", status: "confirmed" },
], nextRefundRequestId: refundRequestId };

test("discovery loads only the selected canonical purchase and keeps money in history", async () => {
  const amounts = { ...purchase, recordedRefundMinor: 125000, refundedMinor: 50000, remainingRefundMinor: 75000,
    refundRequestCount: 4, refundOperations: { ...purchase.refundOperations, confirmed: 1 } };
  const harness = pageHarness({ purchases: [amounts], refundPage });
  const unselected = await harness.render();
  assert.equal(harness.refundReads.length, 0);
  assert.match(unselected, /Vis dine registrerte refusjonsforespørsler/);
  assert.doesNotMatch(unselected, /Sjekk refusjonsstatus/);
  const html = await harness.render({ refundPurchaseId: purchaseId, beforePurchaseId: cursor, beforeRefundRequestId: operationId });
  assert.deepEqual(JSON.parse(JSON.stringify(harness.refundReads)), [["session", { companyId, purchaseId, beforeRefundRequestId: operationId }]]);
  assert.match(html, /Gjenstående registrert beløp: 750,00/);
  assert.match(html, /Forsøket er bekreftet/);
  assert.match(html, /Sjekk refusjonsstatus/);
  assert.match(html, new RegExp(`name="refundRequestId" value="${refundRequestId}"`));
  assert.match(html, new RegExp(`beforePurchaseId=${cursor}&amp;beforeRefundRequestId=${refundRequestId}`));
});

test("absent or unavailable discovery retains authorized history without claiming no refund", async () => {
  for (const options of [{ refundPage: null }, { refundFailure: "unavailable" }]) {
    const html = await pageHarness(options).render({ refundPurchaseId: purchaseId });
    assert.match(html, /Forespørslene kan ikke vises nå/);
    assert.match(html, /Stored purchase terms|Stopp fornyelse/);
    assert.doesNotMatch(html, /Ingen registrerte forespørsler|Sjekk refusjonsstatus|private refund detail/);
  }
  const empty = await pageHarness({ refundPage: { ...refundPage, targets: [], nextRefundRequestId: null } }).render({ refundPurchaseId: purchaseId });
  assert.match(empty, /Ingen registrerte forespørsler kan kontrolleres av deg nå/);
  assert.match(empty, /eventuelt gjenstående refusjonsbeløp/);
});

test("discovery authentication rejection suppresses all earlier protected reads", async () => {
  for (const refundFailure of ["step-up", "sign-in", "unavailable"]) {
    const harness = pageHarness({ refundFailure, refundAccessRejected: true });
    const html = await harness.render({ companyId, refundPurchaseId: purchaseId, refundRequestId,
      beforePurchaseId: cursor, beforeRefundRequestId: operationId });
    assert.match(html, /Abonnementet kan ikke vises nå/);
    assert.doesNotMatch(html, /Stored purchase terms|Stopp fornyelse|Sjekk refusjonsstatus|Last ned årsarkivet/);
    assert.match(html, new RegExp(`refundRequestId(?:%3D|=)${refundRequestId}`));
    assert.match(html, new RegExp(`beforeRefundRequestId(?:%3D|=)${operationId}`));
  }
});

test("invalid or off-page selection sends no discovery request and never substitutes another purchase", async () => {
  for (const params of [{ refundPurchaseId: cursor }, { refundPurchaseId: "invalid" }, { refundRequestId },
    { refundPurchaseId: purchaseId, beforeRefundRequestId: "invalid" }]) {
    const harness = pageHarness({ refundPage });
    const html = await harness.render(params);
    assert.equal(harness.refundReads.length, 0);
    assert.match(html, /valgte refusjonsoversikten er ikke tilgjengelig/);
    assert.doesNotMatch(html, /Sjekk refusjonsstatus/);
  }
});

test("foreign discovery scope and replaced representative cannot silently select the earlier request", async () => {
  for (const changes of [{ companyId: cursor }, { purchaseId: cursor }, { incomeYear: 2025 }]) {
    const html = await pageHarness({ refundPage: { ...refundPage, ...changes } }).render({ refundPurchaseId: purchaseId });
    assert.match(html, /Forespørslene kan ikke vises nå/);
    assert.doesNotMatch(html, /Sjekk refusjonsstatus/);
  }
  const html = await pageHarness({ refundPage }).render({ refundPurchaseId: purchaseId, refundRequestId: operationId });
  assert.match(html, /Den valgte forespørselen vises ikke/);
  assert.doesNotMatch(html, new RegExp(`name="refundRequestId" value="${operationId}"`));
});

test("login preserves selected request and both cursors without performing any action", async () => {
  const harness = pageHarness({ token: null });
  await assert.rejects(harness.render({ companyId, refundPurchaseId: purchaseId, refundRequestId,
    beforePurchaseId: cursor, beforeRefundRequestId: operationId }), error => {
    const login = new URL(error.message.slice("redirect:".length), "https://talli.example");
    const next = new URL(login.searchParams.get("next"), login.origin);
    assert.equal(next.searchParams.get("refundRequestId"), refundRequestId);
    assert.equal(next.searchParams.get("refundPurchaseId"), purchaseId);
    assert.equal(next.searchParams.get("beforeRefundRequestId"), operationId);
    assert.equal(next.searchParams.get("beforePurchaseId"), cursor);
    return true;
  });
  assert.equal(harness.refundReads.length, 0);
});

test("unavailable discovery retries the same page and receipt while newest navigation explicitly resets them", async () => {
  const html = await pageHarness({ refundPage: null }).render({ refundPurchaseId: purchaseId, refundRequestId,
    beforePurchaseId: cursor, beforeRefundRequestId: operationId });
  const links = [...html.matchAll(/href="([^"]+)"[^>]*>([^<]+)</g)].map(match => ({ text: match[2],
    url: new URL(match[1].replaceAll('&amp;', '&'), 'https://talli.example') }));
  const retry = links.find(value => value.text === 'Last inn på nytt').url;
  assert.equal(retry.searchParams.get('refundRequestId'), refundRequestId);
  assert.equal(retry.searchParams.get('beforeRefundRequestId'), operationId);
  assert.equal(retry.searchParams.get('beforePurchaseId'), cursor);
  const newest = links.find(value => value.text === 'Nyeste forespørsler').url;
  assert.equal(newest.searchParams.get('refundRequestId'), null);
  assert.equal(newest.searchParams.get('beforeRefundRequestId'), null);
  assert.equal(newest.searchParams.get('beforePurchaseId'), cursor);
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
    if (recovery === "mfa") assert.equal(link.searchParams.get("fresh"), "1");
    if (recovery === "login") assert.equal(link.searchParams.get("reauth"), "1");
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

for (const status of ["pending", "paid", "refunded", "failed"]) {
  test(`only stored pending history exposes status recovery: ${status}`, async () => {
    const html = await pageHarness({ companies: [{ ...company, admittedAccountingYear: null }],
      purchases: [{ ...purchase, status, incomeYear: 2025, recurringConsent: false, renewalCanceledAt: "2026-09-05T12:00:00Z" }],
    }).render({ companyId, beforePurchaseId: cursor, checkoutPurchaseId: purchaseId, checkoutStatus: "paid" });
    assert.equal(html.includes("Sjekk betalingsstatus"), status === "pending");
    assert.match(html, /selskapsåret 2025/);
    assert.match(html, /Fullfør avslutning/);
    if (status === "pending") {
      assert.match(html, new RegExp(`name="beforePurchaseId" value="${cursor}"`));
      assert.doesNotMatch(html, /Betalt tilgang/);
    }
  });
}

test("checkout recovery marker survives login and page MFA without triggering observation", async () => {
  const params = { companyId, beforePurchaseId: cursor, checkoutPurchaseId: purchaseId };
  const html = await pageHarness({ failure: "step-up" }).render(params);
  assert.match(html, new RegExp(`checkoutPurchaseId%3D${purchaseId}`));
  assert.match(html, new RegExp(`beforePurchaseId%3D${cursor}`));
  const loggedOut = pageHarness({ token: null });
  await assert.rejects(loggedOut.render(params), (error) => error.message.includes(`checkoutPurchaseId%3D${purchaseId}`));
  assert.equal(loggedOut.reads.length, 0);
});

test('checkout preparation is read-only and follows the selected admitted company-year', async () => {
  const harness = pageHarness();
  await harness.render({ companyId, beforePurchaseId: cursor });
  assert.deepEqual(JSON.parse(JSON.stringify(harness.preparationReads)), [['session', companyId, 2026]]);
  const noAdmission = pageHarness({ companies: [{ ...company, admittedAccountingYear: null }] });
  const html = await noAdmission.render();
  assert.equal(noAdmission.preparationReads.length, 0);
  assert.match(html, /Henter eventuell tidligere kjøpsforespørsel/);
  assert.doesNotMatch(html, /name="purchaseAccepted"/);
});

test('unverified initiating user or later preparation access rejection hides protected history', async () => {
  const missing = pageHarness({ user: null });
  const noUser = await missing.render({ companyId, checkoutPurchaseId: purchaseId, checkoutBeforePurchaseId: cursor });
  assert.equal(missing.reads.length, 0);
  assert.match(noUser, /Logg inn igjen/);
  assert.doesNotMatch(noUser, /Stored purchase terms|annual-checkout-review/);
  const rejected = pageHarness({ preparationFailure: true, preparationAccessRejected: true, failure: undefined });
  const denied = await rejected.render();
  assert.equal(rejected.reads.length, 1);
  assert.equal(rejected.preparationReads.length, 1);
  assert.doesNotMatch(denied, /Stored purchase terms|annual-checkout-review/);
  const unavailable = await pageHarness({ preparationFailure: true }).render();
  assert.match(unavailable, /Stored purchase terms/);
  assert.match(unavailable, /annual-checkout-review/);
});

test('checkout selection starts on newest history and retains its earlier page as a separate backlink', async () => {
  const html = await pageHarness({ nextPurchaseId: purchaseId }).render({ companyId,
    checkoutPurchaseId: operationId, checkoutBeforePurchaseId: cursor });
  assert.match(html, /checkoutPurchaseId=30000000/);
  assert.match(html, /checkoutBeforePurchaseId=40000000/);
  assert.match(html, new RegExp(`href="/billing\\?companyId=${companyId}&amp;beforePurchaseId=${cursor}"`));
  const login = pageHarness({ token: null });
  await assert.rejects(login.render({ companyId, checkoutPurchaseId: purchaseId, checkoutBeforePurchaseId: cursor }), error => {
    const url = new URL(error.message.slice('redirect:'.length), 'https://talli.example');
    const next = new URL(url.searchParams.get('next'), url.origin);
    assert.equal(next.searchParams.get('checkoutPurchaseId'), purchaseId);
    assert.equal(next.searchParams.get('checkoutBeforePurchaseId'), cursor);
    assert.equal(next.searchParams.has('beforePurchaseId'), false);
    return true;
  });
});

test('pending checkout and canceled-agreement recovery coexist with distinct sibling identities', () => {
  const root = AnnualBillingView({ companyId, companyName: 'Holding AS',
    snapshot: { offer, purchases: [{ ...purchase, status: 'pending', renewalCanceledAt: '2026-09-05T11:01:00Z' }], nextPurchaseId: null },
    operationIds: {}, cancelAction: async () => {}, cleanupAction: async () => ({ kind: 'idle' }),
    observeAction: async () => ({ kind: 'idle' }), recoverRefundAction: async () => ({ kind: 'idle' }) });
  function find(value, predicate) {
    if (Array.isArray(value)) return value.flatMap(child => find(child, predicate));
    if (!React.isValidElement(value)) return [];
    return [...(predicate(value) ? [value] : []), ...find(value.props.children, predicate)];
  }
  const cards = find(root, value => typeof value.type === 'function' && value.props.purchase?.purchaseId === purchaseId);
  assert.equal(cards.length, 1);
  const article = cards[0].type(cards[0].props);
  const controls = find(article.props.children, value => [AnnualCheckoutObservationControl, AnnualAgreementCleanupControl].includes(value.type));
  assert.equal(controls.length, 2, 'The regression requires both live recovery controls on the same purchase');
  assert.equal(new Set(controls.map(value => value.key)).size, controls.length,
    'Sibling controls must retain distinct React identities across canonical history revalidation');
});
