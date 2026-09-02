import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";

import * as customerAgreements from "../apps/web/app/lib/customer-agreements.ts";
import { ownerCopy } from "../apps/web/app/lib/copy.ts";

const {
  currentCustomerAgreements,
  customerAgreementAuthorityStatementVersion,
} = customerAgreements;

const legalPageSource = readFileSync(
  new URL("../apps/web/app/components/LegalPage.tsx", import.meta.url),
  "utf8",
);
const termsPageSource = readFileSync(new URL("../apps/web/app/vilkar/page.tsx", import.meta.url), "utf8");
const ownerOnboardingActionSource = readFileSync(
  new URL("../apps/web/app/(owner)/onboarding/actions.ts", import.meta.url),
  "utf8",
);

test("publishes separate current Business Terms and DPA records", () => {
  assert.deepEqual(Object.keys(currentCustomerAgreements), ["businessTerms", "dpa"]);
  assert.equal(currentCustomerAgreements.businessTerms.version, "2026-08-30");
  assert.equal(
    currentCustomerAgreements.businessTerms.contentSha256,
    "afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04",
  );
  assert.equal(currentCustomerAgreements.businessTerms.path, "/vilkar");
  assert.equal(currentCustomerAgreements.dpa.version, "2026-08-30");
  assert.equal(
    currentCustomerAgreements.dpa.contentSha256,
    "1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a",
  );
  assert.equal(currentCustomerAgreements.dpa.path, "/databehandleravtale");
  assert.match(currentCustomerAgreements.businessTerms.contentSha256, /^[a-f0-9]{64}$/u);
  assert.match(currentCustomerAgreements.dpa.contentSha256, /^[a-f0-9]{64}$/u);
  assert.equal(customerAgreementAuthorityStatementVersion, "authority-v1");
  assert.equal(
    currentCustomerAgreements.businessTerms.contentSha256,
    createHash("sha256").update(JSON.stringify(ownerCopy.legal.terms), "utf8").digest("hex"),
  );
  assert.equal(
    currentCustomerAgreements.dpa.contentSha256,
    createHash("sha256").update(JSON.stringify(ownerCopy.legal.dpa), "utf8").digest("hex"),
  );
});

test("rejects canonical content drift without a pinned digest update", () => {
  assert.throws(
    () => customerAgreements.assertCanonicalAgreementContent(
      "business_terms",
      { ...ownerCopy.legal.terms, intro: `${ownerCopy.legal.terms.intro} changed` },
      currentCustomerAgreements.businessTerms.contentSha256,
    ),
    /customer_agreement_content_digest_mismatch:business_terms/u,
  );
});

test("module initialization fails when public copy drifts from the pinned digest", () => {
  const directory = mkdtempSync(join(tmpdir(), "talli-agreement-drift-"));
  try {
    const moduleSource = readFileSync(
      new URL("../apps/web/app/lib/customer-agreements.ts", import.meta.url),
      "utf8",
    );
    const copySource = readFileSync(new URL("../apps/web/app/lib/copy.ts", import.meta.url), "utf8");
    const mutatedCopySource = copySource.replace(
      "Disse vilkårene er avtalen mellom selskapet",
      "ENDRET: Disse vilkårene er avtalen mellom selskapet",
    );
    assert.notEqual(mutatedCopySource, copySource);

    mkdirSync(join(directory, "app", "lib"), { recursive: true });
    writeFileSync(join(directory, "app", "lib", "customer-agreements.ts"), moduleSource);
    writeFileSync(join(directory, "app", "lib", "copy.ts"), mutatedCopySource);
    writeFileSync(
      join(directory, "app", "lib", "launch-copy.ts"),
      readFileSync(new URL("../apps/web/app/lib/launch-copy.ts", import.meta.url), "utf8"),
    );

    const importedModuleUrl = pathToFileURL(
      join(directory, "app", "lib", "customer-agreements.ts"),
    ).href;
    const result = spawnSync(
      process.execPath,
      ["--disable-warning=MODULE_TYPELESS_PACKAGE_JSON", "--experimental-strip-types", "--input-type=module", "--eval", `import(${JSON.stringify(importedModuleUrl)})`],
      { encoding: "utf8" },
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /customer_agreement_content_digest_mismatch:business_terms/u);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("uses one general supplier contract for beta and live plans", () => {
  const text = JSON.stringify([ownerCopy.legal.terms, ownerCopy.legal.dpa]);
  assert.match(text, /ELMER WELFIS/u);
  assert.match(text, /930 835 978/u);
  assert.match(text, /planen og funksjonene som vises i tjenesten/iu);
  assert.match(text, /databehandler/iu);
  assert.doesNotMatch(ownerCopy.legal.terms.intro, /ved å bruke/iu);
});

test("owner admission checks every current agreement version and digest", () => {
  for (const required of [
    /companyYearPromiseAccepted/u,
    /businessTermsVersion[^\n]*currentCustomerAgreements\.businessTerms\.version/u,
    /businessTermsSha256[^\n]*currentCustomerAgreements\.businessTerms\.contentSha256/u,
    /dpaVersion[^\n]*currentCustomerAgreements\.dpa\.version/u,
    /dpaSha256[^\n]*currentCustomerAgreements\.dpa\.contentSha256/u,
    /privacyNoticeVersion[^\n]*currentPrivacyNotice\.version/u,
    /privacyNoticeSha256[^\n]*currentPrivacyNotice\.contentSha256/u,
    /Vilkårene eller Talli-grensen er oppdatert/u,
  ]) {
    assert.match(ownerOnboardingActionSource, required);
  }
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
  assert.match(dpa, /etter kundens dokumenterte valg returnere eller slette/iu);
  assert.doesNotMatch(
    dpa,
    /etter kundens valg returnere eller slette[^.]*når tjenestens rutiner tillater det/iu,
  );
  assert.match(dpa, /med mindre en lov plikter Talli direkte til fortsatt lagring/iu);
});

test("requires explicit authorized reacceptance with immutable evidence for every material version", () => {
  const terms = JSON.stringify(ownerCopy.legal.terms);
  assert.match(terms, /enhver vesentlig ny avtaleversjon/iu);
  assert.match(terms, /uttrykkelig aksepteres på nytt av en representant med fullmakt/iu);
  assert.match(terms, /uforanderlig akseptbevis/iu);
  assert.doesNotMatch(terms, /fortsatt bruk[^.]*aksept/iu);
  assert.doesNotMatch(terms, /ny uttrykkelig aksept innhentes når det er nødvendig/iu);
});

test("publishes the annual company-year refund boundary while live billing remains gated", () => {
  const terms = JSON.stringify(ownerCopy.legal.terms);
  assert.match(terms, /NOK 1 490 per selskapsår/iu);
  assert.match(terms, /ingen månedspris, innsendingspakke/iu);
  assert.match(terms, /feil i Tallis egen logikk eller tilkobling/iu);
  assert.match(terms, /får kunden hele beløpet tilbake/iu);
  assert.match(terms, /avbrudd hos myndigheter utenfor Tallis kontroll gir ikke automatisk refusjon/iu);
  assert.doesNotMatch(terms, /30 dager|ubrukte hele måneder|fem virkedager/iu);
  assert.match(terms, /Betaling eller produksjonsinnsending aktiveres ikke/iu);
});

test("requires advance subprocessor notice without a practicality exception", () => {
  const dpa = JSON.stringify(ownerCopy.legal.dpa);
  assert.match(dpa, /forhåndsvarsel/iu);
  assert.match(dpa, /før endringen/iu);
  assert.doesNotMatch(dpa, /når det er praktisk mulig/iu);
});

test("public privacy and DPA copy do not assert unverified hosting or transfer controls", () => {
  const privacy = JSON.stringify(ownerCopy.legal.privacy);
  const dpa = JSON.stringify(ownerCopy.legal.dpa);
  assert.doesNotMatch(privacy, /EU-kommisjonens standard personvernbestemmelser|\bSCC\b|DPF|Data Privacy Framework/iu);
  assert.doesNotMatch(privacy, /EU-region|lagres i EØS|EEA region/iu);
  assert.match(privacy, /må verifiseres mot gjeldende produksjonsavtaler og konfigurasjon/iu);
  assert.match(dpa, /før tiltaket er verifisert i gjeldende produksjonsmiljø/iu);
  assert.doesNotMatch(dpa, /gjennomfører[^.]*logging[^.]*sikkerhetskopiering[^.]*gjenoppretting/iu);
  assert.match(dpa, /Når sikkerhetskopiering og rotasjon er verifisert i gjeldende produksjonsmiljø/iu);
});
