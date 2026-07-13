import { createHash } from "node:crypto";
import { XMLParser, XMLValidator } from "fast-xml-parser";

const SUPPORTED_INCOME_YEAR = 2025;
const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;
const MAX_XML_ELEMENTS = 100_000;
const MAX_XML_DEPTH = 256;
const UNSAFE_XML_PATTERN = /<!\s*(?:DOCTYPE|ENTITY)\b/iu;
const FORBIDDEN_XML_TEXT_PATTERN = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/u;
const TAX_RETURN_NAMESPACE =
  "urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5";
const BUSINESS_SPECIFICATION_NAMESPACE =
  "urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6";

export const COMPANY_TAX_RETURN_2025_SCHEMA = {
  incomeYear: SUPPORTED_INCOME_YEAR,
  taxReturnFile: "skattemeldingUpersonlig_v5_ekstern.xsd",
  taxReturnNamespace: TAX_RETURN_NAMESPACE,
  taxReturnSha256: "d8e74eda092540a974efa63cc4608fdf36754dea27f9349b3293f874f9907d52",
  businessSpecificationFile: "naeringsspesifikasjon_v6_ekstern.xsd",
  businessSpecificationNamespace: BUSINESS_SPECIFICATION_NAMESPACE,
  businessSpecificationSha256: "6300d00b31f4cb1ccd45582cef041fb78400a6d9c2d351f6f320872dbb39f8ef",
  upstreamCommit: "7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba",
} as const;

export type NoActivityCompanyTaxReturnDocumentInput = {
  organizationNumber: string;
  incomeYear: number;
  contractTaxReturnXml: string;
  currentBusinessSpecificationXml: string | null;
  noActivityConfirmed: boolean;
  hasMaterialActivity: boolean;
};

export class CompanyTaxReturnDocumentError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "CompanyTaxReturnDocumentError";
    this.code = code;
  }
}

const parser = new XMLParser({
  ignoreAttributes: false,
  removeNSPrefix: false,
  parseTagValue: false,
  trimValues: true,
  processEntities: true,
});

export function buildNoActivityCompanyTaxReturnDocuments(input: NoActivityCompanyTaxReturnDocumentInput) {
  const organizationNumber = assertOrganizationNumber(input.organizationNumber);
  if (input.incomeYear !== SUPPORTED_INCOME_YEAR) {
    throw documentError(
      "tax_return_document_year_unsupported",
      "Only the pinned 2025 company-tax-return document generation is supported.",
    );
  }
  if (!input.noActivityConfirmed) {
    throw documentError(
      "tax_return_no_activity_not_confirmed",
      "No-activity document generation requires an explicit owner confirmation.",
    );
  }
  if (input.hasMaterialActivity) {
    throw documentError(
      "tax_return_no_activity_conflicts_with_activity",
      "No-activity document generation cannot run when material activity exists.",
    );
  }
  if (input.currentBusinessSpecificationXml !== null) {
    throw documentError(
      "tax_return_business_specification_exists",
      "An existing authority business specification requires review and cannot be replaced automatically.",
    );
  }

  const contractTaxReturnXml = assertSafeXml(input.contractTaxReturnXml);
  const root = parseTaxReturnRoot(contractTaxReturnXml);
  if (root["@_xmlns"] !== TAX_RETURN_NAMESPACE) {
    throw documentError(
      "tax_return_draft_namespace_invalid",
      "The contract tax-return fixture does not use the pinned 2025 company namespace.",
    );
  }
  if (requiredScalar(root.partsnummer) !== organizationNumber) {
    throw documentError(
      "tax_return_draft_party_mismatch",
      "The contract tax-return fixture belongs to another organization.",
    );
  }
  if (requiredScalar(root.inntektsaar) !== String(input.incomeYear)) {
    throw documentError(
      "tax_return_draft_year_mismatch",
      "The contract tax-return fixture belongs to another income year.",
    );
  }

  const businessSpecificationXml = buildNoActivityBusinessSpecificationXml(
    organizationNumber,
    input.incomeYear,
  );
  return {
    taxReturnXml: contractTaxReturnXml,
    businessSpecificationXml,
    taxReturnSource: "local-contract-fixture" as const,
    businessSpecificationSource: "talli-no-activity-2025" as const,
    taxReturnSha256: sha256(contractTaxReturnXml),
    businessSpecificationSha256: sha256(businessSpecificationXml),
    schema: COMPANY_TAX_RETURN_2025_SCHEMA,
  };
}

function buildNoActivityBusinessSpecificationXml(organizationNumber: string, incomeYear: number) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<naeringsspesifikasjon xmlns="${BUSINESS_SPECIFICATION_NAMESPACE}">
  <partsreferanse>${organizationNumber}</partsreferanse>
  <inntektsaar>${incomeYear}</inntektsaar>
  <virksomhet>
    <regnskapspliktstype>
      <regnskapspliktstype>fullRegnskapsplikt</regnskapspliktstype>
    </regnskapspliktstype>
    <regnskapsperiode>
      <start>
        <dato>${incomeYear}-01-01</dato>
      </start>
      <slutt>
        <dato>${incomeYear}-12-31</dato>
      </slutt>
    </regnskapsperiode>
    <virksomhetstype>
      <virksomhetstype>oevrigSelskap</virksomhetstype>
    </virksomhetstype>
    <regeltypeForAarsregnskap>
      <regeltypeForAarsregnskap>regnskapslovensReglerForSmaaForetak</regeltypeForAarsregnskap>
    </regeltypeForAarsregnskap>
  </virksomhet>
  <skalBekreftesAvRevisor>false</skalBekreftesAvRevisor>
</naeringsspesifikasjon>
`;
}

function assertOrganizationNumber(value: unknown) {
  if (typeof value !== "string" || !/^\d{9}$/u.test(value) || !hasValidOrganizationNumberChecksum(value)) {
    throw documentError(
      "tax_return_document_party_invalid",
      "Company-tax-return document generation requires a valid Norwegian organization number.",
    );
  }
  return value;
}

function hasValidOrganizationNumberChecksum(value: string) {
  const weights = [3, 2, 7, 6, 5, 4, 3, 2] as const;
  const sum = weights.reduce((total, weight, index) => total + Number(value[index]) * weight, 0);
  const remainder = 11 - (sum % 11);
  const expected = remainder === 11 ? 0 : remainder;
  return expected !== 10 && expected === Number(value[8]);
}

function assertSafeXml(value: unknown) {
  if (typeof value !== "string" || !value.trimStart().startsWith("<")) {
    throw documentError("tax_return_draft_xml_invalid", "The contract tax-return fixture must be XML.");
  }
  if (
    new TextEncoder().encode(value).byteLength > MAX_DOCUMENT_BYTES ||
    FORBIDDEN_XML_TEXT_PATTERN.test(value)
  ) {
    throw documentError(
      "tax_return_draft_xml_invalid",
      "The contract tax-return fixture is empty, oversized, or contains invalid text.",
    );
  }
  if (UNSAFE_XML_PATTERN.test(value)) {
    throw documentError(
      "tax_return_draft_xml_unsafe",
      "The contract tax-return fixture cannot declare document types or custom entities.",
    );
  }
  assertXmlComplexity(value);
  if (XMLValidator.validate(value, { allowBooleanAttributes: false }) !== true) {
    throw documentError("tax_return_draft_xml_invalid", "The contract tax-return fixture is not well-formed XML.");
  }
  return value;
}

function assertXmlComplexity(xml: string) {
  const markup = xml
    .replace(/<!--[\s\S]*?-->/gu, "")
    .replace(/<!\[CDATA\[[\s\S]*?\]\]>/gu, "")
    .replace(/<\?[\s\S]*?\?>/gu, "");
  const tags = markup.match(/<[^>]+>/gu) ?? [];
  let depth = 0;
  let elementCount = 0;
  for (const tag of tags) {
    if (tag.startsWith("</")) {
      depth = Math.max(0, depth - 1);
      continue;
    }
    if (tag.startsWith("<!")) continue;
    elementCount += 1;
    if (!tag.endsWith("/>")) depth += 1;
    if (elementCount > MAX_XML_ELEMENTS || depth > MAX_XML_DEPTH) {
      throw documentError(
        "tax_return_draft_xml_too_complex",
        "The contract tax-return fixture is too structurally complex.",
      );
    }
  }
}

function parseTaxReturnRoot(xml: string) {
  try {
    const parsed = parser.parse(xml) as unknown;
    if (!isRecord(parsed) || !isRecord(parsed.skattemelding)) throw new Error("invalid");
    return parsed.skattemelding;
  } catch (error) {
    if (error instanceof CompanyTaxReturnDocumentError) throw error;
    throw documentError(
      "tax_return_draft_xml_invalid",
      "The contract tax-return fixture is outside the expected document structure.",
    );
  }
}

function requiredScalar(value: unknown) {
  if (typeof value !== "string" || value.length < 1 || value.length > 32) {
    throw documentError(
      "tax_return_draft_xml_invalid",
      "The contract tax-return fixture is missing required party or year fields.",
    );
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function sha256(value: string) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function documentError(code: string, message: string) {
  return new CompanyTaxReturnDocumentError(code, message);
}
