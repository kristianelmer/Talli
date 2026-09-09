// Frozen #153 pure payload generation and validation presentation; no credentials or I/O.
function safeString(value: unknown, fallback = ""): string {
  if (typeof value !== "string") return fallback;
  return value
    .replace(/[\u0000-\u001f\u007f]/gu, " ")
    .replace(/\s+/gu, " ")
    .trim()
    .slice(0, 500);
}

function validIncomeYear(value: number): number {
  if (!Number.isInteger(value) || value < 2000 || value > 2100) {
    throw new Error("Company tax income year must be an integer between 2000 and 2100.");
  }
  return value;
}

function validOrgNumber(value: string): string {
  if (!/^\d{9}$/u.test(value)) {
    throw new Error("Company tax organization number must contain 9 digits.");
  }
  return value;
}

function requiredXml(value: string, label: string): string {
  if (!value?.trim() || !value.trimStart().startsWith("<")) {
    throw new Error(`${label} XML is required.`);
  }
  return value;
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

type EnvelopeInput = {
  skattemeldingXml: string;
  naeringsspesifikasjonXml: string;
  companyOrgNumber: string;
  incomeYear: number;
  createdBy: string;
};

function renderEnvelope(input: EnvelopeInput & { currentDocumentReference?: string }): string {
  const skattemeldingXml = requiredXml(input.skattemeldingXml, "Company tax return");
  const naeringsspesifikasjonXml = requiredXml(input.naeringsspesifikasjonXml, "Company tax business specification");
  const currentDocumentReference = input.currentDocumentReference?.trim() ?? "";
  if (currentDocumentReference.length > 4000) {
    throw new Error("Current company tax document reference is too long.");
  }
  if (input.currentDocumentReference !== undefined && !currentDocumentReference) {
    throw new Error("Current company tax document reference is required.");
  }
  const createdBy = input.createdBy.trim();
  if (!createdBy || createdBy.length > 4000) {
    throw new Error("Company tax creator name is required.");
  }
  const companyOrgNumber = validOrgNumber(input.companyOrgNumber);
  const incomeYear = validIncomeYear(input.incomeYear);
  const taxBase64 = Buffer.from(skattemeldingXml, "utf8").toString("base64");
  const businessBase64 = Buffer.from(naeringsspesifikasjonXml, "utf8").toString("base64");

  const documentReferenceLines = currentDocumentReference
    ? [
      "  <dokumentreferanseTilGjeldendeDokument>",
      "    <dokumenttype>skattemeldingUpersonlig</dokumenttype>",
      `    <dokumentidentifikator>${escapeXml(currentDocumentReference)}</dokumentidentifikator>`,
      "  </dokumentreferanseTilGjeldendeDokument>",
    ]
    : [];

  return [
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
    '<skattemeldingOgNaeringsspesifikasjonRequest xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:request:v2">',
    "  <dokumenter>",
    "    <dokument>",
    "      <type>skattemeldingUpersonlig</type>",
    "      <encoding>utf-8</encoding>",
    `      <content>${taxBase64}</content>`,
    "    </dokument>",
    "    <dokument>",
    "      <type>naeringsspesifikasjon</type>",
    "      <encoding>utf-8</encoding>",
    `      <content>${businessBase64}</content>`,
    "    </dokument>",
    "  </dokumenter>",
    ...documentReferenceLines,
    `  <inntektsaar>${incomeYear}</inntektsaar>`,
    "  <innsendingsinformasjon>",
    "    <innsendingstype>komplett</innsendingstype>",
    `    <opprettetAv>${escapeXml(createdBy)}</opprettetAv>`,
    `    <tin>${companyOrgNumber}</tin>`,
    "    <innsendingsformaal>egenfastsetting</innsendingsformaal>",
    "  </innsendingsinformasjon>",
    "</skattemeldingOgNaeringsspesifikasjonRequest>",
    "",
  ].join("\n");
}

export function renderCompanyTaxReturnEnvelope(
  input: EnvelopeInput & { currentDocumentReference: string },
): string {
  return renderEnvelope(input);
}

export function renderCompanyTaxReturnValidationEnvelope(input: EnvelopeInput): string {
  return renderEnvelope(input);
}

export type CompanyTaxReturnValidationSummary = {
  result: "validertOK" | "validertMedFeil" | "unknown";
  deviationCodes: string[];
  guidanceCodes: string[];
  failureReasons: string[];
};

function xmlTextValues(xml: string, elementName: string): string[] {
  const qualifiedName = `(?:[A-Za-z_][\\w.-]*:)?${elementName}`;
  const pattern = new RegExp(`<${qualifiedName}\\b[^>]*>([^<]*)<\\/${qualifiedName}>`, "gu");
  return [...xml.matchAll(pattern)]
    .map((match) => safeString(match[1]))
    .filter(Boolean);
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right, "nb"));
}

export function summarizeCompanyTaxReturnValidation(
  resultXml: string,
): CompanyTaxReturnValidationSummary {
  const xml = requiredXml(resultXml, "Company tax validation result");
  const rawResult = xmlTextValues(xml, "resultatAvValidering")[0];
  const result = rawResult === "validertOK" || rawResult === "validertMedFeil"
    ? rawResult
    : "unknown";

  return {
    result,
    deviationCodes: uniqueSorted(xmlTextValues(xml, "avvikstype")),
    guidanceCodes: uniqueSorted(xmlTextValues(xml, "veiledningstype")),
    failureReasons: uniqueSorted(xmlTextValues(xml, "aarsakTilValidertMedFeil")),
  };
}

