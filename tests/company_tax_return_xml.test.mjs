import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  CompanyTaxReturnDocumentError,
  buildNoActivityCompanyTaxReturnDocuments,
} from "../app/lib/company-tax-return-documents.ts";

const fixtureDirectory = new URL("./fixtures/company_tax_return/", import.meta.url);
const fixtureTaxReturnXml = await readFile(
  new URL("2025-no-activity-current-tax-return.xml", fixtureDirectory),
  "utf8",
);
const expectedBusinessSpecificationXml = await readFile(
  new URL("2025-no-activity-business-specification.xml", fixtureDirectory),
  "utf8",
);

test("preserves the local contract tax return and builds a deterministic 2025 no-activity business specification", () => {
  const documents = buildNoActivityCompanyTaxReturnDocuments({
    organizationNumber: "310279617",
    incomeYear: 2025,
    contractTaxReturnXml: fixtureTaxReturnXml,
    currentBusinessSpecificationXml: null,
    noActivityConfirmed: true,
    hasMaterialActivity: false,
  });

  assert.equal(documents.taxReturnXml, fixtureTaxReturnXml);
  assert.equal(documents.businessSpecificationXml, expectedBusinessSpecificationXml);
  assert.equal(documents.taxReturnSource, "local-contract-fixture");
  assert.equal(documents.businessSpecificationSource, "talli-no-activity-2025");
  assert.match(documents.taxReturnSha256, /^[a-f0-9]{64}$/u);
  assert.match(documents.businessSpecificationSha256, /^[a-f0-9]{64}$/u);
  assert.equal(documents.schema.incomeYear, 2025);
  assert.equal(documents.schema.taxReturnSha256, "d8e74eda092540a974efa63cc4608fdf36754dea27f9349b3293f874f9907d52");
  assert.equal(documents.schema.businessSpecificationSha256, "6300d00b31f4cb1ccd45582cef041fb78400a6d9c2d351f6f320872dbb39f8ef");
});

test("blocks no-activity generation when activity or an existing specification is present or confirmation is absent", () => {
  const base = {
    organizationNumber: "310279617",
    incomeYear: 2025,
    contractTaxReturnXml: fixtureTaxReturnXml,
    currentBusinessSpecificationXml: null,
    noActivityConfirmed: true,
    hasMaterialActivity: false,
  };

  for (const input of [
    { ...base, noActivityConfirmed: false },
    { ...base, hasMaterialActivity: true },
    { ...base, currentBusinessSpecificationXml: expectedBusinessSpecificationXml },
  ]) {
    assert.throws(
      () => buildNoActivityCompanyTaxReturnDocuments(input),
      (error) => error instanceof CompanyTaxReturnDocumentError,
    );
  }
});

test("rejects mismatched, unsupported, and unsafe contract fixtures", () => {
  const build = (xml, overrides = {}) =>
    buildNoActivityCompanyTaxReturnDocuments({
      organizationNumber: "310279617",
      incomeYear: 2025,
      contractTaxReturnXml: xml,
      currentBusinessSpecificationXml: null,
      noActivityConfirmed: true,
      hasMaterialActivity: false,
      ...overrides,
    });

  assert.throws(
    () => build(fixtureTaxReturnXml.replace("310279617", "930835978")),
    (error) => error instanceof CompanyTaxReturnDocumentError && error.code === "tax_return_draft_party_mismatch",
  );
  assert.throws(
    () => build(fixtureTaxReturnXml.replace("2025", "2024")),
    (error) => error instanceof CompanyTaxReturnDocumentError && error.code === "tax_return_draft_year_mismatch",
  );
  assert.throws(
    () => build(fixtureTaxReturnXml.replace("ekstern:v5", "ekstern:v6")),
    (error) => error instanceof CompanyTaxReturnDocumentError && error.code === "tax_return_draft_namespace_invalid",
  );
  assert.throws(
    () => build(`<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]>${fixtureTaxReturnXml}`),
    (error) => error instanceof CompanyTaxReturnDocumentError && error.code === "tax_return_draft_xml_unsafe",
  );
  assert.throws(
    () => build(fixtureTaxReturnXml, { incomeYear: 2026 }),
    (error) => error instanceof CompanyTaxReturnDocumentError && error.code === "tax_return_document_year_unsupported",
  );
});
