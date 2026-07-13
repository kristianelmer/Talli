import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  COMPANY_TAX_RETURN_VALIDATION_BASE_URLS,
  COMPANY_TAX_RETURN_VALIDATION_SCOPE,
  CompanyTaxReturnAuthorityError,
  buildCompanyTaxReturnValidationEnvelope,
  createCompanyTaxReturnAuthorityClient,
  createFetchCompanyTaxReturnAuthorityTransport,
} from "../app/lib/company-tax-return-authority-client.ts";

const accessToken = "test-system-user-token";
const taxReturnXml = '<?xml version="1.0" encoding="UTF-8"?><skattemelding xmlns="urn:test:tax"><partsnummer>310279617</partsnummer></skattemelding>';
const businessSpecificationXml = '<?xml version="1.0" encoding="UTF-8"?><naeringsspesifikasjon xmlns="urn:test:business"><partsreferanse>310279617</partsreferanse></naeringsspesifikasjon>';

function xmlResponse(body, status = 200, contentType = "application/xml; charset=utf-8") {
  return {
    status,
    headers: { "content-type": contentType },
    body: new TextEncoder().encode(body),
  };
}

function validResponse(extra = "") {
  return `<?xml version="1.0" encoding="UTF-8"?>
<skattemeldingOgNaeringsspesifikasjonResponse xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2">
  ${extra}
  <resultatAvValidering>validertOK</resultatAvValidering>
</skattemeldingOgNaeringsspesifikasjonResponse>`;
}

test("pins the exact official API v2 authority envelope schemas", async () => {
  const expected = new Map([
    ["skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd", "7aac32c36117d0a7666ee469eaa94768296337e9e37ceab6f835ba2d8856d669"],
    ["skattemeldingognaeringsspesifikasjonresponse_v2.xsd", "fc9c100462603564198ee27e3f96abacc0be037cf9c10ba6d8d440e14ad1e237"],
    ["skattemeldingognaeringsspesifikasjonforespoerselresponse_v2_kompakt.xsd", "c718010fdf6dc6633f4a4c583c272457c1828a70518c6798ff626e0b809a5839"],
  ]);

  for (const [name, digest] of expected) {
    const source = await readFile(new URL(`../docs/filing/authority-contract/${name}`, import.meta.url));
    assert.equal(createHash("sha256").update(source).digest("hex"), digest);
  }
});

test("builds the official v2 filing-validation envelope with both UTF-8 documents and current-draft reference", () => {
  const xml = buildCompanyTaxReturnValidationEnvelope({
    mode: "filing",
    organizationNumber: "310279617",
    incomeYear: 2025,
    taxReturnXml,
    businessSpecificationXml,
    currentTaxReturnDocumentId: "SKI:755:14847",
  });

  assert.match(xml, /xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:request:v2"/u);
  assert.match(xml, /<type>skattemeldingUpersonlig<\/type>/u);
  assert.match(xml, /<type>naeringsspesifikasjon<\/type>/u);
  assert.match(xml, /<dokumenttype>skattemeldingUpersonlig<\/dokumenttype>\s*<dokumentidentifikator>SKI:755:14847<\/dokumentidentifikator>/u);
  assert.match(xml, /<inntektsaar>2025<\/inntektsaar>/u);
  assert.match(xml, /<innsendingstype>komplett<\/innsendingstype>/u);
  assert.match(xml, /<opprettetAv>Talli<\/opprettetAv>/u);
  assert.match(xml, /<tin>310279617<\/tin>/u);
  assert.match(xml, /<innsendingsformaal>egenfastsetting<\/innsendingsformaal>/u);

  const encodedDocuments = [...xml.matchAll(/<content>([^<]+)<\/content>/gu)].map((match) => match[1]);
  assert.deepEqual(encodedDocuments.map((value) => Buffer.from(value, "base64").toString("utf8")), [
    taxReturnXml,
    businessSpecificationXml,
  ]);
});

test("requires a current Skatteetaten draft reference for filing validation and keeps validertest explicitly calculation-only", async () => {
  assert.throws(
    () => buildCompanyTaxReturnValidationEnvelope({
      mode: "filing",
      organizationNumber: "310279617",
      incomeYear: 2025,
      taxReturnXml,
      businessSpecificationXml,
    }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_current_document_required",
  );

  let captured;
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken,
    transport: async (request) => {
      captured = request;
      return xmlResponse(validResponse());
    },
  });
  const result = await client.calculateWithoutCurrentDraft({
    organizationNumber: "310279617",
    incomeYear: 2025,
    taxReturnXml,
    businessSpecificationXml,
  });

  assert.equal(captured.url, `${COMPANY_TAX_RETURN_VALIDATION_BASE_URLS.test}/validertest/2025/310279617`);
  assert.doesNotMatch(captured.body, /dokumentreferanseTilGjeldendeDokument/u);
  assert.equal(result.calculationOnly, true);
  assert.equal(result.validForSubmission, false);
});

test("posts filing validation only to the fixed authority endpoint and returns bounded structured feedback", async () => {
  let captured;
  const response = `<?xml version="1.0" encoding="UTF-8"?>
<skattemeldingOgNaeringsspesifikasjonResponse xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2">
  <avvikEtterBeregning><avvik><avvikstype>BeloepEndret</avvikstype><forekomstidentifikator>item-1</forekomstidentifikator><mottattVerdi>100</mottattVerdi><beregnetVerdi>97</beregnetVerdi><avvikIVerdi>3</avvikIVerdi><sti>skattemelding.inntekt</sti></avvik></avvikEtterBeregning>
  <veiledningEtterKontroll><veiledning><veiledningstype>KontrollerUtbytte</veiledningstype><hjelpetekst>Kontroller beløpet &amp; dokumentasjonen.</hjelpetekst><betjeningsstrategi>dialog</betjeningsstrategi><sti>skattemelding.utbytte</sti></veiledning></veiledningEtterKontroll>
  <avvikVedValidering><avvik><avvikstype>UgyldigFelt</avvikstype><oevrigInformasjon>Feltet må rettes.</oevrigInformasjon><sti>skattemelding.felt</sti></avvik></avvikVedValidering>
  <resultatAvValidering>validertMedFeil</resultatAvValidering>
  <aarsakTilValidertMedFeil>Valideringsavvik</aarsakTilValidertMedFeil>
</skattemeldingOgNaeringsspesifikasjonResponse>`;
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken,
    transport: async (request) => {
      captured = request;
      return xmlResponse(response);
    },
  });

  const result = await client.validateForFiling({
    organizationNumber: "310279617",
    incomeYear: 2025,
    taxReturnXml,
    businessSpecificationXml,
    currentTaxReturnDocumentId: "SKI:755:14847",
  });

  assert.equal(COMPANY_TAX_RETURN_VALIDATION_SCOPE, "skatteetaten:formueinntekt/skattemelding");
  assert.equal(captured.method, "POST");
  assert.equal(captured.url, `${COMPANY_TAX_RETURN_VALIDATION_BASE_URLS.test}/valider/2025/310279617`);
  assert.equal(captured.headers.Authorization, `Bearer ${accessToken}`);
  assert.equal(captured.headers.Accept, "application/xml");
  assert.equal(captured.headers["Content-Type"], "application/xml; charset=utf-8");
  assert.equal(result.result, "validertMedFeil");
  assert.equal(result.calculationOnly, false);
  assert.equal(result.validForSubmission, false);
  assert.deepEqual(result.reasons, ["Valideringsavvik"]);
  assert.deepEqual(result.feedback.map(({ level, source, code, message, path }) => ({ level, source, code, message, path })), [
    { level: "warning", source: "calculation", code: "BeloepEndret", message: "Beregnet verdi avviker fra mottatt verdi.", path: "skattemelding.inntekt" },
    { level: "info", source: "guidance", code: "KontrollerUtbytte", message: "Kontroller beløpet & dokumentasjonen.", path: "skattemelding.utbytte" },
    { level: "error", source: "validation", code: "UgyldigFelt", message: "Feltet må rettes.", path: "skattemelding.felt" },
    { level: "error", source: "validation", code: "company_tax_return_validation_failed", message: "Valideringsavvik", path: undefined },
  ]);
  assert.equal(result.feedback[0].receivedValue, "100");
  assert.equal(result.feedback[0].calculatedValue, "97");
  assert.equal(result.feedback[0].difference, "3");
});

test("returns calculated authority documents as verified UTF-8 XML with content identity", async () => {
  const calculatedXml = '<?xml version="1.0" encoding="UTF-8"?><skattemelding xmlns="urn:test:calculated" />';
  const documents = `<dokumenter><dokument><type>skattemeldingUpersonligEtterBeregning</type><encoding>utf-8</encoding><content>${Buffer.from(calculatedXml).toString("base64")}</content></dokument></dokumenter>`;
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken,
    transport: async () => xmlResponse(validResponse(documents)),
  });

  const result = await client.validateForFiling({
    organizationNumber: "310279617",
    incomeYear: 2025,
    taxReturnXml,
    businessSpecificationXml,
    currentTaxReturnDocumentId: "draft-1",
  });

  assert.equal(result.validForSubmission, true);
  assert.equal(result.documents.length, 1);
  assert.equal(result.documents[0].type, "skattemeldingUpersonligEtterBeregning");
  assert.equal(result.documents[0].xml, calculatedXml);
  assert.match(result.documents[0].sha256, /^[0-9a-f]{64}$/u);
  assert.equal(result.documents[0].byteLength, Buffer.byteLength(calculatedXml));
});

test("gets the current company draft and preserves its document reference for filing validation", async () => {
  let captured;
  const currentTaxXml = '<skattemelding xmlns="urn:test:current" />';
  const currentBusinessXml = '<naeringsspesifikasjon xmlns="urn:test:current-business" />';
  const response = `<?xml version="1.0" encoding="UTF-8"?>
<skattemeldingOgNaeringsspesifikasjonforespoerselResponse xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2">
  <dokumenter>
    <skattemeldingdokument><id>SKI:755:14847</id><encoding>utf-8</encoding><content>${Buffer.from(currentTaxXml).toString("base64")}</content><type>skattemeldingUpersonligUtkast</type></skattemeldingdokument>
    <naeringsspesifikasjondokument><id>NS:755:14848</id><encoding>utf-8</encoding><content>${Buffer.from(currentBusinessXml).toString("base64")}</content></naeringsspesifikasjondokument>
  </dokumenter>
  <laasteFelt><laastFeltSkattemelding><forekomstidentifikator>locked-1</forekomstidentifikator><verdi>yes</verdi><sti>skattemelding.laas</sti></laastFeltSkattemelding></laasteFelt>
</skattemeldingOgNaeringsspesifikasjonforespoerselResponse>`;
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken,
    transport: async (request) => {
      captured = request;
      return xmlResponse(response);
    },
  });

  const draft = await client.getCurrentDraft({ organizationNumber: "310279617", incomeYear: 2025 });

  assert.equal(captured.method, "GET");
  assert.equal(captured.url, `${COMPANY_TAX_RETURN_VALIDATION_BASE_URLS.test}/2025/310279617`);
  assert.equal(captured.body, undefined);
  assert.deepEqual(draft.taxReturn, {
    id: "SKI:755:14847",
    type: "skattemeldingUpersonligUtkast",
    encoding: "utf-8",
    xml: currentTaxXml,
  });
  assert.equal(draft.businessSpecification.id, "NS:755:14848");
  assert.equal(draft.businessSpecification.xml, currentBusinessXml);
  assert.deepEqual(draft.lockedFields, [{ document: "skattemeldingUpersonlig", occurrenceId: "locked-1", value: "yes", path: "skattemelding.laas", information: undefined }]);
});

test("rejects dangerous or malformed XML before transport and rejects unsafe authority XML", async () => {
  let calls = 0;
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken,
    transport: async () => {
      calls += 1;
      return xmlResponse('<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]><x>&leak;</x>');
    },
  });

  await assert.rejects(
    client.validateForFiling({
      organizationNumber: "310279617",
      incomeYear: 2025,
      taxReturnXml: '<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]><x>&leak;</x>',
      businessSpecificationXml,
      currentTaxReturnDocumentId: "draft-1",
    }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_xml_unsafe",
  );
  assert.equal(calls, 0);

  const deeplyNested = `${"<x>".repeat(257)}value${"</x>".repeat(257)}`;
  await assert.rejects(
    client.validateForFiling({
      organizationNumber: "310279617",
      incomeYear: 2025,
      taxReturnXml: deeplyNested,
      businessSpecificationXml,
      currentTaxReturnDocumentId: "draft-1",
    }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_xml_too_complex",
  );
  assert.equal(calls, 0);

  await assert.rejects(
    client.validateForFiling({
      organizationNumber: "310279617",
      incomeYear: 2025,
      taxReturnXml,
      businessSpecificationXml,
      currentTaxReturnDocumentId: "draft-1",
    }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_response_unsafe",
  );
  assert.equal(calls, 1);
});

test("never exposes bearer tokens or provider response bodies in failures", async () => {
  const secret = "secret-system-user-token";
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken: secret,
    transport: async () => xmlResponse(`<error>${secret} confidential taxpayer data</error>`, 400),
  });

  await assert.rejects(
    client.validateForFiling({
      organizationNumber: "310279617",
      incomeYear: 2025,
      taxReturnXml,
      businessSpecificationXml,
      currentTaxReturnDocumentId: "draft-1",
    }),
    (error) => {
      assert.ok(error instanceof CompanyTaxReturnAuthorityError);
      assert.equal(error.code, "company_tax_return_http_400");
      assert.equal(error.status, 400);
      assert.equal(error.retryable, false);
      assert.doesNotMatch(error.message, new RegExp(secret, "u"));
      assert.doesNotMatch(error.message, /confidential taxpayer data/u);
      return true;
    },
  );
});

test("the default transport refuses redirects and bounds streamed responses", async () => {
  let init;
  const transport = createFetchCompanyTaxReturnAuthorityTransport(async (_url, requestInit) => {
    init = requestInit;
    return new Response("<ok />", { status: 200, headers: { "content-type": "application/xml" } });
  });
  const response = await transport({
    method: "GET",
    url: `${COMPANY_TAX_RETURN_VALIDATION_BASE_URLS.test}/ping`,
    headers: { Accept: "application/xml" },
    timeoutMs: 1_000,
    maxResponseBytes: 64,
  });

  assert.equal(init.redirect, "error");
  assert.ok(init.signal instanceof AbortSignal);
  assert.equal(new TextDecoder().decode(response.body), "<ok />");

  const oversized = createFetchCompanyTaxReturnAuthorityTransport(async () =>
    new Response("x".repeat(65), { status: 200, headers: { "content-type": "application/xml" } }),
  );
  await assert.rejects(
    oversized({
      method: "GET",
      url: `${COMPANY_TAX_RETURN_VALIDATION_BASE_URLS.test}/ping`,
      headers: { Accept: "application/xml" },
      timeoutMs: 1_000,
      maxResponseBytes: 64,
    }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_response_too_large",
  );
});

test("rejects non-company identifiers, unbounded responses, and invalid response content types", async () => {
  assert.throws(
    () => createCompanyTaxReturnAuthorityClient({ environment: "test", accessToken: "short" }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_access_token_invalid",
  );

  const oversized = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken,
    maxResponseBytes: 128,
    transport: async () => xmlResponse("x".repeat(129)),
  });
  await assert.rejects(
    oversized.getCurrentDraft({ organizationNumber: "310279617", incomeYear: 2025 }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_response_too_large",
  );

  const wrongType = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken,
    transport: async () => xmlResponse("{}", 200, "application/json"),
  });
  await assert.rejects(
    wrongType.getCurrentDraft({ organizationNumber: "310279617", incomeYear: 2025 }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_response_content_type_invalid",
  );

  await assert.rejects(
    wrongType.getCurrentDraft({ organizationNumber: "123", incomeYear: 2025 }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_organization_number_invalid",
  );

  const wrongNamespace = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    accessToken,
    transport: async () => xmlResponse('<skattemeldingOgNaeringsspesifikasjonResponse xmlns="urn:not-skatteetaten"><resultatAvValidering>validertOK</resultatAvValidering></skattemeldingOgNaeringsspesifikasjonResponse>'),
  });
  await assert.rejects(
    wrongNamespace.validateForFiling({
      organizationNumber: "310279617",
      incomeYear: 2025,
      taxReturnXml,
      businessSpecificationXml,
      currentTaxReturnDocumentId: "draft-1",
    }),
    (error) => error instanceof CompanyTaxReturnAuthorityError && error.code === "company_tax_return_response_invalid",
  );
});
