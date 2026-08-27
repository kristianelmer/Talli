import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { publicRecruitmentOffer } from "../features/public-acquisition/index.ts";

const homepageSource = readFileSync(
  new URL("../app/page.tsx", import.meta.url),
  "utf8",
);
const capabilityManifest = JSON.parse(readFileSync(
  new URL(
    "../../backend/src/talli_backend/modules/company_access/capability_manifest.json",
    import.meta.url,
  ),
  "utf8",
));

test("the public offer stays in free recruitment mode with one eligibility action", () => {
  assert.equal(publicRecruitmentOffer.mode, "recruitment");
  assert.equal(publicRecruitmentOffer.checkoutEnabled, false);
  assert.deepEqual(publicRecruitmentOffer.primaryAction, {
    label: "Sjekk selskapet gratis",
    href: "/sjekk-selskapet",
  });
  assert.equal(
    publicRecruitmentOffer.recruitmentNotice,
    "Gratis rekrutterings- og valideringsmodus. Betaling, banktilkobling og produksjonsinnsending er ikke åpnet.",
  );

  assert.match(homepageSource, /\.\.\/features\/public-acquisition/u);
  assert.equal(
    (homepageSource.match(/href=\{c\.primaryAction\.href\}/gu) ?? []).length,
    2,
  );
  assert.equal((homepageSource.match(/variant="primary"/gu) ?? []).length, 1);
  assert.equal((homepageSource.match(/variant="secondary"/gu) ?? []).length, 1);
  assert.doesNotMatch(homepageSource, /mailto:|checkout|bestill|betal nå/iu);
});

test("the three-step eligibility explanation keeps its visual order for assistive technology", () => {
  assert.match(homepageSource, /<ol className=\{styles\.steps\}>/u);
  assert.match(homepageSource, /<li className=\{styles\.step\}/u);
  assert.doesNotMatch(homepageSource, /<div className=\{styles\.steps\}>/u);
});

test("the static homepage renders every required offer field in the approved order", () => {
  for (const binding of [
    "c.includedTitle",
    "c.filings",
    "c.includedCapabilityClaims",
    "c.reconstruction",
    "c.scope.supported",
    "c.scope.blocked",
    "c.scope.nextStep",
    "c.priceLine",
    "c.priceRestriction",
    "c.refundPromise",
    "c.operator",
    "c.nonAffiliation",
    "c.proofTitle",
    "c.proofBody",
    "c.proofLinks",
    "c.faqTitle",
    "c.faq",
    "c.finalTitle",
    "c.finalBody",
  ]) {
    assert.equal(homepageSource.includes(binding), true, binding);
  }

  let previousSection = -1;
  for (const sectionId of [
    "home-title",
    "included-title",
    "scope-title",
    "steps-title",
    "price-title",
    "proof-title",
    "faq-title",
    "final-action-title",
  ]) {
    const position = homepageSource.indexOf(`id="${sectionId}"`);
    assert.ok(position > previousSection, sectionId);
    previousSection = position;
  }

  assert.doesNotMatch(homepageSource, /godkjente tilbudet/iu);
});

test("the recruitment homepage presents the approved annual offer exactly", () => {
  assert.equal(
    publicRecruitmentOffer.priceLine,
    "NOK 1,490 inkl. mva. per selskapsår. Banktilkobling og alle tre innsendingene er inkludert.",
  );
  assert.deepEqual(publicRecruitmentOffer.filings, [
    "Aksjonærregisteroppgaven (RF-1086)",
    "Skattemeldingen for selskapet",
    "Årsregnskapet",
  ]);
  assert.equal(
    publicRecruitmentOffer.refundPromise,
    "Full refusjon innen 30 dager etter første kjøp når ingen produksjonsinnsending er sendt. Hvis Talli godtar en sak som skulle vært stoppet, eller Talli eller en leverandør ikke kan fullføre det lovede selskapsåret, refunderes hele beløpet automatisk.",
  );
  assert.equal(
    publicRecruitmentOffer.operator,
    "Talli drives av ELMER WELFIS, org.nr. 930 835 978. Kontakt: post@talli.no.",
  );
  assert.equal(
    publicRecruitmentOffer.nonAffiliation,
    "Talli er ikke tilknyttet, godkjent av eller drevet av Fiken, Altinn, Skatteetaten eller Brønnøysundregistrene.",
  );
});

test("the public offer carries the approved proof links, minimum FAQ, and final eligibility invitation", () => {
  assert.deepEqual(publicRecruitmentOffer.proofLinks, [
    { label: "Se selskapsgrensen", href: "/selskapsgrense" },
    { label: "Les personvern", href: "/personvern" },
    { label: "Les vilkår og refusjon", href: "/vilkar" },
  ]);
  assert.deepEqual(
    publicRecruitmentOffer.faq.map(({ question }) => question),
    [
      "Hvilke selskaper passer?",
      "Hva er inkludert?",
      "Trenger jeg et annet regnskapsprogram?",
      "Kan jeg starte etter 1. januar?",
      "Hva skjer hvis banken eller importen har hull?",
      "Hvem kontrollerer og sender inn?",
      "Hva skjer når noe er uklart eller ikke støttes?",
      "Hva koster det, og hvordan fungerer fornyelse og oppsigelse?",
      "Hvordan fungerer refusjon?",
      "Hvordan håndterer Talli sikkerhet, personvern og hjelp?",
    ],
  );
  assert.equal(publicRecruitmentOffer.finalTitle, "Start med gratissjekken");
  assert.match(publicRecruitmentOffer.finalBody, /ingen konto eller betaling/u);
});

test("the complete public company-year promise is pinned to the canonical manifest", () => {
  assert.deepEqual(
    publicRecruitmentOffer.companyYearPromise,
    capabilityManifest.promise,
  );
  assert.equal(publicRecruitmentOffer.capabilityManifestVersion, "2026.1");
  assert.equal(
    publicRecruitmentOffer.capabilityManifestVersion,
    capabilityManifest.boundaryVersion,
  );
  assert.deepEqual(
    publicRecruitmentOffer.includedCapabilityKeys,
    capabilityManifest.promise.capabilities,
  );
  assert.deepEqual(
    publicRecruitmentOffer.includedCapabilityClaims,
    capabilityManifest.promise.customerClaims,
  );
});
