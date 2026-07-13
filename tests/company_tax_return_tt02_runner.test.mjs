import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  CompanyTaxReturnTt02RunnerError,
  inspectCurrentCompanyTaxReturnTt02,
  runNoActivityCompanyTaxReturnTt02Calculation,
} from "../app/lib/company-tax-return-tt02-runner.ts";

const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
const currentTaxReturnXml = await readFile(
  new URL("./fixtures/company_tax_return/2025-no-activity-current-tax-return.xml", import.meta.url),
  "utf8",
);

function authorityXml(result = "validertOK") {
  return `<?xml version="1.0" encoding="UTF-8"?>
<skattemeldingOgNaeringsspesifikasjonResponse xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2">
  <resultatAvValidering>${result}</resultatAvValidering>
</skattemeldingOgNaeringsspesifikasjonResponse>`;
}

test("runs only the TT02 calculation boundary and never reports the fixture as submission-valid", async () => {
  let tokenCalls = 0;
  let authorityRequest;
  const result = await runNoActivityCompanyTaxReturnTt02Calculation({
    clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
    keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
    customerOrgNumber: "310279617",
    incomeYear: 2025,
    contractTaxReturnXml: currentTaxReturnXml,
    privateKeyPem,
    tokenFetchImplementation: async () => {
      tokenCalls += 1;
      return new Response(
        JSON.stringify({
          access_token: "short-lived-test-token",
          token_type: "Bearer",
          expires_in: 120,
          scope: "skatteetaten:formueinntekt/skattemelding",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
    authorityTransport: async (request) => {
      authorityRequest = request;
      return {
        status: 200,
        headers: { "content-type": "application/xml" },
        body: new TextEncoder().encode(authorityXml()),
      };
    },
  });

  assert.equal(tokenCalls, 1);
  assert.equal(authorityRequest.method, "POST");
  assert.equal(authorityRequest.url, "https://api-test.sits.no/api/skattemelding/v2/validertest/2025/310279617");
  assert.doesNotMatch(authorityRequest.body, /dokumentreferanseTilGjeldendeDokument/u);
  assert.equal(result.environment, "test");
  assert.equal(result.operation, "calculation-only");
  assert.equal(result.validation.result, "validertOK");
  assert.equal(result.validation.calculationOnly, true);
  assert.equal(result.validation.validForSubmission, false);
  assert.equal(result.fixture.taxReturnSource, "local-contract-fixture");
  assert.equal("xml" in result.fixture, false);
});

test("rejects a cross-party fixture before requesting a token", async () => {
  let tokenCalls = 0;
  await assert.rejects(
    runNoActivityCompanyTaxReturnTt02Calculation({
      clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
      keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
      customerOrgNumber: "310279617",
      incomeYear: 2025,
      contractTaxReturnXml: currentTaxReturnXml.replace("310279617", "930835978"),
      privateKeyPem,
      tokenFetchImplementation: async () => {
        tokenCalls += 1;
        throw new Error("must not run");
      },
      authorityTransport: async () => {
        throw new Error("must not run");
      },
    }),
    (error) =>
      error instanceof CompanyTaxReturnTt02RunnerError &&
      error.code === "company_tax_return_tt02_fixture_invalid",
  );
  assert.equal(tokenCalls, 0);
});

test("inspects current TT02 documents without returning authority XML or locked values", async () => {
  const currentTaxXml = currentTaxReturnXml;
  const currentBusinessXml = "<naeringsspesifikasjon xmlns=\"urn:test\" />";
  const response = `<?xml version="1.0" encoding="UTF-8"?>
<skattemeldingOgNaeringsspesifikasjonforespoerselResponse xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2">
  <dokumenter>
    <skattemeldingdokument><id>tax-draft-2025</id><encoding>utf-8</encoding><content>${Buffer.from(currentTaxXml).toString("base64")}</content><type>skattemeldingUpersonligUtkast</type></skattemeldingdokument>
    <naeringsspesifikasjondokument><id>business-draft-2025</id><encoding>utf-8</encoding><content>${Buffer.from(currentBusinessXml).toString("base64")}</content></naeringsspesifikasjondokument>
  </dokumenter>
  <laasteFelt><laastFeltSkattemelding><verdi>secret-value</verdi><sti>skattemelding.locked</sti></laastFeltSkattemelding></laasteFelt>
</skattemeldingOgNaeringsspesifikasjonforespoerselResponse>`;
  const output = await inspectCurrentCompanyTaxReturnTt02({
    clientId: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
    keyId: "2d275f93-10a2-4839-993e-b14da2b84ad8",
    customerOrgNumber: "310279617",
    incomeYear: 2025,
    privateKeyPem,
    tokenFetchImplementation: async () =>
      new Response(
        JSON.stringify({
          access_token: "short-lived-test-token",
          token_type: "Bearer",
          expires_in: 120,
          scope: "skatteetaten:formueinntekt/skattemelding",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    authorityTransport: async () => ({
      status: 200,
      headers: { "content-type": "application/xml" },
      body: new TextEncoder().encode(response),
    }),
  });

  assert.equal(output.operation, "inspect-current-read-only");
  assert.equal(output.current.taxReturn.id, "tax-draft-2025");
  assert.match(output.current.taxReturn.sha256, /^[a-f0-9]{64}$/u);
  assert.equal(output.current.businessSpecification.id, "business-draft-2025");
  assert.equal(output.current.lockedFieldCount, 1);
  assert.equal(JSON.stringify(output).includes("secret-value"), false);
  assert.equal(JSON.stringify(output).includes("<skattemelding"), false);
});
