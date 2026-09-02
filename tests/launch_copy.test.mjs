import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  preProductionDirectFilingCopy,
  requiredNonAffiliationCopy,
  validateLaunchCopy,
} from "../apps/web/app/lib/launch-copy.ts";
import { publicRecruitmentOffer } from "../apps/web/features/public-acquisition/index.ts";

const ownerCopySource = readFileSync(new URL("../apps/web/app/lib/copy.ts", import.meta.url), "utf8");

test("requires non-affiliation and pre-production gate language in public app copy", () => {
  // The canonical launch strings are wired into the central owner copy module
  // (see app/lib/copy.ts -> ownerCopy.filing) since the UX rebuild (#89/#93).
  const copy = readFileSync(new URL("../apps/web/app/lib/copy.ts", import.meta.url), "utf8");

  assert.match(copy, /requiredNonAffiliationCopy/);
  assert.match(copy, /preProductionDirectFilingCopy/);

  // ...and that copy is surfaced where the owner reviews submission readiness.
  const submissionReview = readFileSync(
    new URL("../apps/web/app/components/annual-workspace/SubmissionReview.tsx", import.meta.url),
    "utf8",
  );

  assert.match(submissionReview, /requiredNonAffiliationCopy/);
  assert.match(submissionReview, /preProductionDirectFilingCopy/);

  const result = validateLaunchCopy(`${requiredNonAffiliationCopy}\n${preProductionDirectFilingCopy}`);

  assert.equal(result.hasRequiredNonAffiliation, true);
  assert.equal(result.hasPreProductionGate, true);
  assert.deepEqual(result.violations, []);
  assert.equal(result.approved, true);
});

test("rejects launch claims that outrun authority evidence", () => {
  const result = validateLaunchCopy(
    `${requiredNonAffiliationCopy}\n${preProductionDirectFilingCopy}\nGodkjent av Skatteetaten og ferdig innsendt.`,
  );

  assert.equal(result.approved, false);
  assert.ok(result.violations.length >= 2);
});

test("public homepage is a truthful free recruitment entry", () => {
  const publicPage = readFileSync(new URL("../apps/web/app/page.tsx", import.meta.url), "utf8");
  const capabilityManifest = JSON.parse(readFileSync(
    new URL(
      "../apps/backend/src/talli_backend/modules/company_access/capability_manifest.json",
      import.meta.url,
    ),
    "utf8",
  ));

  assert.equal(publicRecruitmentOffer.mode, "recruitment");
  assert.equal(publicRecruitmentOffer.checkoutEnabled, false);
  assert.deepEqual(publicRecruitmentOffer.primaryAction, {
    label: "Sjekk selskapet gratis",
    href: "/sjekk-selskapet",
  });
  assert.equal(publicRecruitmentOffer.nonAffiliation, requiredNonAffiliationCopy);
  assert.deepEqual(publicRecruitmentOffer.companyYearPromise, capabilityManifest.promise);
  assert.match(publicPage, /\.\.\/features\/public-acquisition/u);
  assert.equal(
    (publicPage.match(/href=\{c\.primaryAction\.href\}/gu) ?? []).length,
    2,
  );
  assert.equal((publicPage.match(/variant="primary"/gu) ?? []).length, 1);
  assert.equal((publicPage.match(/variant="secondary"/gu) ?? []).length, 1);
  assert.doesNotMatch(publicPage, /mailto:|checkout|bestill|betal nå/iu);

  for (const requiredBinding of [
    "c.includedCapabilityClaims",
    "c.priceLine",
    "c.refundPromise",
    "c.operator",
    "c.nonAffiliation",
    "c.proofLinks",
    "c.faq",
    "c.finalBody",
  ]) {
    assert.equal(publicPage.includes(requiredBinding), true, requiredBinding);
  }

  const renderedCopy = JSON.stringify(publicRecruitmentOffer);
  assert.doesNotMatch(renderedCopy, /uten regnskapsfører/i);
  assert.doesNotMatch(renderedCopy, /menneskelig kontroll/i);
  assert.doesNotMatch(renderedCopy, /betaler først ved innsending/i);
  assert.doesNotMatch(renderedCopy, /leveres til riktig myndighet/i);
  assert.doesNotMatch(renderedCopy, /trygg innsending/i);
});

test("public company check is free, provisional, and distinguishes provider failure", () => {
  const eligibilityPage = readFileSync(
    new URL("../apps/web/app/sjekk-selskapet/page.tsx", import.meta.url),
    "utf8",
  );
  const checker = readFileSync(
    new URL("../apps/web/app/sjekk-selskapet/EligibilityChecker.tsx", import.meta.url),
    "utf8",
  );
  const presentation = readFileSync(
    new URL("../apps/web/features/company-access/presentation.ts", import.meta.url),
    "utf8",
  );
  const manifest = JSON.parse(readFileSync(
    new URL(
      "../apps/backend/src/talli_backend/modules/company_access/capability_manifest.json",
      import.meta.url,
    ),
    "utf8",
  ));

  assert.match(eligibilityPage, /Gratis · ingen konto · ingen betaling/u);
  assert.match(eligibilityPage, /Foreløpig svar er alltid merket tydelig/u);
  assert.match(checker, /Foreløpig svar · Utenfor grensen/u);
  assert.match(checker, /komplett fra 1\. januar/u);
  assert.equal(
    manifest.outcomes.clarifyNextStep,
    "Avklar det ukjente med en regnskapsfører før du går videre.",
  );
  assert.match(presentation, /Dette betyr ikke at selskapet er utenfor Talli/u);
});

test("public legal copy identifies the real beta operator and contains no placeholders", () => {
  assert.match(ownerCopySource, /ELMER WELFIS/);
  assert.match(ownerCopySource, /930 835 978/);
  assert.match(ownerCopySource, /post@talli\.no/);
  assert.match(ownerCopySource, /En gratis plan medfører ingen betaling/i);
  assert.doesNotMatch(ownerCopySource, /\[Talli AS|XXX XXX XXX|\[Oslo tingrett\]/i);
  assert.doesNotMatch(ownerCopySource, /kontakt@talli\.no|personvern@talli\.no/i);
});

test("email signup communicates the hosted twelve-character password floor", () => {
  const signupPage = readFileSync(
    new URL("../apps/web/app/(auth)/signup/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(ownerCopySource, /passwordHelp: "Minst 12 tegn\."/u);
  assert.match(signupPage, /minLength=\{12\}/u);
});

test("launch validator rejects beta overclaims about review, payment, and delivery", () => {
  const required = `${requiredNonAffiliationCopy}\n${preProductionDirectFilingCopy}`;

  for (const overclaim of [
    "Årsoppgjøret uten regnskapsfører.",
    "Hver innsending kvalitetssikres med menneskelig kontroll.",
    "Du betaler først ved innsending.",
    "Innsendingen leveres til riktig myndighet.",
    "Trygg innsending.",
  ]) {
    const result = validateLaunchCopy(`${required}\n${overclaim}`);
    assert.equal(result.approved, false, overclaim);
    assert.ok(result.violations.length >= 1, overclaim);
  }
});

test("owner Systembruker copy distinguishes approval from verified readiness", () => {
  assert.match(ownerCopySource, /Verifiserer tilkoblingen/u);
  assert.match(ownerCopySource, /Tilkoblingen er godkjent og verifisert/u);
  assert.match(ownerCopySource, /Godkjent, men kunne ikke verifiseres for innsending/u);
  assert.match(ownerCopySource, /Klar for kontrollert innsending/u);
  assert.doesNotMatch(ownerCopySource, /new[^\n]+klar til innsending/iu);
});
