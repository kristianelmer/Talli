import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  inviteOnlyBetaCopy,
  preProductionDirectFilingCopy,
  requiredNonAffiliationCopy,
  validateLaunchCopy,
} from "../apps/web/app/lib/launch-copy.ts";

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

test("public homepage is a truthful invite-only free beta invitation", () => {
  const publicPage = readFileSync(new URL("../apps/web/app/page.tsx", import.meta.url), "utf8");

  assert.equal(inviteOnlyBetaCopy, "Invitasjonsbasert gratis beta");
  assert.match(ownerCopySource, /inviteOnlyBetaCopy/);
  assert.match(ownerCopySource, /Produksjonsinnsending og live betaling er ikke tilgjengelig i betaen/i);
  assert.match(ownerCopySource, /Be om betatilgang/i);
  assert.match(ownerCopySource, /requiredNonAffiliationCopy/);
  assert.match(ownerCopySource, /preProductionDirectFilingCopy/);
  assert.match(publicPage, /c\.disclosures/);
  assert.match(publicPage, /mailto:post@talli\.no/);

  assert.doesNotMatch(ownerCopySource, /uten regnskapsfører/i);
  assert.doesNotMatch(ownerCopySource, /menneskelig kontroll/i);
  assert.doesNotMatch(ownerCopySource, /betaler først ved innsending/i);
  assert.doesNotMatch(ownerCopySource, /leveres til riktig myndighet/i);
  assert.doesNotMatch(ownerCopySource, /trygg innsending/i);
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
