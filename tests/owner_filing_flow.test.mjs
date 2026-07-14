import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const filingPageSource = readFileSync(
  new URL("../app/(owner)/filing/[obligation]/page.tsx", import.meta.url),
  "utf8",
);
const filingHubSource = readFileSync(
  new URL("../app/(owner)/filing/page.tsx", import.meta.url),
  "utf8",
);
const nonRf1086Branch = filingPageSource.slice(
  filingPageSource.indexOf("// --- Skattemelding / Årsregnskap"),
  filingPageSource.indexOf("// --- Aksjonærregisteroppgaven"),
);

test("company-tax filing shows persisted pending TT02 feedback without production acceptance", () => {
  assert.match(filingPageSource, /obligationFilingString\(obligation\)/u);
  assert.match(filingPageSource, /item\.income_year === input\.incomeYear/u);
  assert.match(filingPageSource, /obligation === "skattemelding"/u);
  assert.match(filingPageSource, /mode === "test_authority"/u);
  assert.match(filingPageSource, /status === "feedback_ready"/u);
  assert.match(nonRf1086Branch, /TT02-tilbakemelding mottatt/u);
  assert.match(nonRf1086Branch, /Myndighetsutfallet venter på klassifisering/u);
  assert.match(nonRf1086Branch, /Test – ikke produksjonsinnsending/u);
  assert.match(nonRf1086Branch, /receipt_id/u);
  assert.match(filingPageSource, /archiveReference/u);
  assert.match(nonRf1086Branch, /variant="warning"/u);
  assert.doesNotMatch(nonRf1086Branch, /<SubmitButton/u);
  assert.doesNotMatch(nonRf1086Branch, /Akseptert|Godkjent av myndigheten|produksjonsinnsending fullført/iu);
});

test("filing hub does not turn pending company-tax TT02 feedback into a success badge", () => {
  assert.match(filingHubSource, /obligation === "skattemelding"/u);
  assert.match(filingHubSource, /mode === "test_authority"/u);
  assert.match(filingHubSource, /status === "feedback_ready"/u);
  assert.match(filingHubSource, /Test – ikke produksjonsinnsending/u);
  assert.match(
    filingHubSource,
    /companyTaxFeedbackPending\s*\?\s*\([\s\S]*?variant="warning"/u,
  );
});
