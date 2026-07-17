import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  assertCurrentCustomerAgreementForm,
  currentCustomerAgreements,
  customerAgreementAuthorityStatementVersion,
} from "../app/lib/customer-agreements.ts";
import { ownerCopy } from "../app/lib/copy.ts";

const legalPageSource = readFileSync(
  new URL("../app/components/LegalPage.tsx", import.meta.url),
  "utf8",
);
const termsPageSource = readFileSync(new URL("../app/vilkar/page.tsx", import.meta.url), "utf8");

test("publishes separate current Business Terms and DPA records", () => {
  assert.deepEqual(Object.keys(currentCustomerAgreements), ["businessTerms", "dpa"]);
  assert.equal(currentCustomerAgreements.businessTerms.version, "2026-07-17");
  assert.equal(currentCustomerAgreements.businessTerms.path, "/vilkar");
  assert.equal(currentCustomerAgreements.dpa.version, "2026-07-17");
  assert.equal(currentCustomerAgreements.dpa.path, "/databehandleravtale");
  assert.match(currentCustomerAgreements.businessTerms.contentSha256, /^[a-f0-9]{64}$/u);
  assert.match(currentCustomerAgreements.dpa.contentSha256, /^[a-f0-9]{64}$/u);
  assert.equal(customerAgreementAuthorityStatementVersion, "authority-v1");
});

test("uses one general supplier contract for beta and live plans", () => {
  const text = JSON.stringify([ownerCopy.legal.terms, ownerCopy.legal.dpa]);
  assert.match(text, /ELMER WELFIS/u);
  assert.match(text, /930 835 978/u);
  assert.match(text, /planen og funksjonene som vises i tjenesten/iu);
  assert.match(text, /databehandler/iu);
  assert.doesNotMatch(ownerCopy.legal.terms.intro, /ved å bruke/iu);
});

test("rejects absent and stale company agreement assent", () => {
  const current = {
    agreementAccepted: "accepted",
    businessTermsVersion: "2026-07-17",
    dpaVersion: "2026-07-17",
  };
  assert.doesNotThrow(() => assertCurrentCustomerAgreementForm(current));
  assert.throws(
    () => assertCurrentCustomerAgreementForm({ ...current, agreementAccepted: "" }),
    /Du må bekrefte fullmakt og godta avtalevilkårene/u,
  );
  assert.throws(
    () => assertCurrentCustomerAgreementForm({ ...current, dpaVersion: "2026-07-16" }),
    /Avtalevilkårene er oppdatert/u,
  );
});

test("versioned contract pages replace the shared last-updated metadata", () => {
  assert.match(
    legalPageSource,
    /version && effectiveDate \? \([\s\S]*Versjon \{version\}[\s\S]*\) : \([\s\S]*c\.lastUpdatedLabel/u,
  );
});

test("publishes the canonical Business Terms name in browser metadata", () => {
  assert.match(termsPageSource, /title: "Brukervilkår for bedriftskunder – Talli"/u);
  assert.match(termsPageSource, /description: "Talli Business Terms for bedriftskunder\."/u);
});

test("makes return or deletion the customer's unconditional choice except for legal retention", () => {
  const dpa = JSON.stringify(ownerCopy.legal.dpa);
  assert.match(dpa, /etter kundens valg returnere eller slette/iu);
  assert.doesNotMatch(
    dpa,
    /etter kundens valg returnere eller slette[^.]*når tjenestens rutiner tillater det/iu,
  );
  assert.match(dpa, /med mindre lov krever fortsatt lagring/iu);
});
